"""Escritura de un hecho en las tres capas de memgraphrag-core.

``tau`` queda en 1: en este dominio una frase explícita del viajero ya es un
esquema estable. El umbral de corpus (2) tiraría cada restricción dicha una
sola vez.
"""

from __future__ import annotations

from memgraphrag_core.domain.models import (
    LAYER_M_FAC,
    LAYER_M_ONT,
    LAYER_M_PAS,
    EDGE_EVIDENCE_IN,
    EDGE_INSTANTIATES,
    Fact,
    FactCategory,
    GlobalMemoryState,
    Passage,
    coerce_fact_category,
)
from memgraphrag_core.infrastructure.in_memory_vector_store import InMemoryVectorStore
from memgraphrag_core.infrastructure.networkx_graph_store import NetworkXGraphStore
from memgraphrag_core.interfaces.graph_store import GraphEdge, GraphNode

from memory.protocol import FactWrite


async def write_fact(
    memory: GlobalMemoryState,
    graph: NetworkXGraphStore,
    vectors: InMemoryVectorStore,
    fact_write: FactWrite,
    *,
    typed: bool,
    honor_ttl: bool,
) -> Fact:
    category = coerce_fact_category(fact_write.category) if typed else FactCategory.DECLARATIVE
    ttl = fact_write.ttl_seconds if honor_ttl else None
    passage_id = _passage_id(memory, fact_write)
    passage = Passage(id=passage_id, text=fact_write.passage, created_at=fact_write.as_of)
    memory.add_passage(passage)
    memory.register_schema_candidate(fact_write.head_type, fact_write.relation, fact_write.tail_type)

    fact = Fact(
        head_entity=fact_write.head,
        head_type=fact_write.head_type,
        relation=fact_write.relation,
        tail_entity=fact_write.tail,
        tail_type=fact_write.tail_type,
        passage_ids=[passage_id],
        source_passage_id=passage_id,
        category=category,
        ttl_seconds=ttl,
        created_at=fact_write.as_of,
        metadata={"prompt_text": fact_write.prompt_text},
    )
    stored = memory.add_fact(fact)
    if stored is None:
        raise RuntimeError(
            f"M_fac rechazó {fact.fact_key}: el esquema no alcanza tau={memory.tau}"
        )
    if "prompt_text" not in stored.metadata:
        stored.metadata["prompt_text"] = fact_write.prompt_text

    await vectors.add_texts([fact_write.passage], [passage_id], namespace=LAYER_M_PAS)
    await vectors.add_texts(
        [fact_write.schema_text], [stored.schema_key], namespace=LAYER_M_ONT
    )
    await vectors.add_texts(
        [fact_write.prompt_text], [stored.fact_key], namespace=LAYER_M_FAC
    )
    await _link(graph, stored)
    return stored


def _passage_id(memory: GlobalMemoryState, fact_write: FactWrite) -> str:
    slug = fact_write.relation.strip().lower().replace(" ", "-")
    base = f"pas-{slug}-{len(memory.passages) + 1:03d}"
    candidate = base
    n = 2
    while candidate in memory.passages:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


async def _link(graph: NetworkXGraphStore, fact: Fact) -> None:
    passage_id = fact.source_passage_id or fact.passage_ids[0]
    await graph.add_node(GraphNode(id=f"ont_{fact.schema_key}", label="Schema"))
    await graph.add_node(
        GraphNode(
            id=f"fact_{fact.fact_key}",
            label="Fact",
            properties=fact.graph_properties(),
        )
    )
    await graph.add_node(GraphNode(id=f"pas_{passage_id}", label="Passage"))
    await graph.add_edge(
        GraphEdge(
            source_id=f"ont_{fact.schema_key}",
            target_id=f"fact_{fact.fact_key}",
            relation=EDGE_INSTANTIATES,
        )
    )
    await graph.add_edge(
        GraphEdge(
            source_id=f"fact_{fact.fact_key}",
            target_id=f"pas_{passage_id}",
            relation=EDGE_EVIDENCE_IN,
        )
    )
