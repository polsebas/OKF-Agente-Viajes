"""E2E: tres adaptadores sobre la misma conversación de 12 turnos."""

from __future__ import annotations

import asyncio

from memgraphrag_core.domain.models import FactCategory

from agents.prao import TravelPraoLoop
from agents.travel_agent import (
    ValidationFailureTracker,
    create_travel_agent,
    make_validation_stuck_state_hook,
)
from evaluation.run_effectiveness_suite import (
    render_results,
    run_suite,
    write_results,
)
from evaluation.scenario import ASIDE_PASSAGE, SCENARIO
from memory import MemoryDrilldownDisabled, MemoryMode, build_memory_adapter
from memory.flat_summarizer import lossy_summarize
from schemas.validation import ValidationIssue, ValidationResult, ValidationSeverity
from tools.okf_adapter import OKFValidationError


def _by_name(runs):
    return {run.adapter_name: run for run in runs}


def _trace(run, kind: str):
    return next(trace for trace in run.traces if trace.kind == kind)


def _fact(adapter, relation: str):
    return next(fact for fact in adapter.memory.facts.values() if fact.relation == relation)


def test_scenario_has_twelve_turns_and_the_clock_expires_the_fare():
    assert len(SCENARIO) == 12
    assert [turn.index for turn in SCENARIO] == list(range(1, 13))
    assert SCENARIO[2].kind == "rejection"
    assert SCENARIO[4].kind == "book"
    assert SCENARIO[8].kind == "quote"
    assert SCENARIO[10].kind == "ask_fare"
    assert SCENARIO[11].kind == "close"
    assert SCENARIO[10].as_of > SCENARIO[8].as_of
    elapsed = SCENARIO[10].as_of - SCENARIO[8].as_of
    assert elapsed.total_seconds() > 3600


def test_lossy_summary_drops_rejection_failure_and_aside():
    summary = lossy_summarize(
        [
            "El presupuesto máximo es 3500 dólares: es un tope duro.",
            ASIDE_PASSAGE,
            "Rechazo cualquier escala en Miami. No tienen visa de tránsito.",
            "HTTP 409 Conflict al reservar Hotel Norte: sin cupo",
            "Cotización vigente del vuelo EZE-MAD: 890 USD",
        ]
    )
    assert "3500" in summary
    assert "890" in summary
    assert "Miami" not in summary
    assert "409" not in summary
    assert "7" not in summary
    assert "celíaca" not in summary


def test_v2_preserves_process_ttl_and_raw_passage_against_the_baselines(tmp_path):
    runs = run_suite()
    report = render_results(runs)
    written = write_results(runs, tmp_path / "RESULTS.md")
    assert "MemGraphRAGV2Adapter" in written.read_text(encoding="utf-8")

    by_name = _by_name(runs)
    flat = by_name["FlatSummarizerAdapter"]
    legacy = by_name["MemGraphRAGLegacyAdapter"]
    v2 = by_name["MemGraphRAGV2Adapter"]
    debug = report + "\n" + _debug(runs)

    assert v2.metrics.constraint_compliance == 100, debug
    assert legacy.metrics.constraint_compliance == 100, debug
    assert flat.metrics.constraint_compliance == 0, debug
    assert v2.metrics.tool_failure_repeat == 0, debug
    assert legacy.metrics.tool_failure_repeat == 0, debug
    assert flat.metrics.tool_failure_repeat == 100, debug
    assert v2.metrics.stale_hallucination == 0, debug
    assert flat.metrics.stale_hallucination == 100, debug
    assert legacy.metrics.stale_hallucination == 100, debug
    assert v2.metrics.raw_detail_recall == 100, debug
    assert flat.metrics.raw_detail_recall == 0, debug
    assert legacy.metrics.raw_detail_recall == 0, debug
    assert v2.metrics.avg_prompt_tokens > 0

    v2_close = _trace(v2, "close")
    flat_close = _trace(flat, "close")
    assert v2_close.route == "EZE-GRU-MAD"
    assert "MIA" in flat_close.route
    assert v2_close.hotel == "Hotel Prado"
    assert flat_close.hotel == "Hotel Norte"
    assert v2_close.drilldown_text == ASIDE_PASSAGE
    assert "7" in v2_close.drilldown_text and "celíaca" in v2_close.drilldown_text

    v2_fare = _trace(v2, "ask_fare")
    legacy_fare = _trace(legacy, "ask_fare")
    assert v2_fare.refreshed_quote is True
    assert v2_fare.fare_usd == 1120
    assert legacy_fare.stale_hallucination is True
    assert legacy_fare.fare_usd == 890

    rejected = _fact(v2.adapter, "REJECTED_LAYOVER")
    failed = _fact(v2.adapter, "BOOKING_FAILED")
    quote = _fact(v2.adapter, "QUOTED_PRICE")
    aside = _fact(v2.adapter, "HAS_ASIDE")
    assert rejected.category is FactCategory.REJECTED_OPTION
    assert failed.category is FactCategory.TOOL_FAILURE
    assert _fact(v2.adapter, "HARD_CAP").category is FactCategory.HARD_CONSTRAINT
    assert quote.ttl_seconds == 3600
    assert quote.is_expired(SCENARIO[10].as_of)
    assert "890" not in _trace(v2, "ask_fare").prompt
    assert v2.adapter.expand_fact_evidence(aside.fact_id or aside.fact_key) == ASIDE_PASSAGE

    legacy_quote = _fact(legacy.adapter, "QUOTED_PRICE")
    legacy_rejected = _fact(legacy.adapter, "REJECTED_LAYOVER")
    assert legacy_quote.ttl_seconds is None
    assert legacy_quote.is_expired(SCENARIO[10].as_of) is False
    assert legacy_rejected.category is FactCategory.DECLARATIVE
    assert "7" not in legacy_rejected.metadata.get("prompt_text", "")
    assert "7 años" not in _fact(legacy.adapter, "HAS_ASIDE").metadata["prompt_text"]
    try:
        legacy.adapter.expand_fact_evidence(aside.fact_id or "missing")
    except MemoryDrilldownDisabled:
        pass
    else:
        raise AssertionError("el adaptador legacy no debe abrir M_pas")


