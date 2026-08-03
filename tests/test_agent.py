"""Tests de los cuatro componentes del kernel: constitution, context
engineering, tool registry, model abstraction."""

from pathlib import Path

import pytest

from agents.travel_agent import (
    ValidationFailureTracker,
    build_world_state,
    create_travel_agent,
    make_validation_stuck_state_hook,
)
from core.config import get_fallback_models, get_judge_model, get_resilient_model
from tools.okf_adapter import OKFValidationError, parse_bundle

_CONSTITUTION_PATH = Path(__file__).resolve().parent.parent / "prompts" / "travel_itinerary_agent_v1.md"

_EXPECTED_CONSTITUTION = """## IDENTITY AND BASE ROLE

You are TravelItineraryAgent, the interpreter and maintainer of a personal travel
itinerary stored as an OKF bundle in an Obsidian vault.
Your exclusive objective is to answer questions about the itinerary accurately, and to
append or create itinerary concepts when the user explicitly asks you to.
You are precise and literal. You do not invent itinerary details that are not in the vault.

## ABSOLUTE LIMITS (what you must NEVER do)

- NEVER invent, infer, or estimate itinerary facts (flight times, prices, addresses).
  If it is not in a concept you retrieved, you do not know it. Say so.
- NEVER rewrite, merge, or delete tags directly. If you believe tags should be merged,
  call propose_tag_merge and stop. You do not have a tool to apply a merge, and you must
  not attempt to work around that by editing files manually.
- NEVER create a concept without a `type` field. If the user's request doesn't map to a
  clear concept type, ask which type before writing.
- NEVER overwrite existing body content. Use append_to_concept, never a full rewrite.
- NEVER use skill tools (get_skill_script, get_skill_reference, get_skill_instructions)
  to read the itinerary. Vault files are NOT skills. To read Xian call
  query_okf_concept with concept_id "05 - Xian" (same pattern for other cities).
- NEVER invent or paste fake tool calls as markdown. Either call a real OKF tool
  or answer from tool results you already have.

## IMMUTABLE AXIOMS (truths you cannot question)

- The vault is the single source of truth. If a concept is not in the bundle, it does not
  exist for itinerary purposes, regardless of what you might otherwise assume.
- A validation error on a write means the write did not happen. There is no partial state.
- Tag governance is a deterministic, scheduled process. You propose; you never execute.
- Itinerary facts come only from list_okf_concepts, query_okf_concept, or
  get_day_itinerary. Skills (when enabled) are advisory for writes only.

## OUTPUT CONTRACT

For read-only questions, answer ONLY what was asked — natural language, no JSON.
Factual asks (dates, places, hotels, "qué día…", "cuándo…") get ONE short sentence
with the fact. Example: user asks when arrival in Beijing is → reply like
"La llegada a Beijing es el lunes 7 de septiembre de 2026." and STOP.

On read-only questions you MUST NOT:
- review, critique, or "improve" the concept
- offer tags, frontmatter, skills, checklists, or next steps
- use headings, bullet lists, or long markdown structure
- ask "what would you like to work on" unless the user asked for help writing

For city/itinerary questions (excursions, hotels, plans): call query_okf_concept on
the matching concept_id from world_state (e.g. "05 - Xian"), then answer briefly from
that body. Do not narrate the tool call.

Use list_okf_concepts only as a catalog (short previews). Then call query_okf_concept
for the one concept you need — never dump the whole vault into the conversation.
get_day_itinerary looks up type=day by timestamp (YYYY-MM-DD). Always answer with a
short final reply — never leave the user without a text reply.
For any tool call that writes to the vault, you MUST first state in plain language what
you are about to write and to which concept_id, before calling the tool.
If a write tool returns a validation error, relay the exact error to the user. Do not
retry silently more than once.

## OPERATIONAL CONTEXT (injected dynamically at runtime)

[WORLD_STATE: parsed OKF bundle summary, tag taxonomy snapshot, current date]
"""


# ---------------------------------------------------------------------------
# 1. Constitution (kernel)
# ---------------------------------------------------------------------------


def test_constitution_matches_spec_verbatim():
    actual = _CONSTITUTION_PATH.read_text(encoding="utf-8")
    assert actual == _EXPECTED_CONSTITUTION


# ---------------------------------------------------------------------------
# 2. Context engineering: Recuperacion Selectiva
# ---------------------------------------------------------------------------


