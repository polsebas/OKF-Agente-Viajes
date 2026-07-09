"""Capa de integridad determinista del bundle OKF.

Ninguna funcion de este modulo llama a un LLM. Es el unico lugar con
autoridad para decidir si una escritura puede tocar disco (validate_concept,
gate de escritura individual) o para producir el reporte de un scan completo
(validate_bundle, usado por el cron de mantenimiento).
"""

import hashlib
from abc import ABC, abstractmethod

from schemas.okf_concept import OKFConcept
from schemas.validation import ValidationIssue, ValidationResult, ValidationSeverity


def content_hash(concept: OKFConcept) -> str:
    """Hash deterministico del contenido relevante de un concept, usado por
    NoDuplicateIdRule para distinguir una reescritura idempotente de un choque
    real de concept_id."""
    payload = f"{concept.type}|{concept.title or ''}|{concept.body}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ValidationRule(ABC):
    name: str

    @abstractmethod
    def check(self, concept: OKFConcept, all_concepts: dict[str, OKFConcept]) -> list[ValidationIssue]:
        ...


class TypeRequiredRule(ValidationRule):
    """ERROR if concept.type is empty — the only field OKF v0.1 actually mandates."""

    name = "type_required"

    def check(self, concept: OKFConcept, all_concepts: dict[str, OKFConcept]) -> list[ValidationIssue]:
        if concept.type and concept.type.strip():
            return []
        return [
            ValidationIssue(
                rule_name=self.name,
                severity=ValidationSeverity.ERROR,
                concept_id=concept.concept_id,
                message="El concept no tiene 'type', el unico campo obligatorio de OKF v0.1.",
            )
        ]


class LinksResolveRule(ValidationRule):
    """ERROR if any concept_id in concept.links is not a key in all_concepts."""

    name = "links_resolve"

    def check(self, concept: OKFConcept, all_concepts: dict[str, OKFConcept]) -> list[ValidationIssue]:
        issues = []
        for link in concept.links:
            if link not in all_concepts:
                issues.append(
                    ValidationIssue(
                        rule_name=self.name,
                        severity=ValidationSeverity.ERROR,
                        concept_id=concept.concept_id,
                        message=f"El link '{link}' no resuelve a ningun concept_id del bundle.",
                    )
                )
        return issues


class NoDuplicateIdRule(ValidationRule):
    """ERROR if concept_id already exists with different content hash at write time."""

    name = "no_duplicate_id"

    def check(self, concept: OKFConcept, all_concepts: dict[str, OKFConcept]) -> list[ValidationIssue]:
        existing = all_concepts.get(concept.concept_id)
        if existing is None or existing is concept:
            return []
        if content_hash(existing) == content_hash(concept):
            return []
        return [
            ValidationIssue(
                rule_name=self.name,
                severity=ValidationSeverity.ERROR,
                concept_id=concept.concept_id,
                message=(
                    f"Ya existe un concept con concept_id '{concept.concept_id}' "
                    "y contenido distinto. Usa append_to_concept o un concept_id nuevo."
                ),
            )
        ]


class TagInTaxonomyRule(ValidationRule):
    """WARNING (not ERROR) if a tag is not in the canonical taxonomy — mark
    tag_pending=true in extra_frontmatter instead of blocking the write."""

    name = "tag_in_taxonomy"

    def __init__(self, known_tags: set[str] | None = None):
        self._known_tags = known_tags or set()

    def check(self, concept: OKFConcept, all_concepts: dict[str, OKFConcept]) -> list[ValidationIssue]:
        if not self._known_tags:
            return []
        unknown = [tag for tag in concept.tags if tag not in self._known_tags]
        if not unknown:
            return []
        concept.extra_frontmatter["tag_pending"] = True
        return [
            ValidationIssue(
                rule_name=self.name,
                severity=ValidationSeverity.WARNING,
                concept_id=concept.concept_id,
                message=f"Tags fuera de la taxonomia canonica: {', '.join(unknown)}.",
            )
        ]


class ValidationEngine:
    def __init__(self, rules: list[ValidationRule]):
        self.rules = rules

    def validate_concept(self, concept: OKFConcept, all_concepts: dict) -> ValidationResult:
        issues: list[ValidationIssue] = []
        for rule in self.rules:
            issues.extend(rule.check(concept, all_concepts))
        passed = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(passed=passed, issues=issues)

    def validate_bundle(self, all_concepts: dict) -> ValidationResult:
        """Scan completo, usado por el cron de integridad. Recorre todos los
        concepts del bundle y agrega todos los issues, sin detenerse en el
        primer ERROR (a diferencia de validate_concept, que gatea una sola
        escritura)."""
        issues: list[ValidationIssue] = []
        for concept in all_concepts.values():
            for rule in self.rules:
                issues.extend(rule.check(concept, all_concepts))
        passed = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(passed=passed, issues=issues)


def build_default_engine(known_tags: set[str] | None = None) -> ValidationEngine:
    """Registra las cuatro reglas por default."""
    return ValidationEngine(
        rules=[
            TypeRequiredRule(),
            LinksResolveRule(),
            NoDuplicateIdRule(),
            TagInTaxonomyRule(known_tags=known_tags),
        ]
    )