def test_validation_failure_is_recorded_as_tool_failure():
    adapter = build_memory_adapter(MemoryMode.V2)
    tracker = ValidationFailureTracker()

    def _record(concept_id: str, detail: str) -> None:
        adapter.record_tool_failure(
            passage=detail,
            resource=concept_id,
            detail=detail,
            as_of=SCENARIO[0].as_of,
        )

    hook = make_validation_stuck_state_hook(tracker, on_tool_failure=_record)

    def always_fails(**kwargs):
        del kwargs
        raise OKFValidationError(
            ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        rule_name="type_required",
                        severity=ValidationSeverity.ERROR,
                        concept_id="hoteles/hotel-norte",
                        message="HTTP 409 Conflict",
                    )
                ],
            )
        )

    try:
        hook("append_to_concept", always_fails, {"concept_id": "hoteles/hotel-norte"})
    except OKFValidationError:
        pass
    stored = _fact(adapter, "BOOKING_FAILED")
    assert stored.category is FactCategory.TOOL_FAILURE
    assert "409" in stored.metadata["prompt_text"]


def test_v2_agent_exposes_drilldown_tool_and_the_default_registry_does_not():
    plain = create_travel_agent()
    plain_names = {tool.name for tool in plain.tools if hasattr(tool, "name")}
    assert "expand_fact_evidence" not in plain_names
    assert "apply_tag_rewrite" not in plain_names

    v2 = create_travel_agent(memory_adapter=build_memory_adapter(MemoryMode.V2))
    v2_names = {tool.name for tool in v2.tools if hasattr(tool, "name")}
    assert "expand_fact_evidence" in v2_names
    assert plain_names <= v2_names


def test_v2_recovers_the_409_and_does_not_ask_norte_again():
    from datetime import timedelta

    from agents.booking import HOTEL_NORTE, HOTEL_PRADO, BookingDesk
    from evaluation.scenario import ScenarioTurn

    adapter = build_memory_adapter(MemoryMode.V2)
    desk = BookingDesk()
    loop = TravelPraoLoop(adapter, desk)
    traces = asyncio.run(loop.run(SCENARIO))
    booked = next(trace for trace in traces if trace.kind == "book")
    assert "409" in booked.observation
    assert HOTEL_PRADO in booked.observation
    assert desk.attempts.count(HOTEL_NORTE) == 1

    again = asyncio.run(
        loop.step(
            ScenarioTurn(
                index=13,
                kind="book",
                user="Reservá el Hotel Norte otra vez.",
                as_of=SCENARIO[-1].as_of + timedelta(minutes=5),
            )
        )
    )
    assert again.hotel == HOTEL_PRADO
    assert "No lo reintento" in again.observation
    assert desk.attempts.count(HOTEL_NORTE) == 1


def test_prao_loop_is_the_runtime_under_test():
    adapter = build_memory_adapter(MemoryMode.V2)
    traces = asyncio.run(TravelPraoLoop(adapter).run(SCENARIO[:1]))
    assert traces[0].kind == "constraint"
    assert _fact(adapter, "HARD_CAP").category is FactCategory.HARD_CONSTRAINT


def _debug(runs) -> str:
    chunks = []
    for run in runs:
        chunks.append(f"## {run.adapter_name} {run.metrics}")
        for trace in run.traces:
            if trace.kind in {"book", "ask_fare", "close", "rejection", "aside"}:
                chunks.append(
                    f"t{trace.index} {trace.kind} route={trace.route!r} hotel={trace.hotel!r} "
                    f"fare={trace.fare_usd} stale={trace.stale_hallucination} "
                    f"refresh={trace.refreshed_quote} details={trace.raw_details_found} "
                    f"cats={trace.retrieved_categories} rels={trace.retrieved_relations}\n"
                    f"prompt={trace.prompt!r}"
                )
    return "\n".join(chunks)
