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

## License / status

Personal tooling prototype — shape your vault, adjust `.env`, and treat the sample itinerary as a safe sandbox before pointing the agent at a live Obsidian vault.
