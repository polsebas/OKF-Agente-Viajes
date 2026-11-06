"""Runner de la suite de efectividad y export de ``evaluation/RESULTS.md``.

Ejecutar desde la raíz del paquete:

    python -m evaluation.run_effectiveness_suite
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from agents.prao import TravelPraoLoop, TurnTrace
from evaluation.scenario import SCENARIO
from memory import MemoryMode, build_memory_adapter

RESULTS_PATH = Path(__file__).resolve().parent / "RESULTS.md"

_MODES = (MemoryMode.FLAT, MemoryMode.LEGACY, MemoryMode.V2)


@dataclass
class Metrics:
    constraint_compliance: float
    tool_failure_repeat: float
    stale_hallucination: float
    raw_detail_recall: float
    avg_prompt_tokens: float


@dataclass
class AdapterRun:
    adapter_name: str
    mode: MemoryMode
    metrics: Metrics
    traces: list[TurnTrace]
    adapter: object


def metrics_from_traces(traces: list[TurnTrace]) -> Metrics:
    route_turns = [trace for trace in traces if trace.decided_route]
    if not route_turns:
        raise RuntimeError("el escenario no decidió ninguna ruta")
    violations = sum(1 for trace in route_turns if trace.violated_constraint)
    compliance = 100.0 * (1.0 - violations / len(route_turns))

    attempts = [trace for trace in traces if trace.attempted_blocked_resource]
    if not attempts:
        raise RuntimeError("el escenario no reintentó un recurso con fallo previo")
    repeats = sum(1 for trace in attempts if trace.repeated_failure)
    repeat_rate = 100.0 * repeats / len(attempts)

    fare_checks = [trace for trace in traces if trace.checked_stale_fare]
    if not fare_checks:
        raise RuntimeError("el escenario no consultó una tarifa vencida")
    stale_hits = sum(1 for trace in fare_checks if trace.stale_hallucination)
    stale_rate = 100.0 * stale_hits / len(fare_checks)

    asked = sum(trace.raw_details_asked for trace in traces)
    found = sum(trace.raw_details_found for trace in traces)
    if asked == 0:
        raise RuntimeError("el escenario no pidió detalle crudo")
    recall = 100.0 * found / asked

    avg_tokens = sum(trace.prompt_tokens for trace in traces) / len(traces)
    return Metrics(
        constraint_compliance=compliance,
        tool_failure_repeat=repeat_rate,
        stale_hallucination=stale_rate,
        raw_detail_recall=recall,
        avg_prompt_tokens=avg_tokens,
    )


async def _run_mode(mode: MemoryMode) -> AdapterRun:
    adapter = build_memory_adapter(mode)
    traces = await TravelPraoLoop(adapter).run(SCENARIO)
    return AdapterRun(
        adapter_name=adapter.name,
        mode=mode,
        metrics=metrics_from_traces(traces),
        traces=traces,
        adapter=adapter,
    )


def run_suite() -> list[AdapterRun]:
    return asyncio.run(_run_all())


async def _run_all() -> list[AdapterRun]:
    runs: list[AdapterRun] = []
    for mode in _MODES:
        runs.append(await _run_mode(mode))
    return runs


def render_results(runs: list[AdapterRun]) -> str:
    header = (
        "# Resultados — efectividad de memoria en OKF-Agente-Viajes\n\n"
        "Conversación E2E de 12 turnos (reservas e itinerario), sin LLM externo. "
        "El reloj simulado vence la tarifa antes del turno 11. "
        "Papers de referencia: MemoryTax (arXiv:2610.29823), "
        "MemDev-Bench (arXiv:2610.27524) y Remembering Is Not Enough "
        "(arXiv:2610.36652).\n\n"
        "Tool Failure Repeat Rate y Stale Data Hallucination Rate: menor es mejor.\n\n"
        "| Adaptador | Constraint Compliance Rate (%) | Tool Failure Repeat Rate (%) "
        "| Stale Data Hallucination Rate (%) | Raw Detail Recall via M_pas (%) "
        "| Tokens Promedio Inyectados en Prompt |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: |\n"
    )
    lines = [header.rstrip("\n")]
    for run in runs:
        metrics = run.metrics
        lines.append(
            "| {name} | {compliance:.0f} | {repeat:.0f} | {stale:.0f} | {recall:.0f} | {tokens:.1f} |".format(
                name=run.adapter_name,
                compliance=metrics.constraint_compliance,
                repeat=metrics.tool_failure_repeat,
                stale=metrics.stale_hallucination,
                recall=metrics.raw_detail_recall,
                tokens=metrics.avg_prompt_tokens,
            )
        )
    lines.append("")
    lines.append(_reading(runs))
    lines.append("")
    return "\n".join(lines) + "\n"


def _reading(runs: list[AdapterRun]) -> str:
    named = {run.adapter_name: run.metrics for run in runs}
    flat = named["FlatSummarizerAdapter"]
    legacy = named["MemGraphRAGLegacyAdapter"]
    v2 = named["MemGraphRAGV2Adapter"]
    return (
        "Lectura: el resumen plano pierde el rechazo de Miami, el HTTP 409 y "
        f"el dato incidental (compliance {flat.constraint_compliance:.0f}%, "
        f"reintento {flat.tool_failure_repeat:.0f}%, "
        f"recall {flat.raw_detail_recall:.0f}%). "
        "Legacy conserva ese texto en el grafo, pero no vence la tarifa "
        f"(alucinación {legacy.stale_hallucination:.0f}%) ni abre M_pas "
        f"(recall {legacy.raw_detail_recall:.0f}%). "
        "V2 tipa el rechazo y el fallo, poda la tarifa dentro del PPR y "
        f"recupera el pasaje crudo (compliance {v2.constraint_compliance:.0f}%, "
        f"reintento {v2.tool_failure_repeat:.0f}%, "
        f"alucinación {v2.stale_hallucination:.0f}%, "
        f"recall {v2.raw_detail_recall:.0f}%)."
    )


def write_results(runs: list[AdapterRun], path: Path = RESULTS_PATH) -> Path:
    path.write_text(render_results(runs), encoding="utf-8")
    return path


def main() -> int:
    runs = run_suite()
    report = render_results(runs)
    write_results(runs)
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
