"""OKF adapter: unico punto de lectura y escritura del bundle (vault Obsidian).

Principio rector: el LLM nunca orquesta control de flujo de validacion ni de
reescritura masiva. Las funciones de escritura de este modulo corren
validation_engine.validate_concept() en codigo determinista ANTES de tocar
disco; si falla con severidad ERROR, se levanta OKFValidationError y no se
escribe nada (Arq. 5.4, Error as Observation: el detalle estructurado del
fallo viaja en la excepcion, no se enmascara).

`apply_tag_rewrite` NO vive aca ni se expone como tool de Agno — vive solo en
core/maintenance_cron.py, invocado por el scheduler, nunca por el agente.
"""

import hashlib
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import frontmatter
from agno.tools import tool
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from core.config import get_vault_root
from core.validation_engine import build_default_engine, content_hash
from schemas.okf_concept import OKFConcept
from schemas.tag_taxonomy import TagMergeCandidate, TagMergePlan
from schemas.validation import ValidationIssue, ValidationResult, ValidationSeverity

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+\.md)[^)]*\)")
_MODELED_FRONTMATTER_KEYS = {"type", "title", "description", "resource", "tags", "timestamp"}
_PENDING_MERGES_DIRNAME = ".okf_meta/pending_merges"
_IDEMPOTENCY_DB_RELPATH = ".okf_meta/idempotency.sqlite3"


