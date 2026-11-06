"""Adaptadores MemGraphRAG legacy y v2 sobre el mismo writer.

Legacy persiste todo como ``DECLARATIVE`` y sin ``ttl_seconds``. El pasaje
crudo entra a ``M_pas``, pero el modo no expone ``expand_fact_evidence`` y el
prompt solo recibe el hecho comprimido.

V2 activa ``FactCategory``, el boost de restricciones dentro del PPR (lo hace
el retriever al ver ``HARD_CONSTRAINT`` / ``REJECTED_OPTION``), la poda por
``ttl_seconds`` y el drill-down al pasaje inmutable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from memgraphrag_core.domain.models import GlobalMemoryState
from memgraphrag_core.infrastructure.in_memory_vector_store import InMemoryVectorStore
from memgraphrag_core.infrastructure.networkx_graph_store import NetworkXGraphStore
from memgraphrag_core.retrieval.retriever import MemoryGuidedRetriever

from memory.graph_memory import write_fact
from memory.protocol import (
    FactWrite,
    MemoryDrilldownDisabled,
    MemoryView,
    RetrievedFact,
)
from memory.tokens import estimate_tokens


class _MemGraphAdapter:
    supports_drilldown = False
    typed = False
    honor_ttl = False
    name = "MemGraphRAG"

    def __init__(self, *, top_k_facts: int = 12, top_k_passages: int = 12) -> None:
        # El cupo de pasajes tiene que alcanzar al de hechos: el retriever
        # descarta un hecho de M_fac si su evidencia en M_pas no entra.
        self.memory = GlobalMemoryState(tau=1)
        self.graph = NetworkXGraphStore()
        self.vectors = InMemoryVectorStore()
        self.retriever = MemoryGuidedRetriever(
            self.memory,
            self.graph,
            self.vectors,
            top_k_facts=top_k_facts,
            top_k_passages=top_k_passages,
        )

    async def awrite(self, fact: FactWrite) -> None:
        await write_fact(
            self.memory,
            self.graph,
            self.vectors,
            fact,
            typed=self.typed,
            honor_ttl=self.honor_ttl,
        )

    async def aretrieve(self, query: str, *, as_of: datetime) -> MemoryView:
        result = await self.retriever.retrieve(query, as_of=as_of)
        facts: list[RetrievedFact] = []
        lines: list[str] = []
        for fact in result.facts:
            text = str(fact.metadata.get("prompt_text") or "").strip()
            if not text:
                text = f"{fact.head_entity} {fact.relation} {fact.tail_entity}"
            fact_id = fact.fact_id or fact.fact_key
            if self.typed:
                line = f"[{fact.category.value}] {text} (id={fact_id})"
            else:
                line = text
            facts.append(
                RetrievedFact(
                    fact_id=fact_id,
                    category=fact.category.value,
                    relation=fact.relation,
                    tail=fact.tail_entity,
                    text=text,
                )
            )
            lines.append(line)
        prompt = "\n".join(lines)
        return MemoryView(
            prompt=prompt,
            facts=facts,
            tokens=estimate_tokens(prompt),
            supports_drilldown=self.supports_drilldown,
            adapter_name=self.name,
        )

    def expand_fact_evidence(self, fact_id: str) -> str:
        if not self.supports_drilldown:
            raise MemoryDrilldownDisabled(
                f"{self.name} no expone expand_fact_evidence. "
                "El pasaje sigue en M_pas, pero este modo no hace drill-down."
            )
        return self.memory.expand_fact_evidence(fact_id)

    def record_tool_failure(
        self,
        *,
        passage: str,
        resource: str,
        detail: str,
        as_of: datetime,
    ) -> None:
        text = passage.strip() or f"{resource} HTTP 409 Conflict: {detail}"
        asyncio.run(
            self.awrite(
                FactWrite(
                    passage=text,
                    head=resource,
                    head_type="Hotel",
                    relation="BOOKING_FAILED",
                    tail=resource,
                    tail_type="Error",
                    schema_text=f"fallo de herramienta hotel reserva {resource}",
                    prompt_text=f"{resource} BOOKING_FAILED HTTP 409 Conflict {detail}",
                    as_of=as_of,
                    category="tool_failure",
                )
            )
        )


class MemGraphRAGLegacyAdapter(_MemGraphAdapter):
    name = "MemGraphRAGLegacyAdapter"
    supports_drilldown = False
    typed = False
    honor_ttl = False


class MemGraphRAGV2Adapter(_MemGraphAdapter):
    name = "MemGraphRAGV2Adapter"
    supports_drilldown = True
    typed = True
    honor_ttl = True