def test_world_state_excludes_full_concept_bodies(sample_vault_path):
    bundle = parse_bundle(str(sample_vault_path))
    world_state = build_world_state(bundle)

    assert "Fushimi Inari" not in world_state  # body de dias/dia-03-kyoto
    assert "shinkansen" not in world_state
    assert "Conceptos por type" in world_state
    assert "japon" in world_state  # tag canonico, si, cuerpo completo, no


def test_world_state_size_does_not_scale_linearly_with_vault_size(sample_vault_path):
    small_bundle = parse_bundle(str(sample_vault_path))
    small_state = build_world_state(small_bundle)

    template = small_bundle["dias/dia-01-tokio"]
    big_bundle = dict(small_bundle)
    for i in range(200):
        concept_id = f"dias/dia-sintetico-{i:03d}"
        big_bundle[concept_id] = template.model_copy(update={"concept_id": concept_id})
    big_state = build_world_state(big_bundle)

    assert len(big_bundle) > len(small_bundle) * 20
    assert len(big_state) < len(small_state) * 3


# ---------------------------------------------------------------------------
# 3. Tool registry: Mínimo Privilegio Cognitivo + Stuck State Interrupt
# ---------------------------------------------------------------------------



def test_skill_tools_absent_by_default():
    agent = create_travel_agent()
    tool_names = {t.name for t in agent.tools if hasattr(t, "name")}
    assert not any(name.startswith("get_skill_") for name in tool_names)
    # Sin loader de Skills, Agno no debe exponer get_skill_*.
    assert getattr(agent, "skills", None) is None


def test_apply_tag_rewrite_absent_from_travel_agent_tools():
    agent = create_travel_agent()
    tool_names = {t.name for t in agent.tools if hasattr(t, "name")}

    assert "apply_tag_rewrite" not in tool_names
    assert tool_names == {
        "list_okf_concepts",
        "query_okf_concept",
        "get_day_itinerary",
        "create_concept",
        "append_to_concept",
        "propose_tag_merge",
    }


def test_validation_failure_tracker_interrupts_after_two_consecutive_failures():
    tracker = ValidationFailureTracker()

    assert tracker.record_failure("dias/dia-03-kyoto") == 1
    assert tracker.should_interrupt("dias/dia-03-kyoto") is False

    assert tracker.record_failure("dias/dia-03-kyoto") == 2
    assert tracker.should_interrupt("dias/dia-03-kyoto") is True


def test_validation_failure_tracker_resets_on_success():
    tracker = ValidationFailureTracker()
    tracker.record_failure("dias/dia-03-kyoto")
    tracker.record_success("dias/dia-03-kyoto")

    assert tracker.should_interrupt("dias/dia-03-kyoto") is False


def test_stuck_state_hook_interrupts_on_second_consecutive_failure():
    from agents.travel_agent import StuckStateInterrupt

    tracker = ValidationFailureTracker()
    hook = make_validation_stuck_state_hook(tracker)

    def always_fails(**kwargs):
        raise OKFValidationError(result=_fake_validation_result())

    arguments = {"concept_id": "dias/dia-03-kyoto", "content": "algo"}

    with pytest.raises(OKFValidationError):
        hook("append_to_concept", always_fails, arguments)

    with pytest.raises(StuckStateInterrupt):
        hook("append_to_concept", always_fails, arguments)


def test_stuck_state_hook_ignores_read_only_tools():
    tracker = ValidationFailureTracker()
    hook = make_validation_stuck_state_hook(tracker)

    def passthrough(**kwargs):
        return "ok"

    assert hook("query_okf_concept", passthrough, {"concept_id": "x"}) == "ok"


def _fake_validation_result():
    from schemas.validation import ValidationIssue, ValidationResult, ValidationSeverity

    return ValidationResult(
        passed=False,
        issues=[
            ValidationIssue(
                rule_name="type_required",
                severity=ValidationSeverity.ERROR,
                concept_id="dias/dia-03-kyoto",
                message="falta type",
            )
        ],
    )


# ---------------------------------------------------------------------------
# 4. Model abstraction: Regla de Oro del JSON (temperature=0.0)
# ---------------------------------------------------------------------------


def test_resilient_and_judge_models_use_zero_temperature():
    assert get_resilient_model().temperature == 0.0
    assert get_judge_model().temperature == 0.0


def test_fallback_models_default_empty_without_env_config(monkeypatch):
    monkeypatch.delenv("OKF_FALLBACK_MODELS", raising=False)
    assert get_fallback_models() == []
