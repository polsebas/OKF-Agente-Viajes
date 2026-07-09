"""Procesos de mantenimiento deterministas, invocados por el scheduler.

Ningun tool de este modulo se expone al agente Agno. `apply_tag_rewrite`
vive exclusivamente aca: es codigo determinista (edicion de YAML), nunca una
completion de LLM, y solo corre si `auto_apply=True` — que por default es
False.
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.config import (
    get_judge_model,
    get_tag_canonicalization_auto_apply,
    get_tag_similarity_threshold,
    get_vault_root,
)
from core.validation_engine import build_default_engine
from schemas.okf_concept import OKFConcept
from schemas.tag_taxonomy import TagMergeCandidate, TagMergePlan
from schemas.validation import ValidationResult
from tools.okf_adapter import parse_bundle
from tools.tag_taxonomy import find_candidate_synonyms, load_taxonomy, resolve_tag

logger = logging.getLogger("okf_travel_agent.maintenance_cron")

PENDING_MERGES_DIRNAME = ".okf_meta/pending_merges"


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
# Job 2: canonicalizacion de tags.
# ---------------------------------------------------------------------------


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


def _persist_plan(vault_root: str, plan: TagMergePlan) -> None:
    plans_dir = Path(vault_root) / PENDING_MERGES_DIRNAME
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan.plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def run_tag_canonicalization(
    bundle_root: str | None = None,
    auto_apply: bool | None = None,
    use_judge: bool = False,
) -> TagMergePlan:
    """
    1. Parse bundle, load taxonomy.
    2. Collect all tags in use, find those not in taxonomy.
    3. find_candidate_synonyms() -> embedding-based candidates.
    4. Optional: pase de juez LLM acotado (use_judge=True) para llenar
       `rationale` y confirmar/rechazar — unico lugar donde un LLM toca el
       pipeline de tags, nunca escribe archivos.
    5. Persiste el TagMergePlan en .okf_meta/pending_merges/.
    6. Si auto_apply=True: reescribe frontmatter de forma determinista,
       re-valida el bundle completo, commit git. Si la validacion post-
       rewrite falla, revierte el commit automaticamente.
    """
    bundle_root = bundle_root or get_vault_root()
    auto_apply = get_tag_canonicalization_auto_apply() if auto_apply is None else auto_apply

    bundle = parse_bundle(bundle_root)
    taxonomy = load_taxonomy(bundle)

    candidates = _alias_resolution_candidates(bundle, taxonomy)
    candidates += _embedding_candidates(bundle, taxonomy, threshold=get_tag_similarity_threshold())

    if use_judge and candidates:
        candidates = _judge_candidates(candidates)

    plan = TagMergePlan(
        plan_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
        status="pending",
    )
    _persist_plan(bundle_root, plan)

    if auto_apply:
        _apply_tag_rewrite(bundle_root, plan)

    return plan


# ---------------------------------------------------------------------------
# apply_tag_rewrite: NUNCA se expone como tool de Agno. Codigo puramente
# determinista, invocado solo desde este cron cuando auto_apply=True.
# ---------------------------------------------------------------------------


def _apply_tag_rewrite(bundle_root: str, plan: TagMergePlan) -> ValidationResult:
    from tools.okf_adapter import _git_commit, _write_concept_file, invalidate_bundle_cache

    bundle = parse_bundle(bundle_root)
    tag_rewrite_map: dict[str, str] = {}
    for candidate in plan.candidates:
        if candidate.similarity_score <= 0.0:
            continue  # el juez lo rechazo
        for tag in candidate.tags_to_merge:
            tag_rewrite_map[tag] = candidate.proposed_canonical

    if not tag_rewrite_map:
        plan.status = "rejected"
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
    _git_commit(bundle_root, commit_message)

    from git import Repo

    repo = Repo(bundle_root)

    if not result.passed:
        logger.error(
            "apply_tag_rewrite dejo el bundle invalido, revirtiendo commit: %s", result.issues
        )
        repo.git.revert("--no-edit", "HEAD")
        plan.status = "rejected"
    else:
        plan.status = "applied"

    invalidate_bundle_cache()
    _persist_plan(bundle_root, plan)
    return result


# ---------------------------------------------------------------------------
# Scheduling: integridad nocturna, canonicalizacion semanal. auto_apply
# queda en False por default y NO se hardcodea en True — es una decision
# abierta que el usuario debe revisar tras varias corridas en dry-run.
# ---------------------------------------------------------------------------


def start_scheduler(bundle_root: str | None = None) -> BackgroundScheduler:
    bundle_root = bundle_root or get_vault_root()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_integrity_scan,
        CronTrigger(hour=3, minute=0),
        args=[bundle_root],
        id="okf_integrity_scan_nightly",
        replace_existing=True,
    )
    scheduler.add_job(
        run_tag_canonicalization,
        CronTrigger(day_of_week="sun", hour=4, minute=0),
        args=[bundle_root],
        kwargs={"auto_apply": get_tag_canonicalization_auto_apply()},
        id="okf_tag_canonicalization_weekly",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
