from schemas.tag_taxonomy import TagEntry, TagTaxonomy
from tools.okf_adapter import parse_bundle
from tools.tag_taxonomy import find_candidate_synonyms, load_taxonomy, resolve_tag


def _taxonomy_with_known_jp_alias() -> TagTaxonomy:
    """Taxonomia donde 'jp' YA es un alias conocido de 'japon' — para probar
    que resolve_tag hace la resolucion determinista de alias correctamente,
    independiente de cualquier calculo de embeddings."""
    return TagTaxonomy(
        entries={
            "japon": TagEntry(canonical="japon", aliases=["jp", "japón", "asia-japon"], children=["tokio", "kyoto"]),
            "vuelos": TagEntry(canonical="vuelos", aliases=["vuelo", "flight", "aereo"], children=[]),
        }
    )


def test_resolve_tag_returns_canonical_for_known_alias():
    taxonomy = _taxonomy_with_known_jp_alias()
    assert resolve_tag("jp", taxonomy) == "japon"


def test_resolve_tag_returns_input_unchanged_for_canonical_or_unknown():
    taxonomy = _taxonomy_with_known_jp_alias()
    assert resolve_tag("japon", taxonomy) == "japon"
    assert resolve_tag("tag-totalmente-desconocido", taxonomy) == "tag-totalmente-desconocido"


def test_load_taxonomy_parses_meta_tags_concept(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))
    taxonomy = load_taxonomy(bundle)

    assert "japon" in taxonomy.entries
    assert "vuelos" in taxonomy.entries
    assert set(taxonomy.entries["japon"].aliases) == {"japón", "asia-japon"}
    assert set(taxonomy.entries["japon"].children) == {"tokio", "kyoto", "osaka"}


def test_find_candidate_synonyms_flags_jp_japon_pair_above_default_threshold(sample_vault_path):
    """Caso adversarial del Paso 12: en el fixture, 'jp' (usado en
    dias/dia-02-tokio.md) todavia NO es un alias conocido de 'japon' en la
    taxonomia — es exactamente lo que este pipeline de embeddings debe
    descubrir y proponer."""
    bundle = parse_bundle(str(sample_vault_path))
    taxonomy = load_taxonomy(bundle)

    assert resolve_tag("jp", taxonomy) == "jp"  # todavia no resuelve via alias

    candidates = find_candidate_synonyms(["jp"], taxonomy, threshold=0.82)

    assert len(candidates) == 1
    assert candidates[0].proposed_canonical == "japon"
    assert candidates[0].tags_to_merge == ["jp"]
    assert candidates[0].similarity_score >= 0.82


def test_find_candidate_synonyms_ignores_unrelated_tags():
    taxonomy = _taxonomy_with_known_jp_alias()
    candidates = find_candidate_synonyms(["hotel"], taxonomy, threshold=0.82)
    assert candidates == []
