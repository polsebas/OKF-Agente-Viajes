from core.validation_engine import (
    LinksResolveRule,
    NoDuplicateIdRule,
    TagInTaxonomyRule,
    TypeRequiredRule,
    ValidationEngine,
    build_default_engine,
)
from schemas.okf_concept import OKFConcept
from schemas.validation import ValidationSeverity


def _concept(**overrides) -> OKFConcept:
    defaults = dict(
        concept_id="dias/dia-01-tokio",
        type="day",
        title="Dia 1",
        body="cuerpo de prueba",
        tags=[],
        links=[],
    )
    defaults.update(overrides)
    return OKFConcept(**defaults)


def test_type_required_rule_errors_on_missing_type():
    concept = _concept(type="")
    issues = TypeRequiredRule().check(concept, {})

    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.ERROR
    assert issues[0].rule_name == "type_required"


def test_type_required_rule_passes_with_type():
    concept = _concept(type="day")
    assert TypeRequiredRule().check(concept, {}) == []


def test_links_resolve_rule_errors_on_dangling_link():
    concept = _concept(links=["vuelos/vuelo-fantasma"])
    issues = LinksResolveRule().check(concept, {concept.concept_id: concept})

    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.ERROR
    assert issues[0].rule_name == "links_resolve"


def test_links_resolve_rule_passes_when_link_exists():
    target = _concept(concept_id="alojamientos/hotel-shibuya", type="lodging")
    concept = _concept(links=["alojamientos/hotel-shibuya"])
    all_concepts = {concept.concept_id: concept, target.concept_id: target}

    assert LinksResolveRule().check(concept, all_concepts) == []


def test_no_duplicate_id_rule_errors_on_conflicting_content():
    existing = _concept(body="contenido original")
    conflicting = _concept(body="contenido completamente distinto")
    all_concepts = {existing.concept_id: existing}

    issues = NoDuplicateIdRule().check(conflicting, all_concepts)

    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.ERROR
    assert issues[0].rule_name == "no_duplicate_id"


def test_no_duplicate_id_rule_passes_for_identical_content_idempotent_write():
    existing = _concept(body="mismo contenido")
    same = _concept(body="mismo contenido")
    all_concepts = {existing.concept_id: existing}

    assert NoDuplicateIdRule().check(same, all_concepts) == []


def test_tag_in_taxonomy_rule_warns_and_marks_pending():
    concept = _concept(tags=["jp"])
    rule = TagInTaxonomyRule(known_tags={"japon", "tokio"})

    issues = rule.check(concept, {})

    assert len(issues) == 1
    assert issues[0].severity == ValidationSeverity.WARNING
    assert issues[0].rule_name == "tag_in_taxonomy"
    assert concept.extra_frontmatter.get("tag_pending") is True


def test_tag_in_taxonomy_rule_does_not_block_write():
    concept = _concept(tags=["jp"], type="day")
    engine = ValidationEngine(rules=[TypeRequiredRule(), TagInTaxonomyRule(known_tags={"japon"})])

    result = engine.validate_concept(concept, {})

    assert result.passed is True
    assert any(issue.severity == ValidationSeverity.WARNING for issue in result.issues)


def test_validate_concept_gate_blocks_on_error():
    concept = _concept(type="", links=["algo/inexistente"])
    engine = build_default_engine(known_tags=set())

    result = engine.validate_concept(concept, {})

    assert result.passed is False
    error_rules = {issue.rule_name for issue in result.issues if issue.severity == ValidationSeverity.ERROR}
    assert "type_required" in error_rules
    assert "links_resolve" in error_rules


def test_validate_bundle_scans_every_concept():
    broken = _concept(concept_id="dias/dia-roto", type="", links=["nada/inexistente"])
    healthy = _concept(concept_id="dias/dia-sano", type="day")
    engine = build_default_engine(known_tags=set())

    result = engine.validate_bundle({broken.concept_id: broken, healthy.concept_id: healthy})

    assert result.passed is False
    broken_issues = [issue for issue in result.issues if issue.concept_id == "dias/dia-roto"]
    assert any(issue.severity == ValidationSeverity.ERROR for issue in broken_issues)
