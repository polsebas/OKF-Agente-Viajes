"""Interfaz de memoria del agente de viajes.

Tres modos comparten este contrato para que el bucle PRAO y la suite E2E
comparen retención, no una política distinta por adaptador:

- ``FlatSummarizerAdapter``: resumen periódico con pérdida + búsqueda vectorial plana.
- ``MemGraphRAGLegacyAdapter``: MemGraphRAG sin ``FactCategory`` de proceso ni TTL.
- ``MemGraphRAGV2Adapter``: categorías de traza, boost en PPR, ``ttl_seconds`` y
  drill-down ``expand_fact_evidence`` hacia ``M_pas``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol


class MemoryMode(str, Enum):
    FLAT = "flat_summarizer"
    LEGACY = "memgraphrag_legacy"
    V2 = "memgraphrag_v2"


@dataclass(frozen=True)
class RetrievedFact:
    """Hecho que el adaptador inyecta en el turno. Es lo único que el PRAO puede usar."""

    fact_id: str
    category: str
    relation: str
    tail: str
    text: str


@dataclass
class MemoryView:
    """Bloque de memoria que entra al prompt de un turno."""

    prompt: str
    facts: list[RetrievedFact] = field(default_factory=list)
    tokens: int = 0
    supports_drilldown: bool = False
    adapter_name: str = ""


@dataclass(frozen=True)
class FactWrite:
    """Observación ya clasificada, lista para persistir."""

    passage: str
    head: str
    head_type: str
    relation: str
    tail: str
    tail_type: str
    schema_text: str
    prompt_text: str
    as_of: datetime
    category: str = "declarative"
    ttl_seconds: Optional[int] = None


class MemoryDrilldownDisabled(RuntimeError):
    """El modo no ofrece lectura directa de ``M_pas``."""


class MemoryAdapter(Protocol):
    name: str
    supports_drilldown: bool

    async def aretrieve(self, query: str, *, as_of: datetime) -> MemoryView:
        """Arma el bloque inyectado en el prompt para esta consulta."""

    async def awrite(self, fact: FactWrite) -> None:
        """Persiste un hecho y su pasaje fuente."""

    def expand_fact_evidence(self, fact_id: str) -> str:
        """Devuelve el texto crudo e inmutable de ``M_pas`` para ``fact_id``."""

    def record_tool_failure(
        self,
        *,
        passage: str,
        resource: str,
        detail: str,
        as_of: datetime,
    ) -> None:
        """Atajo sincrónico para un fallo de herramienta observado fuera del loop async."""
