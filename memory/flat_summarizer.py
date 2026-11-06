"""Baseline: compresión periódica con pérdida y búsqueda vectorial plana.

El compresor es un sustituto determinista del resumen por LLM. Hace lo que
MemDev-Bench y MemoryTax le atribuyen a la memoria comprimida: se queda con
el plan afirmativo (destino, hoteles, tarifa) y tira el proceso (rechazos,
HTTP 409) y el detalle incidental (edad, dieta) que no entra en el resumen.
No hay ``M_pas`` consultable ni poda por TTL: la tarifa vieja sigue en el texto.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

from memgraphrag_core.infrastructure.in_memory_vector_store import InMemoryVectorStore

from memory.protocol import FactWrite, MemoryDrilldownDisabled, MemoryView, RetrievedFact
from memory.tokens import estimate_tokens

_LOSSY = re.compile(
    r"rechaz|no quiero|visa de tr[aá]nsito|"
    r"\b409\b|conflict|sin cupo|"
    r"de paso|cel[ií]ac|gluten|\baños\b",
    re.IGNORECASE,
)


def lossy_summarize(lines: list[str]) -> str:
    """Resume el log. Cada línea que matchea el filtro de pérdida desaparece."""
    kept: list[str] = []
    for line in lines:
        text = " ".join(line.split())
        if not text or _LOSSY.search(text):
            continue
        kept.append(text)
    if not kept:
        return ""
    return "Resumen del itinerario: " + " ".join(kept)


class FlatSummarizerAdapter:
    name = "FlatSummarizerAdapter"
    supports_drilldown = False

    def __init__(self, *, compress_every: int = 2, summarizer=lossy_summarize) -> None:
        if compress_every < 1:
            raise ValueError("compress_every debe ser >= 1")
        self.compress_every = compress_every
        self._summarize = summarizer
        self._lines: list[str] = []
        self._notes_since_compress = 0
        self._vectors = InMemoryVectorStore()
        self._summary_index = 0

    async def awrite(self, fact: FactWrite) -> None:
        self._lines.append(fact.passage.strip())
        self._notes_since_compress += 1
        if self._notes_since_compress >= self.compress_every:
            await self._compress()
            self._notes_since_compress = 0

    async def _compress(self) -> None:
        summary = self._summarize(self._lines)
        if not summary:
            return
        self._summary_index += 1
        summary_id = f"sum-{self._summary_index:03d}"
        await self._vectors.add_texts([summary], [summary_id], namespace="flat")

    async def aretrieve(self, query: str, *, as_of: datetime) -> MemoryView:
        del as_of
        provisional = self._summarize(self._lines)
        hits = await self._vectors.search_similarity(query, k=2, namespace="flat")
        chunks: list[str] = []
        if provisional:
            chunks.append(provisional)
        for hit in hits:
            if hit.text not in chunks:
                chunks.append(hit.text)
        prompt = "\n".join(chunks)
        facts = [
            RetrievedFact(
                fact_id=f"flat-{index}",
                category="declarative",
                relation="SUMMARY",
                tail="",
                text=chunk,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]
        return MemoryView(
            prompt=prompt,
            facts=facts,
            tokens=estimate_tokens(prompt),
            supports_drilldown=False,
            adapter_name=self.name,
        )

    def expand_fact_evidence(self, fact_id: str) -> str:
        raise MemoryDrilldownDisabled(
            "FlatSummarizerAdapter no guarda M_pas: el resumen ya descartó el pasaje "
            f"crudo (fact_id={fact_id})."
        )

    def record_tool_failure(
        self,
        *,
        passage: str,
        resource: str,
        detail: str,
        as_of: datetime,
    ) -> None:
        line = passage.strip() or f"HTTP 409 Conflict al reservar {resource}: {detail}"
        asyncio.run(
            self.awrite(
                FactWrite(
                    passage=line,
                    head=resource,
                    head_type="Hotel",
                    relation="BOOKING_FAILED",
                    tail=detail,
                    tail_type="Error",
                    schema_text="fallo de reserva",
                    prompt_text=line,
                    as_of=as_of,
                    category="tool_failure",
                )
            )
        )
