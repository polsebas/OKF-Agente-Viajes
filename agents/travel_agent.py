"""Definicion del agente Agno. El LLM aca solo hace trabajo cognitivo: leer,
interpretar, proponer. `apply_tag_rewrite` NO aparece en esta lista de tools
a proposito — vive solo en core/maintenance_cron.py, invocado por el
scheduler, nunca por el agente. Confirmado explicitamente: greppeando este
archivo por 'apply_tag_rewrite' no debe haber ningun resultado.
"""

from collections import Counter
from datetime import date
from pathlib import Path

from agno.agent import Agent

from core.config import get_fallback_models, get_resilient_model, get_vault_root
from schemas.okf_concept import OKFConcept
from tools.okf_adapter import (
    OKFValidationError,
    append_to_concept,
    create_concept,
    get_day_itinerary,
    list_okf_concepts,
    parse_bundle,
    propose_tag_merge,
    query_okf_concept,
)
from tools.tag_taxonomy import load_taxonomy

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "travel_itinerary_agent_v1.md"

with open(_PROMPT_PATH, encoding="utf-8") as f:
    instructions = f.read()

WRITE_TOOL_NAMES = {"create_concept", "append_to_concept"}


# ---------------------------------------------------------------------------
# Context engineering: Recuperacion Selectiva (Arq. 1.3), no dump completo
# del bundle. El costo en tokens es ~constante respecto del tamaño del vault.
# ---------------------------------------------------------------------------


def build_world_state(bundle: dict[str, OKFConcept]) -> str:
    """Snapshot liviano para el placeholder [WORLD_STATE] de la constitucion.
    Nunca incluye el body completo de un concept que no sea index.md. El
    agente decide, con las tools, que concept completo necesita traer."""
    counts = Counter(concept.type for concept in bundle.values())
    index_concept = bundle.get("index")
    index_summary = index_concept.body.strip() if index_concept else "(sin index.md en el bundle)"
    taxonomy = load_taxonomy(bundle)
    canonical_tags = sorted(taxonomy.entries.keys())

    return "\n".join(
        [
            f"Fecha actual: {date.today().isoformat()}",
            f"Conceptos por type: {dict(sorted(counts.items()))}",
            f"Tags canonicos en la taxonomia: {canonical_tags}",
            "Arbol de index.md:",
            index_summary,
        ]
    )


# ---------------------------------------------------------------------------
# Tool registry: Stuck State / System Prompt Interrupt (Arq. 2.3). No viene
# gratis con tool_call_limit — hay que inyectarlo explicitamente.
# ---------------------------------------------------------------------------


class StuckStateInterrupt(Exception):
    """Se levanta en lugar de OKFValidationError cuando un mismo concept_id
    acumula dos fallos de validacion consecutivos. El mensaje instruye al
    agente a reportar y dejar de reintentar."""


class ValidationFailureTracker:
    THRESHOLD = 2

    def __init__(self):
        self._consecutive_failures: dict[str, int] = {}

    def record_success(self, concept_id: str) -> None:
        self._consecutive_failures.pop(concept_id, None)

    def record_failure(self, concept_id: str) -> int:
        count = self._consecutive_failures.get(concept_id, 0) + 1
        self._consecutive_failures[concept_id] = count
        return count

    def should_interrupt(self, concept_id: str) -> bool:
        return self._consecutive_failures.get(concept_id, 0) >= self.THRESHOLD

    @staticmethod
    def interrupt_message(concept_id: str) -> str:
        return (
            f"Has fallado la validacion dos veces en el concept '{concept_id}'. "
            "Reporta el error exacto al usuario. No reintentes esta escritura "
            "de nuevo en este turno."
        )

    def reset(self) -> None:
        self._consecutive_failures.clear()


def _extract_concept_id(arguments: dict) -> str | None:
    if arguments.get("concept_id"):
        return arguments["concept_id"]
    frontmatter = arguments.get("frontmatter") or {}
    return frontmatter.get("concept_id")


def make_validation_stuck_state_hook(tracker: ValidationFailureTracker):
    """Tool hook (Ent. 2.4 / Arq. 5.2): envuelve create_concept y
    append_to_concept. Deja pasar el primer fallo tal cual (Error as
    Observation, Arq. 5.4). Al segundo fallo consecutivo sobre el mismo
    concept_id, reemplaza la excepcion por un System Prompt Interrupt
    explicito."""

    def hook(function_name: str, function_call, arguments: dict):
        if function_name not in WRITE_TOOL_NAMES:
            return function_call(**arguments)

        concept_id = _extract_concept_id(arguments)
        try:
            result = function_call(**arguments)
        except OKFValidationError as exc:
            if concept_id:
                failures = tracker.record_failure(concept_id)
                if failures >= ValidationFailureTracker.THRESHOLD:
                    raise StuckStateInterrupt(
                        f"{exc}\n\n{tracker.interrupt_message(concept_id)}"
                    ) from exc
            raise
        else:
            if concept_id:
                tracker.record_success(concept_id)
            return result

    return hook


# ---------------------------------------------------------------------------
# Model abstraction (Ent. 3.3, 3.5): get_resilient_model() con fallback,
# temperature=0.0 siempre (Regla de Oro del JSON, hay tool-calling en juego).
# ---------------------------------------------------------------------------


def create_travel_agent(tracker: ValidationFailureTracker | None = None) -> Agent:
    tracker = tracker or ValidationFailureTracker()
    return Agent(
        model=get_resilient_model(),
        fallback_models=get_fallback_models(),
        tools=[
            list_okf_concepts,
            query_okf_concept,
            get_day_itinerary,
            create_concept,
            append_to_concept,
            propose_tag_merge,
        ],
        instructions=instructions,
        tool_call_limit=6,  # levemente por encima del usual 5 — los flujos de escritura necesitan un paso mas
        tool_hooks=[make_validation_stuck_state_hook(tracker)],
        add_dependencies_to_context=True,
        markdown=True,
    )


def ask(agent: Agent, message: str, dependencies: dict | None = None):
    """Corre el agente inyectando el world_state liviano (Recuperacion
    Selectiva) como dependency de este run, en vez de re-parsear todo el
    bundle en las instrucciones estaticas del agente."""
    bundle = parse_bundle(get_vault_root())
    run_dependencies = {"world_state": build_world_state(bundle)}
    if dependencies:
        run_dependencies.update(dependencies)
    return agent.run(message, dependencies=run_dependencies, add_dependencies_to_context=True)


travel_agent = create_travel_agent()
