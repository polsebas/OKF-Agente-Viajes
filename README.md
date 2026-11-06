# OKF Travel Itinerary Agent

A personal AI agent that reads and maintains a travel itinerary stored in an Obsidian vault — treated as an **OKF bundle** (Open Knowledge Format).

Ask questions about your trip, append notes to a day, or create new itinerary entries. The agent answers from what is actually in the vault. It does not invent flights, prices, or hotel details that are not written down.

---

## Why this exists

Itineraries live in notes: days, flights, hotels, links between them. A chat model without structure will guess. This project keeps the **notes as the source of truth**, and uses an agent only where judgment is needed — understanding your request, choosing what to look up, proposing a change.

Everything that must stay consistent (links, types, tags, writing files) is handled by deterministic code, not by the model improvising.

---

## What is OKF?

**OKF (Open Knowledge Format)** is a simple way to treat a folder of Markdown files as a knowledge bundle:

- Each note is a **concept** (a day, a flight, a hotel, an index, a tag taxonomy).
- Concepts have **YAML frontmatter** (type, title, tags, links) and a Markdown body.
- Files can **link** to each other, like a small graph of your trip.
- The whole vault is one **bundle** the agent can list, query, and carefully update.

In practice, your Obsidian vault *is* the OKF bundle. No separate database is required for day-to-day use.

A sample Japan 2026 itinerary lives under `fixtures/sample_vault/` so you can try the agent immediately.

---

## What is the agent?