class OKFValidationError(Exception):
    """Se levanta cuando validate_concept() falla con severidad ERROR. La
    escritura no ocurrio. str(exc) trae el detalle estructurado completo, sin
    enmascarar nada, para que el agente lo relaye tal cual al usuario."""

    def __init__(self, result: ValidationResult):
        self.result = result
        error_lines = [
            f"[{issue.severity.value}] {issue.rule_name} en '{issue.concept_id}': {issue.message}"
            for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        super().__init__("Validacion fallida, no se escribio nada:\n" + "\n".join(error_lines))


# ---------------------------------------------------------------------------
# Lectura: parseo del bundle
# ---------------------------------------------------------------------------


def _concept_id_from_path(root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(root).with_suffix("")
    return str(PurePosixPath(rel))


def _resolve_link(raw_link: str, current_concept_id: str) -> str:
    raw_link = raw_link.strip()
    if raw_link.startswith("/"):
        target = PurePosixPath(raw_link.lstrip("/"))
    else:
        current_dir = PurePosixPath(current_concept_id).parent
        target = PurePosixPath(os.path.normpath(str(current_dir / raw_link)))
    if target.suffix == ".md":
        target = target.with_suffix("")
    return str(target)


def _coerce_timestamp(raw_value) -> datetime | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, date):
        return datetime(raw_value.year, raw_value.month, raw_value.day)
    if isinstance(raw_value, str):
        return datetime.fromisoformat(raw_value)
    return None


def _concept_from_post(concept_id: str, post: frontmatter.Post) -> OKFConcept:
    metadata = dict(post.metadata)
    tags = metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    links = sorted({_resolve_link(m.group(1), concept_id) for m in _LINK_RE.finditer(post.content)})
    extra = {k: v for k, v in metadata.items() if k not in _MODELED_FRONTMATTER_KEYS}
    return OKFConcept(
        concept_id=concept_id,
        type=metadata.get("type", "") or "",
        title=metadata.get("title"),
        description=metadata.get("description"),
        resource=metadata.get("resource"),
        tags=list(tags),
        timestamp=_coerce_timestamp(metadata.get("timestamp")),
        body=post.content,
        links=links,
        extra_frontmatter=extra,
    )


def parse_bundle(root_path: str) -> dict[str, OKFConcept]:
    """Walks the directory, parses every `.md` file with `python-frontmatter`,
    resolves markdown links into `concept_id` references, returns a dict
    keyed by `concept_id`."""
    root = Path(root_path)
    concepts: dict[str, OKFConcept] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(".md"):
                continue
            file_path = Path(dirpath) / filename
            concept_id = _concept_id_from_path(root, file_path)
            post = frontmatter.load(file_path)
            concepts[concept_id] = _concept_from_post(concept_id, post)
    return concepts


_bundle_cache: dict[str, OKFConcept] | None = None


def _load_bundle(force_reload: bool = False) -> dict[str, OKFConcept]:
    global _bundle_cache
    if _bundle_cache is None or force_reload:
        _bundle_cache = parse_bundle(get_vault_root())
    return _bundle_cache


def invalidate_bundle_cache() -> None:
    global _bundle_cache
    _bundle_cache = None


# ---------------------------------------------------------------------------
# Lectura: tools Agno (read-only, temperature 0.0 en el modelo que las llama)
# ---------------------------------------------------------------------------


@tool
def list_okf_concepts(type: str | None = None, tag: str | None = None) -> list[OKFConcept]:
    """Lista concepts del bundle OKF, opcionalmente filtrando por `type` y/o `tag`.
    Herramienta de solo lectura, nunca modifica el vault."""
    bundle = _load_bundle()
    results = []
    for concept in bundle.values():
        if type is not None and concept.type != type:
            continue
        if tag is not None and tag not in concept.tags:
            continue
        results.append(concept)
    return results


@tool
def query_okf_concept(concept_id: str) -> OKFConcept | None:
    """Busca un concept por su concept_id exacto. Devuelve None si no existe
    — el agente debe interpretar None como 'no esta en el vault', nunca
    inventar el dato."""
    bundle = _load_bundle()
    return bundle.get(concept_id)


@tool
def get_day_itinerary(date: str) -> OKFConcept | None:
    """Busca el concept de type 'day' cuyo timestamp coincide con `date`
    (formato YYYY-MM-DD)."""
    target = datetime.fromisoformat(date).date()
    bundle = _load_bundle()
    for concept in bundle.values():
        if concept.type != "day":
            continue
        if concept.timestamp is not None and concept.timestamp.date() == target:
            return concept
    return None


# ---------------------------------------------------------------------------
# Idempotencia (SQLite) + commit git — infraestructura compartida por los
# dos tools de escritura.
# ---------------------------------------------------------------------------


def _idempotency_db_path(vault_root: str) -> Path:
    return Path(vault_root) / _IDEMPOTENCY_DB_RELPATH


def _idempotency_key(tool_name: str, concept_id: str, body_hash: str) -> str:
    return hashlib.sha256(f"{tool_name}:{concept_id}:{body_hash}".encode("utf-8")).hexdigest()


def _check_and_record_idempotency(vault_root: str, key: str) -> bool:
    """Returns True if this exact write already happened before (caller
    should skip re-writing/re-committing); records the key otherwise."""
    db_path = _idempotency_db_path(vault_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS writes (idempotency_key TEXT PRIMARY KEY, created_at TEXT)"
        )
        existing = conn.execute(
            "SELECT 1 FROM writes WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if existing:
            return True
        conn.execute(
            "INSERT INTO writes (idempotency_key, created_at) VALUES (?, ?)",
            (key, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def _git_commit(vault_root: str, message: str) -> None:
    try:
        repo = Repo(vault_root)
    except (InvalidGitRepositoryError, NoSuchPathError):
        repo = Repo.init(vault_root)
    repo.git.add(A=True)
    if repo.is_dirty() or repo.untracked_files:
        repo.index.commit(message)


# ---------------------------------------------------------------------------
# Escritura: gate de validacion + idempotencia + commit
# ---------------------------------------------------------------------------


def _extra_metadata(frontmatter_dict: dict) -> dict:
    return {k: v for k, v in frontmatter_dict.items() if k not in _MODELED_FRONTMATTER_KEYS | {"concept_id"}}


def _write_concept_file(vault_root: str, concept: OKFConcept) -> None:
    file_path = Path(vault_root) / f"{concept.concept_id}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"type": concept.type}
    if concept.title is not None:
        metadata["title"] = concept.title
    if concept.description is not None:
        metadata["description"] = concept.description
    if concept.resource is not None:
        metadata["resource"] = concept.resource
    if concept.tags:
        metadata["tags"] = concept.tags
    if concept.timestamp is not None:
        metadata["timestamp"] = concept.timestamp.isoformat()
    metadata.update(concept.extra_frontmatter)
    post = frontmatter.Post(concept.body, **metadata)
    with open(file_path, "w", encoding="utf-8") as f:
        frontmatter.dump(post, f)


def _known_tags_from_bundle(bundle: dict[str, OKFConcept]) -> set[str]:
    from tools.tag_taxonomy import load_taxonomy

    taxonomy = load_taxonomy(bundle)
    known = set(taxonomy.entries.keys())
    for entry in taxonomy.entries.values():
        known.update(entry.aliases)
    return known


@tool
def create_concept(type: str, frontmatter: dict, body: str) -> OKFConcept:
    """Crea un nuevo concept OKF (un archivo .md nuevo). `frontmatter` debe
    incluir 'concept_id' (ruta relativa al vault, sin sufijo .md). Corre
    validate_concept() antes de escribir; si falla con ERROR, no se escribe
    nada y se levanta OKFValidationError con el detalle completo."""
    concept_id = frontmatter.get("concept_id")
    if not concept_id:
        raise ValueError("frontmatter debe incluir 'concept_id' (ruta relativa sin sufijo .md).")

    bundle = _load_bundle()
    candidate = OKFConcept(
        concept_id=concept_id,
        type=type,
        title=frontmatter.get("title"),
        description=frontmatter.get("description"),
        resource=frontmatter.get("resource"),
        tags=list(frontmatter.get("tags") or []),
        timestamp=_coerce_timestamp(frontmatter.get("timestamp")),
        body=body,
        links=sorted({_resolve_link(m.group(1), concept_id) for m in _LINK_RE.finditer(body)}),
        extra_frontmatter=_extra_metadata(frontmatter),
    )

    engine = build_default_engine(known_tags=_known_tags_from_bundle(bundle))
    result = engine.validate_concept(candidate, bundle)
    if not result.passed:
        raise OKFValidationError(result)

    vault_root = get_vault_root()
    idem_key = _idempotency_key("create_concept", concept_id, content_hash(candidate))
    already_done = _check_and_record_idempotency(vault_root, idem_key)
    if not already_done:
        _write_concept_file(vault_root, candidate)
        _git_commit(vault_root, f"agent: create_concept on {concept_id}")
        invalidate_bundle_cache()

    return candidate


@tool
def append_to_concept(concept_id: str, content: str) -> OKFConcept:
    """Agrega `content` al final del body de un concept existente. Nunca
    reescribe el body existente — solo concatena. Corre validate_concept()
    antes de escribir; si falla con ERROR, no se escribe nada."""
    bundle = _load_bundle()
    existing = bundle.get(concept_id)
    if existing is None:
        raise OKFValidationError(
            ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        rule_name="concept_exists",
                        severity=ValidationSeverity.ERROR,
                        concept_id=concept_id,
                        message=f"No existe ningun concept con concept_id '{concept_id}' en el bundle.",
                    )
                ],
            )
        )

    updated_body = f"{existing.body}\n\n{content}"
    updated = existing.model_copy(update={"body": updated_body})
    updated.links = sorted({_resolve_link(m.group(1), concept_id) for m in _LINK_RE.finditer(updated_body)})

    bundle_for_validation = dict(bundle)
    bundle_for_validation[concept_id] = updated  # evita que NoDuplicateIdRule dispare sobre si mismo

    engine = build_default_engine(known_tags=_known_tags_from_bundle(bundle))
    result = engine.validate_concept(updated, bundle_for_validation)
    if not result.passed:
        raise OKFValidationError(result)

    vault_root = get_vault_root()
    idem_key = _idempotency_key("append_to_concept", concept_id, content_hash(updated))
    already_done = _check_and_record_idempotency(vault_root, idem_key)
    if not already_done:
        _write_concept_file(vault_root, updated)
        _git_commit(vault_root, f"agent: append_to_concept on {concept_id}")
        invalidate_bundle_cache()

    return updated


# ---------------------------------------------------------------------------
# Tag governance: unico tool de tags del agente interactivo. No toca archivos
# del vault, no hace commit — solo deja un artefacto pendiente para el cron.
# ---------------------------------------------------------------------------


def _pending_merges_dir(vault_root: str) -> Path:
    return Path(vault_root) / _PENDING_MERGES_DIRNAME


def _concept_ids_with_any_tag(bundle: dict[str, OKFConcept], tags: list[str]) -> list[str]:
    tag_set = set(tags)
    return [cid for cid, concept in bundle.items() if tag_set.intersection(concept.tags)]


@tool
def propose_tag_merge(tags: list[str], canonical: str) -> str:
    """Propone fusionar `tags` bajo la forma canonica `canonical`. NO toca
    archivos del vault: escribe un TagMergePlan con status 'pending' en
    .okf_meta/pending_merges/{plan_id}.json y devuelve el plan_id. Aplicar el
    merge es responsabilidad exclusiva del cron de mantenimiento."""
    bundle = _load_bundle()
    plan_id = str(uuid.uuid4())
    candidate = TagMergeCandidate(
        proposed_canonical=canonical,
        tags_to_merge=tags,
        similarity_score=1.0,
        affected_concept_ids=_concept_ids_with_any_tag(bundle, tags),
        rationale="Propuesto directamente por el agente conversacional a pedido del usuario.",
    )
    plan = TagMergePlan(
        plan_id=plan_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=[candidate],
        status="pending",
    )

    vault_root = get_vault_root()
    plans_dir = _pending_merges_dir(vault_root)
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    return plan_id
