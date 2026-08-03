from datetime import datetime

import pytest
from git import Repo

from tools.okf_adapter import (
    OKFValidationError,
    append_to_concept,
    create_concept,
    get_day_itinerary,
    list_okf_concepts,
    parse_bundle,
    propose_tag_merge,
    query_okf_concept,
)


def test_parse_bundle_counts(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))

    assert len(bundle) == 8
    assert bundle["index"].type == "note"
    assert bundle["_meta/tags"].type == "tag-taxonomy"
    assert bundle["vuelos/vuelo-ida"].type == "flight"
    assert bundle["vuelos/vuelo-vuelta"].type == "flight"
    assert bundle["dias/dia-01-tokio"].type == "day"
    assert bundle["dias/dia-02-tokio"].type == "day"
    assert bundle["dias/dia-03-kyoto"].type == "day"
    assert bundle["alojamientos/hotel-shibuya"].type == "lodging"


def test_parse_bundle_resolves_links(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))

    index_links = set(bundle["index"].links)
    assert "vuelos/vuelo-ida" in index_links
    assert "vuelos/vuelo-vuelta" in index_links
    assert "dias/dia-01-tokio" in index_links
    assert "dias/dia-02-tokio" in index_links
    assert "dias/dia-03-kyoto" in index_links
    assert "alojamientos/hotel-shibuya" in index_links

    day1_links = set(bundle["dias/dia-01-tokio"].links)
    assert "alojamientos/hotel-shibuya" in day1_links
    assert "vuelos/vuelo-ida" in day1_links


def test_parse_bundle_no_dangling_links_in_fixture(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))
    for concept in bundle.values():
        for link in concept.links:
            assert link in bundle, f"link colgante: {concept.concept_id} -> {link}"


def test_get_day_itinerary_matches_by_date(temp_vault):
    result = get_day_itinerary.entrypoint(date="2026-08-11")
    assert result is not None
    assert result.concept_id == "dias/dia-02-tokio"


def test_get_day_itinerary_missing_date_returns_explicit_message(temp_vault):
    result = get_day_itinerary.entrypoint(date="2026-01-01")
    assert isinstance(result, str)
    assert "No hay concept type=day" in result


def test_query_okf_concept_missing_returns_explicit_message(temp_vault):
    result = query_okf_concept.entrypoint(concept_id="vuelos/vuelo-fantasma")
    assert isinstance(result, str)
    assert "No existe ningun concept" in result


def test_list_okf_concepts_unknown_type_returns_explicit_message(temp_vault):
    result = list_okf_concepts.entrypoint(type="day-that-does-not-exist", tag=None)
    assert isinstance(result, str)
    assert "No hay concepts que coincidan" in result


def test_list_okf_concepts_filters_by_type_and_tag(temp_vault):
    days = list_okf_concepts.entrypoint(type="day", tag=None)
    assert {c.concept_id for c in days} == {
        "dias/dia-01-tokio",
        "dias/dia-02-tokio",
        "dias/dia-03-kyoto",
    }

    kyoto_days = list_okf_concepts.entrypoint(type="day", tag="kyoto")
    assert {c.concept_id for c in kyoto_days} == {"dias/dia-03-kyoto"}


def test_list_okf_concepts_returns_catalog_preview_not_full_body(temp_vault):
    listed = {c.concept_id: c for c in list_okf_concepts.entrypoint()}
    full = query_okf_concept.entrypoint(concept_id="dias/dia-03-kyoto")
    assert full is not None
    assert "Fushimi Inari" in full.body
    assert len(listed["dias/dia-03-kyoto"].body) < len(full.body)
    assert len(listed["dias/dia-03-kyoto"].body) <= 281


# ---------------------------------------------------------------------------
# Escritura: gate de validacion, idempotencia, commit git.
# ---------------------------------------------------------------------------


def test_create_concept_missing_type_rejected_before_disk(temp_vault, mocker):
    write_spy = mocker.patch("tools.okf_adapter._write_concept_file")
    commit_spy = mocker.patch("tools.okf_adapter._git_commit")

    with pytest.raises(OKFValidationError):
        create_concept.entrypoint(
            type="",
            frontmatter={"concept_id": "notas/nota-sin-type"},
            body="contenido de prueba",
        )

    write_spy.assert_not_called()
    commit_spy.assert_not_called()


def test_create_concept_with_dangling_link_rejected_before_disk(temp_vault, mocker):
    write_spy = mocker.patch("tools.okf_adapter._write_concept_file")

    with pytest.raises(OKFValidationError):
        create_concept.entrypoint(
            type="note",
            frontmatter={"concept_id": "notas/nota-con-link-roto"},
            body="Ver [algo](vuelos/vuelo-fantasma.md)",
        )

    write_spy.assert_not_called()


def test_create_concept_writes_file_and_commits(temp_vault):
    concept = create_concept.entrypoint(
        type="note",
        frontmatter={"concept_id": "notas/nota-nueva", "title": "Nota nueva"},
        body="Contenido de la nota nueva.",
    )

    assert concept.concept_id == "notas/nota-nueva"
    file_path = temp_vault / "notas" / "nota-nueva.md"
    assert file_path.exists()

    repo = Repo(temp_vault)
    last_commit = next(repo.iter_commits(max_count=1))
    assert "create_concept on notas/nota-nueva" in last_commit.message


def test_append_to_concept_never_overwrites_existing_body(temp_vault):
    before = query_okf_concept.entrypoint(concept_id="dias/dia-03-kyoto")
    updated = append_to_concept.entrypoint(
        concept_id="dias/dia-03-kyoto",
        content="El hotel de Kyoto cancelo la reserva.",
    )

    assert updated.body.startswith(before.body)
    assert "cancelo la reserva" in updated.body

    repo = Repo(temp_vault)
    last_commit = next(repo.iter_commits(max_count=1))
    assert "append_to_concept on dias/dia-03-kyoto" in last_commit.message


def test_append_to_concept_missing_concept_raises(temp_vault):
    with pytest.raises(OKFValidationError):
        append_to_concept.entrypoint(concept_id="dias/dia-99-inexistente", content="algo")


def test_write_idempotency_skips_duplicate_write(temp_vault, mocker):
    create_concept.entrypoint(
        type="note",
        frontmatter={"concept_id": "notas/nota-idempotente"},
        body="mismo contenido",
    )

    write_spy = mocker.patch("tools.okf_adapter._write_concept_file")
    commit_spy = mocker.patch("tools.okf_adapter._git_commit")

    create_concept.entrypoint(
        type="note",
        frontmatter={"concept_id": "notas/nota-idempotente"},
        body="mismo contenido",
    )

    write_spy.assert_not_called()
    commit_spy.assert_not_called()


def test_propose_tag_merge_does_not_touch_vault_files(temp_vault):
    before_files = sorted(p.relative_to(temp_vault) for p in temp_vault.rglob("*.md"))

    plan_id = propose_tag_merge.entrypoint(tags=["jp"], canonical="japon")

    after_files = sorted(p.relative_to(temp_vault) for p in temp_vault.rglob("*.md"))
    assert before_files == after_files

    plan_path = temp_vault / ".okf_meta" / "pending_merges" / f"{plan_id}.json"
    assert plan_path.exists()
