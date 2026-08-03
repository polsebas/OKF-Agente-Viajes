"""La enforcement del ValidationEngine no depende de consultar skills.

Este test llama create_concept directamente, sin el agente ni el loader de
skills. Si pasa, queda demostrado que el gate de escritura es independiente
de si el agente 'leyo el skill correctamente'.
"""

import pytest

from tools.okf_adapter import OKFValidationError, create_concept


def test_validation_rejects_missing_type_without_skills_loader(temp_vault):
    # No importamos ni instanciamos Skills / LocalSkills a proposito.
    with pytest.raises(OKFValidationError) as exc_info:
        create_concept.entrypoint(
            type="",
            frontmatter={"concept_id": "notas/nota-sin-type-sin-skill"},
            body="contenido de prueba",
        )

    assert "type_required" in str(exc_info.value)
    assert not (temp_vault / "notas" / "nota-sin-type-sin-skill.md").exists()
