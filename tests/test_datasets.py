"""Chequeos estructurales de los datasets de evaluacion contra el fixture.

No llaman a ningun LLM — solo verifican que golden/adversarial_dataset.json
sean consistentes con lo que realmente hay (o no hay) en fixtures/sample_vault,
para que las expectativas de las evals no queden desincronizadas del fixture."""

import json
from pathlib import Path

from tools.okf_adapter import parse_bundle

DATASETS_DIR = Path(__file__).resolve().parent


def _load(name: str) -> list[dict]:
    return json.loads((DATASETS_DIR / name).read_text(encoding="utf-8"))


def test_golden_dataset_concept_ids_exist_in_fixture(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))
    golden = _load("golden_dataset.json")

    assert len(golden) == 10

    for case in golden:
        for concept_id in case["expected_concept_ids"]:
            assert concept_id in bundle, f"{case['id']}: concept_id inexistente {concept_id}"


def test_adversarial_dataset_absent_facts_are_actually_absent(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))
    adversarial = _load("adversarial_dataset.json")

    for case in adversarial:
        assert case["fact_present_in_vault"] is False
        queried = case.get("queried_concept_id")
        expected_exists = case.get("queried_concept_exists")
        if queried is not None and expected_exists is not None:
            assert (queried in bundle) is expected_exists, (
                f"{case['id']}: se esperaba queried_concept_exists={expected_exists} para {queried}"
            )

    hotel = bundle["alojamientos/hotel-shibuya"]
    assert "cost" not in hotel.extra_frontmatter
    assert hotel.resource is not None and "$" not in hotel.body and "USD" not in hotel.body
