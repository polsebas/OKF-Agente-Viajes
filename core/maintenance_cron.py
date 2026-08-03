"""Procesos de mantenimiento deterministas, invocados por el scheduler.

Ningun tool de este modulo se expone al agente Agno. `apply_tag_rewrite`
vive exclusivamente aca: es codigo determinista (edicion de YAML), nunca una
completion de LLM, y solo corre tras aprobacion humana explicita del plan.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import (
    get_judge_model,
    get_tag_similarity_threshold,
    get_vault_root,
)
from core.maintenance_report import write_maintenance_report
from core.validation_engine import build_default_engine
from schemas.okf_concept import OKFConcept
from schemas.tag_taxonomy import TagMergeCandidate, TagMergePlan, TagTaxonomy
from schemas.validation import ValidationResult
from tools.okf_adapter import parse_bundle
from tools.tag_taxonomy import find_candidate_synonyms, load_taxonomy, resolve_tag

logger = logging.getLogger("okf_travel_agent.maintenance_cron")

PENDING_MERGES_DIRNAME = ".okf_meta/pending_merges"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_TAXONOMY_SNAPSHOT = (
    "skills/tag-taxonomy-conventions/references/taxonomy-snapshot.md"
)
_CANONICALIZATION_WEEKDAY = 6  # domingo (datetime.weekday: lunes=0)


# ---------------------------------------------------------------------------
# Job 1: scan de integridad. 100% deterministico, cero llamadas a LLM.
# ---------------------------------------------------------------------------


def run_integrity_scan(bundle_root: str | None = None) -> ValidationResult:
    """Full deterministic scan. No LLM calls. Runs nightly."""
    bundle_root = bundle_root or get_vault_root()
    concepts = parse_bundle(bundle_root)
    known_tags = _known_tags(concepts)
    engine = build_default_engine(known_tags=known_tags)
    result = engine.validate_bundle(concepts)

    error_count = sum(1 for issue in result.issues if issue.severity.value == "error")
    warning_count = len(result.issues) - error_count
    logger.info(
        "Integrity scan sobre %s: %s concepts, %s errores, %s warnings, passed=%s",
        bundle_root,
        len(concepts),
        error_count,
        warning_count,
        result.passed,
    )
    for issue in result.issues:
        logger.warning("[%s] %s (%s): %s", issue.severity.value, issue.concept_id, issue.rule_name, issue.message)
    return result


def _known_tags(bundle: dict[str, OKFConcept]) -> set[str]:
    taxonomy = load_taxonomy(bundle)
    known = set(taxonomy.entries.keys())
    for entry in taxonomy.entries.values():
        known.update(entry.aliases)
    return known


# ---------------------------------------------------------------------------
# Job 2: canonicalizacion de tags — solo propone, nunca aplica.
# ---------------------------------------------------------------------------


def _plans_dir(bundle_root: str) -> Path:
    return Path(bundle_root) / PENDING_MERGES_DIRNAME


def _load_plan(bundle_root: str, plan_id: str) -> TagMergePlan:
    plan_path = _plans_dir(bundle_root) / f"{plan_id}.json"
    return TagMergePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))


def _load_all_plans(bundle_root: str) -> list[TagMergePlan]:
    plans_path = _plans_dir(bundle_root)
    if not plans_path.exists():
        return []
    plans = []
    for plan_path in sorted(plans_path.glob("*.json")):
        plans.append(TagMergePlan.model_validate_json(plan_path.read_text(encoding="utf-8")))
    return plans


def _count_pending_plans(bundle_root: str) -> int:
    return sum(1 for plan in _load_all_plans(bundle_root) if plan.status == "pending")


def _persist_plan(vault_root: str, plan: TagMergePlan) -> None:
    plans_dir = _plans_dir(vault_root)
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan.plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def _tags_in_use(bundle: dict[str, OKFConcept]) -> set[str]:
    used = set()
    for concept in bundle.values():
        used.update(concept.tags)
    return used


def _concept_ids_with_tag(bundle: dict[str, OKFConcept], tag: str) -> list[str]:
    return [concept_id for concept_id, concept in bundle.items() if tag in concept.tags]


def _alias_resolution_candidates(bundle, taxonomy) -> list[TagMergeCandidate]:
    """Tags que ya son un alias CONOCIDO de un canonico en la taxonomia, pero
    que todavia estan escritos en su forma no-canonica en algun archivo. No
    hace falta un LLM ni embeddings para esto — resolve_tag() ya lo resuelve
    de forma determinista."""
    candidates = []
    for tag in sorted(_tags_in_use(bundle)):
        canonical = resolve_tag(tag, taxonomy)
        if canonical != tag:
            candidates.append(
                TagMergeCandidate(
                    proposed_canonical=canonical,
                    tags_to_merge=[tag],
                    similarity_score=1.0,
                    affected_concept_ids=_concept_ids_with_tag(bundle, tag),
                    rationale=f"'{tag}' ya es un alias conocido de '{canonical}' en la taxonomia.",
                )
            )
    return candidates


def _unresolved_tags(bundle, taxonomy) -> list[str]:
    """Tags que ni son canonicos ni son alias conocidos de nada — candidatos
    a que el pipeline de embeddings los compare contra los canonicos."""
    known_canonicals = set(taxonomy.entries.keys())
    unresolved = []
    for tag in sorted(_tags_in_use(bundle)):
        if tag in known_canonicals:
            continue
        if resolve_tag(tag, taxonomy) != tag:
            continue  # ya es un alias conocido, lo cubre _alias_resolution_candidates
        unresolved.append(tag)
    return unresolved


def _embedding_candidates(bundle, taxonomy, threshold: float) -> list[TagMergeCandidate]:
    unresolved = _unresolved_tags(bundle, taxonomy)
    if not unresolved:
        return []
    candidates = find_candidate_synonyms(unresolved, taxonomy, threshold=threshold)
    for candidate in candidates:
        affected: set[str] = set()
        for tag in candidate.tags_to_merge:
            affected.update(_concept_ids_with_tag(bundle, tag))
        candidate.affected_concept_ids = sorted(affected)
    return candidates


def _judge_candidates(candidates: list[TagMergeCandidate]) -> list[TagMergeCandidate]:
    """Unico punto donde un LLM toca el pipeline de tags: una llamada
    acotada (temp 0.0, sin historial, single input/output) que solo llena
    `rationale` en lenguaje llano y puede rechazar un candidato bajandole el
    similarity_score a 0. Nunca escribe archivos por su cuenta."""
    from agno.agent import Agent
    from pydantic import BaseModel

    class TagMergeJudgment(BaseModel):
        approved: bool
        rationale: str

    judge = Agent(
        model=get_judge_model(),
        instructions=(
            "Te doy un candidato de fusion de tags de un itinerario de viaje: "
            "los tags a fusionar y el tag canonico propuesto. Decidi si tiene "
            "sentido semantico fusionarlos y escribi una razon breve, en "
            "lenguaje llano, sin inventar hechos del itinerario que no te "
            "di. No tenes historial de conversacion ni tools."
        ),
        output_schema=TagMergeJudgment,
        add_history_to_context=False,
    )

    judged = []
    for candidate in candidates:
        prompt = (
            f"Tags a fusionar: {candidate.tags_to_merge}. "
            f"Canonico propuesto: '{candidate.proposed_canonical}'. "
            f"Similitud coseno medida: {candidate.similarity_score:.3f}."
        )
        try:
            response = judge.run(prompt)
            judgment: TagMergeJudgment = response.content
            candidate.rationale = judgment.rationale
            if not judgment.approved:
                candidate.similarity_score = 0.0
        except Exception as exc:  # sin credenciales/red disponibles: no bloquea el pipeline
            logger.warning("Pase de juez LLM omitido para %s: %s", candidate.tags_to_merge, exc)
        judged.append(candidate)
    return judged


def run_tag_canonicalization(
    bundle_root: str | None = None,
    use_judge: bool = False,
) -> list[TagMergePlan]:
    """
    Always PROPOSES only. Never applies. Writes TagMergePlan objects with
    status='pending' to .okf_meta/pending_merges/. Returns the plans created
    this run, for the report.
    """
    bundle_root = bundle_root or get_vault_root()

    bundle = parse_bundle(bundle_root)
    taxonomy = load_taxonomy(bundle)

    candidates = _alias_resolution_candidates(bundle, taxonomy)
    candidates += _embedding_candidates(bundle, taxonomy, threshold=get_tag_similarity_threshold())

    if use_judge and candidates:
        candidates = _judge_candidates(candidates)

    actionable = [c for c in candidates if c.similarity_score > 0.0]
    if not actionable:
        return []

    plan = TagMergePlan(
        plan_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=actionable,
        status="pending",
    )
    _persist_plan(bundle_root, plan)
    return [plan]


# ---------------------------------------------------------------------------
# apply_tag_rewrite: NUNCA se expone como tool de Agno. Codigo puramente
# determinista, invocado solo desde apply_approved_plans tras aprobacion humana.
# ---------------------------------------------------------------------------


def regenerate_taxonomy_snapshot(
    taxonomy: TagTaxonomy,
    output_path: str = _DEFAULT_TAXONOMY_SNAPSHOT,
) -> None:
    """
    Pure deterministic serialization of TagTaxonomy -> the markdown reference
    file consumed by the tag-taxonomy-conventions runtime skill.
    Called only from apply_tag_rewrite's success path. Never called from
    agent-facing code — the running agent reads this file, it does not write it.
    """
    lines = ["<!-- AUTO-GENERATED by core/maintenance_cron.py — do not edit by hand -->"]
    for entry in taxonomy.entries.values():
        lines.append(f"## {entry.canonical}")
        lines.append(f"canonical: {entry.canonical}")
        lines.append(f"aliases: [{', '.join(entry.aliases)}]")
        lines.append(f"children: [{', '.join(entry.children)}]")
        lines.append("")
    path = Path(output_path)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _apply_tag_rewrite(
    bundle_root: str,
    plan: TagMergePlan,
    snapshot_path: str = _DEFAULT_TAXONOMY_SNAPSHOT,
) -> ValidationResult:
    from tools.okf_adapter import _git_commit, _write_concept_file, invalidate_bundle_cache

    bundle = parse_bundle(bundle_root)
    tag_rewrite_map: dict[str, str] = {}
    for candidate in plan.candidates:
        if candidate.similarity_score <= 0.0:
            continue  # el juez lo rechazo
        for tag in candidate.tags_to_merge:
            tag_rewrite_map[tag] = candidate.proposed_canonical

    if not tag_rewrite_map:
        plan.status = "failed"
        plan.failure_reason = "El plan no tiene candidatos accionables para reescribir."
        _persist_plan(bundle_root, plan)
        return ValidationResult(passed=True, issues=[])

    touched_concept_ids = []
    for concept_id, concept in bundle.items():
        if not any(tag in tag_rewrite_map for tag in concept.tags):
            continue
        new_tags = sorted({tag_rewrite_map.get(tag, tag) for tag in concept.tags})
        updated = concept.model_copy(update={"tags": new_tags})
        bundle[concept_id] = updated
        _write_concept_file(bundle_root, updated)
        touched_concept_ids.append(concept_id)

    if not touched_concept_ids:
        plan.status = "applied"
        _persist_plan(bundle_root, plan)
        return ValidationResult(passed=True, issues=[])

    engine = build_default_engine(known_tags=_known_tags(bundle))
    result = engine.validate_bundle(bundle)

    commit_message = f"agent: apply_tag_rewrite on {len(touched_concept_ids)} concepts"
    from git import Repo

    repo = Repo(bundle_root)

    if not result.passed:
        logger.error(
            "apply_tag_rewrite dejo el bundle invalido, revirtiendo commit: %s", result.issues
        )
        _git_commit(bundle_root, commit_message)
        repo.git.revert("--no-edit", "HEAD")
        plan.status = "failed"
        plan.failure_reason = (
            f"Validacion post-rewrite fallo con {len(result.issues)} issue(s); commit revertido."
        )
    else:
        # Solo tras validate_bundle OK: regenera el snapshot del skill y
        # committea junto con los cambios de contenido (si el path cae
        # dentro del vault, git add -A lo incluye en el mismo commit).
        regenerate_taxonomy_snapshot(load_taxonomy(bundle), output_path=snapshot_path)
        _git_commit(bundle_root, commit_message)
        plan.status = "applied"
        plan.failure_reason = None

    invalidate_bundle_cache()
    _persist_plan(bundle_root, plan)
    return result


def apply_approved_plans(
    bundle_root: str | None = None,
    snapshot_path: str = _DEFAULT_TAXONOMY_SNAPSHOT,
) -> list[TagMergePlan]:
    """
    Scans .okf_meta/pending_merges/*.json for status == 'approved' only.
    For each: applies the rewrite (deterministic code, same as
    apply_tag_rewrite from the base prompt), re-validates the bundle,
    commits to git, sets status -> 'applied' on success or 'failed' with a
    reason on failure (kept, not deleted). Plans still 'pending' are left
    untouched — this function never applies anything a human hasn't
    explicitly approved.
    Returns the list of plans it acted on, for the report.
    """
    bundle_root = bundle_root or get_vault_root()
    acted_on: list[TagMergePlan] = []

    for plan in _load_all_plans(bundle_root):
        if plan.status != "approved":
            continue
        _apply_tag_rewrite(bundle_root, plan, snapshot_path=snapshot_path)
        acted_on.append(_load_plan(bundle_root, plan.plan_id))

    return acted_on


# ---------------------------------------------------------------------------
# Orchestrador nocturno + scheduling unico.
# ---------------------------------------------------------------------------


def run_nightly_maintenance(bundle_root: str | None = None) -> None:
    """
    The single scheduled entrypoint. Orchestrates:
      1. run_integrity_scan() — every night
      2. run_tag_canonicalization() — only on the scheduled weekly day
      3. apply_approved_plans() — every night (cheap no-op if nothing approved)
    Then calls write_maintenance_report() ONCE with the combined results.
    """
    bundle_root = bundle_root or get_vault_root()

    integrity_result = run_integrity_scan(bundle_root)

    new_candidates: list[TagMergePlan] = []
    if datetime.now(timezone.utc).weekday() == _CANONICALIZATION_WEEKDAY:
        new_candidates = run_tag_canonicalization(bundle_root)

    applied_plans = apply_approved_plans(bundle_root)
    pending_count = _count_pending_plans(bundle_root)

    write_maintenance_report(
        integrity_result=integrity_result,
        new_candidates=new_candidates,
        applied_plans=applied_plans,
        pending_count=pending_count,
        bundle_root=bundle_root,
    )


def start_scheduler(bundle_root: str | None = None) -> BackgroundScheduler:
    bundle_root = bundle_root or get_vault_root()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_nightly_maintenance,
        CronTrigger(hour=3, minute=0),
        args=[bundle_root],
        id="okf_nightly_maintenance",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
