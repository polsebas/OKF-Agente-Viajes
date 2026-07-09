from pydantic import BaseModel, Field
from datetime import datetime


class OKFConcept(BaseModel):
    """A single parsed OKF concept — one markdown file."""
    concept_id: str = Field(description="File path relative to bundle root, no .md suffix")
    type: str = Field(description="Required OKF field. E.g. 'day', 'flight', 'lodging', 'note'")
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    body: str = Field(description="Markdown content after frontmatter")
    links: list[str] = Field(default_factory=list, description="Concept IDs this file links to")
    extra_frontmatter: dict = Field(default_factory=dict, description="Any producer-defined keys not modeled above")