The **Travel Itinerary Agent** is built with [Agno](https://docs.agno.com/). It is not a free-form chatbot with full write access to your disk.

Its role:

| It does | It does not |
| --- | --- |
| Answer questions from concepts it retrieves | Invent missing itinerary facts |
| Append text to an existing concept when you ask | Silently overwrite existing notes |
| Create a new concept when the type is clear | Merge or delete tags on its own |
| Propose a tag merge for review | Bypass validation when a write is invalid |
| Say “I don’t know” when the vault has no answer | Keep retrying a failed write blindly |

The agent’s **constitution** (system instructions) encodes those rules. Tools do the reading and writing; a validation layer checks integrity before anything hits the vault; changes that pass are committed with Git.

### Selective context

Each turn the agent sees a light summary of the vault (counts by type, the index tree, canonical tags, today’s date) — not every note at once. It then pulls the specific concepts it needs with tools. That keeps answers grounded and context size from growing with every new day of your trip.

### Maintenance (outside the chat)

Scheduled jobs can scan the bundle for broken links or inconsistent concepts, and suggest tag cleanup (for example merging near-duplicate tags). Applying tag rewrites is intentional and optional — the chat agent only proposes.

---

## Design in one line

**The model thinks. Code enforces. The vault stores the truth.**

---

## Quick start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or a virtualenv
- A model provider: **Ollama** (local), OpenAI, or Anthropic

### Setup

```bash
cd okf_travel_agent
cp .env.example .env
# edit .env — set vault path and model provider
uv sync
```

Point `OKF_VAULT_ROOT` at your Obsidian vault (or leave the sample vault for a first run).

Example with local Ollama:

```env
OKF_VAULT_ROOT=fixtures/sample_vault
OKF_PRIMARY_MODEL_PROVIDER=ollama
OKF_PRIMARY_MODEL_ID=qwen3.5:9b
OLLAMA_HOST=http://localhost:11434
```

### Run

Interactive chat:

```bash
.venv/bin/python main.py
```

One-shot question:

```bash
.venv/bin/python main.py "Which days are in the itinerary?"
```

Exit the REPL with `salir`, `exit`, or `quit`.

### Tests

```bash
.venv/bin/pytest
```

---

## What you can ask

Examples that fit the sample vault:

- “What days does the itinerary have?”
- “Where do I stay in Tokyo?”
- “What is the outbound flight?”
- “Add a note to day 3: the hotel cancelled.”

Ambiguous requests (“fix my tags”) get a clarifying question — the agent will not guess a risky write.

If a fact is missing (for example a hotel price that was never recorded), it says so instead of estimating.

---

## Project layout (high level)

```
okf_travel_agent/
├── main.py                 # CLI entrypoint
├── agents/                 # Agent definition and constitution wiring
├── prompts/                # Agent constitution (identity and limits)
├── tools/                  # Vault read/write tools (OKF adapter)
├── core/                   # Config, validation, maintenance jobs
├── schemas/                # Shared data shapes
├── fixtures/sample_vault/  # Example OKF itinerary
└── tests/                  # Unit tests and evaluation datasets
```

---

## Principles worth remembering

1. **Vault first** — if it is not in the bundle, the agent does not claim it.
2. **Write carefully** — validation before disk; Git history for every successful change.
3. **Least privilege** — the agent proposes tag governance; scheduled code may apply it.
4. **Honest failures** — validation errors are shown to you, not papered over.

---

## Arquitectura de Memoria y Trazabilidad en Producción (`memgraphrag-core`)

Este repositorio es el caso de uso de dominio: un agente de itinerario sobre un vault Obsidian tratado como bundle OKF. La memoria de producción —evidencia cruda, hechos aceptados y trazabilidad de lo que se rechazó— es el contrato de [memgraphrag-core](https://github.com/polsebas/memgraphrag-core) (`polsebas/memgraphrag-core`).

El motor guarda una memoria global de tres capas y recupera con Personalized PageRank guiado por esa memoria, más un rerank híbrido entre similitud vectorial y puntaje estructural. Los agentes de indexación (`A_ext`, `A_det`, `A_res`) también están escritos con [Agno](https://docs.agno.com/), igual que este itinerario. Acá el modelo interpreta el pedido y elige qué nota leer. En el banco de reservas, el bucle PRAO escribe en el mismo motor y decide el turno siguiente solo con lo que el adaptador inyecta.

| Capa del motor | Qué persiste | En este dominio |
| --- | --- | --- |
| `M_pas` | Pasajes: texto fuente, para grounding y trazabilidad | El cuerpo de cada concepto OKF y el turno crudo (por ejemplo la edad y la dieta dichas al pasar). El hecho comprimido no reemplaza ese texto. |
| `M_ont` | Esquemas `(tipo, relación, tipo)`, estables solo si la frecuencia alcanza `tau` | Tipos de concepto, links entre notas y taxonomía de tags. Un merge se propone; el chat no lo aplica. |
| `M_fac` | Hechos instanciados, ligados al esquema estable y a los pasajes que los evidencian | Un dato que pasó validación, un rechazo del viajero, un `HTTP 409` o una tarifa con `ttl_seconds`. |

La topología que materializa el motor es `Schema --INSTANTIATES--> Fact --EVIDENCE_IN--> Passage`. Una respuesta factual del itinerario sale de `query_okf_concept`, `get_day_itinerary` o `list_okf_concepts`. En el cierre de una reserva, el dato exacto del pasajero sale de `expand_fact_evidence` sobre `M_pas`.

Tres adaptadores comparten esa interfaz para la comparación. `FlatSummarizerAdapter` comprime el log y busca en el resumen. `MemGraphRAGLegacyAdapter` usa el grafo sin categoría de proceso y sin vencimiento. `MemGraphRAGV2Adapter` activa `FactCategory` (`HARD_CONSTRAINT`, `REJECTED_OPTION`, `TOOL_FAILURE`), la poda por `ttl_seconds` dentro del PPR y el drill-down al pasaje. La corrida está en `python -m evaluation.run_effectiveness_suite` y la tabla queda en [evaluation/RESULTS.md](evaluation/RESULTS.md).

### MemoryTax: el techo lo pone quien escribe la memoria

[MemoryTax](https://arxiv.org/abs/2610.29823) (*The Bitter Lesson of Agent Memory*, arXiv:2610.29823) compara memorias diseñadas (Mem0, Zep) con el contexto completo y con agentes que buscan el historial crudo. El hallazgo que fija este dominio: la memoria tiene un techo puesto por el modelo que la escribe. Un lector más fuerte no recupera el tramo que el escritor no guardó. En el grafo Zep escrito por GPT-4o-mini, GPT-4o-mini, GPT-6 Luna y Claude Opus 5.5 quedan en 43 %, 43 % y 45 %. En el grafo escrito por Claude Opus 5.5, los mismos lectores llegan a 66 %, 71 % y 87 %.

Por eso `M_fac` y `M_ont` no sustituyen a `M_pas`. El contexto selectivo de cada turno (conteos por tipo, índice, tags canónicos, fecha de hoy) es un puntero al vault. El precio de un hotel que nadie escribió sigue ausente. En el banco, la edad de la nena y la dieta celíaca viven en el pasaje del turno 2; el hecho comprimido solo dice «restricción alimentaria», y V2 la recupera leyendo `M_pas`.

### MemDev-Bench: conservar el proceso y juzgar si sigue vigente

[MemDev-Bench](https://arxiv.org/abs/2610.27524) (*Does Memory Help Code Agents?*, arXiv:2610.27524) mide sistemas de memoria sobre historiales reales de repositorio: 555 tareas base y 4.869 tareas históricas anotadas por relevancia. La memoria ayuda a localizar y editar, y también hace fallar tareas que el agente resolvía sin ella, porque reutiliza una guía vieja sin revisar si todavía aplica. Entregar la trayectoria cruda, en el orden en que ocurrió, acorta el proceso: guarda intentos fallidos, revisiones y resultados que las memorias comprimidas suelen descartar.

En este agente esos eventos ya son parte del contrato, y el motor los distingue en producción:

- Un write inválido o un `HTTP 409` de Hotel Norte es un rechazo. La herramienta falla, el archivo no cambia y Git no commitea. V2 lo guarda como `TOOL_FAILURE` para no reintentar el mismo cupo en el cierre.
- «No inventar vuelos, precios ni direcciones» y «no aplicar un merge de tags desde el chat» son restricciones negativas. `propose_tag_merge` propone. El job de mantenimiento aplica, y solo si hay un plan aprobado. El rechazo de una escala en Miami queda como `REJECTED_OPTION`.
- `append_to_concept` agrega texto al cuerpo existente. La nota anterior queda en el archivo y en la historia de Git, con el `concept_id` en el mensaje del commit.
- La vigencia es explícita. Una tarifa aérea nace con `ttl_seconds`. Cuando el reloj pasa ese plazo, el PPR la saca del contexto y el agente vuelve a cotizar en el escritorio determinista, en vez de repetir el importe vencido.

---

## License / status

Personal tooling prototype — shape your vault, adjust `.env`, and treat the sample itinerary as a safe sandbox before pointing the agent at a live Obsidian vault.
