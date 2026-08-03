from pydantic import BaseModel


class TagEntry(BaseModel):
    canonical: str
    aliases: list[str] = []
    children: list[str] = []


class TagTaxonomy(BaseModel):
    entries: dict[str, TagEntry]  # keyed by canonical tag


class TagMergeCandidate(BaseModel):
    proposed_canonical: str
    tags_to_merge: list[str]
    similarity_score: float
    affected_concept_ids: list[str]
    rationale: str  # filled by the LLM judge pass, plain language, no invented facts


class TagMergePlan(BaseModel):
    plan_id: str
    created_at: str
    candidates: list[TagMergeCandidate]
    status: str = "pending"  # pending | approved | applied | rejected | failed
    failure_reason: str | None = None
