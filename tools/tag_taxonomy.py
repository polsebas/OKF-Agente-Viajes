"""La taxonomia de tags es un concept OKF mas — vive en `_meta/tags.md` con
`type: tag-taxonomy`, no en una base de datos separada.

Este modulo solo propone: `find_candidate_synonyms` marca pares por similitud
de embeddings, nunca decide un merge por su cuenta.
"""

import re

from schemas.okf_concept import OKFConcept
from schemas.tag_taxonomy import TagEntry, TagMergeCandidate, TagTaxonomy

TAXONOMY_CONCEPT_ID = "_meta/tags"

_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")
_LIST_FIELD_RE = re.compile(r"^(canonical|aliases|children):\s*(.*)$")


def _parse_list_value(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


def _parse_taxonomy_body(body: str) -> dict[str, TagEntry]:
    """Parser simple linea a linea. A proposito no es un DSL general: solo
    entiende el formato de ejemplo del Paso 7 (encabezado ## + canonical/
    aliases/children)."""
    entries: dict[str, TagEntry] = {}
    current_canonical: str | None = None
    current_aliases: list[str] = []
    current_children: list[str] = []

    def flush():
        if current_canonical:
            entries[current_canonical] = TagEntry(
                canonical=current_canonical,
                aliases=current_aliases,
                children=current_children,
            )

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header_match = _HEADER_RE.match(line)
        if header_match:
            flush()
            current_canonical = header_match.group(1).strip()
            current_aliases = []
            current_children = []
            continue
        field_match = _LIST_FIELD_RE.match(line)
        if field_match and current_canonical is not None:
            field, value = field_match.groups()
            if field == "canonical":
                current_canonical = value.strip() or current_canonical
            elif field == "aliases":
                current_aliases = _parse_list_value(value)
            elif field == "children":
                current_children = _parse_list_value(value)

    flush()
    return entries


def load_taxonomy(bundle: dict[str, OKFConcept]) -> TagTaxonomy:
    taxonomy_concept = bundle.get(TAXONOMY_CONCEPT_ID)
    if taxonomy_concept is None:
        return TagTaxonomy(entries={})
    return TagTaxonomy(entries=_parse_taxonomy_body(taxonomy_concept.body))


def resolve_tag(tag: str, taxonomy: TagTaxonomy) -> str:
    """Returns canonical form if the tag is an alias, otherwise returns the
    tag unchanged."""
    if tag in taxonomy.entries:
        return tag
    for canonical, entry in taxonomy.entries.items():
        if tag in entry.aliases:
            return canonical
    return tag


_embedding_model = None


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _embedding_model


_EMBEDDING_CONTEXT_TEMPLATE = "viaje a {tag}"


def _embed_tags(model, tags: list[str]):
    """Los tags de viaje suelen ser abreviaturas cortas (paises, ciudades:
    'jp', 'jpn') donde la palabra sola no le da al modelo de sentence
    embeddings contexto semantico suficiente para separarlas bien de otras
    abreviaturas cortas no relacionadas. Anclarlas en una frase de dominio
    ('viaje a {tag}') antes de embeber mejora consistentemente la separacion
    para este vocabulario, medido empiricamente contra el par jp/japon."""
    templated = [_EMBEDDING_CONTEXT_TEMPLATE.format(tag=tag) for tag in tags]
    return model.encode(templated, normalize_embeddings=True)


def find_candidate_synonyms(
    new_tags: list[str],
    taxonomy: TagTaxonomy,
    threshold: float = 0.82,
) -> list[TagMergeCandidate]:
    """Embeds new_tags and every canonical tag, flags cosine similarity above
    `threshold` as a candidate. Does not decide anything — just proposes.

    `affected_concept_ids` and `rationale` quedan vacios aca a proposito: no
    hay bundle disponible en esta firma para calcular a que concepts afecta,
    y la racionalizacion en lenguaje llano la llena el pase de juez LLM del
    cron (core/maintenance_cron.py), nunca este modulo.
    """
    canonicals = list(taxonomy.entries.keys())
    if not new_tags or not canonicals:
        return []

    import numpy as np

    model = _get_embedding_model()
    new_embeddings = _embed_tags(model, new_tags)
    canonical_embeddings = _embed_tags(model, canonicals)

    candidates: list[TagMergeCandidate] = []
    for tag, tag_embedding in zip(new_tags, new_embeddings):
        similarities = canonical_embeddings @ tag_embedding
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        if best_score >= threshold:
            candidates.append(
                TagMergeCandidate(
                    proposed_canonical=canonicals[best_idx],
                    tags_to_merge=[tag],
                    similarity_score=best_score,
                    affected_concept_ids=[],
                    rationale="",
                )
            )
    return candidates
