"""Capa de memoria del agente de viajes.

Instalación del motor:

- Desarrollo, con el checkout al lado del workspace (``pip install -e ../memgraphrag-core``
  parado en ``OKF-Agente-VIajes``). ``uv`` lo resuelve por
  ``[tool.uv.sources]`` como ``../../memgraphrag-core`` respecto de este paquete.
- Sin checkout: ``pip install "memgraphrag-core @ git+https://github.com/polsebas/memgraphrag-core.git"``.
  El árbol publicado tiene que incluir ``FactCategory``, ``ttl_seconds`` y
  ``expand_fact_evidence``.
"""

from memory.flat_summarizer import FlatSummarizerAdapter
from memory.memgraph_adapters import MemGraphRAGLegacyAdapter, MemGraphRAGV2Adapter
from memory.protocol import (
    FactWrite,
    MemoryAdapter,
    MemoryDrilldownDisabled,
    MemoryMode,
    MemoryView,
    RetrievedFact,
)

__all__ = [
    "FactWrite",
    "FlatSummarizerAdapter",
    "MemGraphRAGLegacyAdapter",
    "MemGraphRAGV2Adapter",
    "MemoryAdapter",
    "MemoryDrilldownDisabled",
    "MemoryMode",
    "MemoryView",
    "RetrievedFact",
    "build_memory_adapter",
]


def build_memory_adapter(mode: MemoryMode | str):
    resolved = MemoryMode(mode)
    if resolved is MemoryMode.FLAT:
        return FlatSummarizerAdapter()
    if resolved is MemoryMode.LEGACY:
        return MemGraphRAGLegacyAdapter()
    if resolved is MemoryMode.V2:
        return MemGraphRAGV2Adapter()
    raise ValueError(f"modo de memoria desconocido: {mode}")
