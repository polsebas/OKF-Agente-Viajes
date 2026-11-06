"""Tool Agno de drill-down a M_pas. Solo se registra con el adaptador v2."""

from __future__ import annotations

from agno.tools import tool


def build_expand_fact_evidence_tool(memory_adapter):
    @tool
    def expand_fact_evidence(fact_id: str) -> str:
        """Lee el pasaje crudo e inmutable en M_pas del hecho ``fact_id``.

        Usala antes del checkout cuando haga falta un dato exacto del pasajero
        (edad, restricción alimentaria) que el hecho comprimido de M_fac no
        conserva. Devuelve el texto fuente, sin resumirlo.
        """
        return memory_adapter.expand_fact_evidence(fact_id)

    return expand_fact_evidence
