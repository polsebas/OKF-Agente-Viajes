"""Corrida real del agente sobre los 12 turnos, y el informe de RESULTS.md.

El banco controlado (PRAO, sin LLM) se vuelve a medir en la misma corrida.
El agente usa el modelo configurado en el entorno. La charla reciente no se
reinyecta: el único recuerdo entre turnos es el adaptador de memoria, que es
lo que la tabla compara.

    uv run python -m evaluation.live_evidence
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from agents.booking import HOTEL_NORTE, LIVE_FARE_USD, STALE_FARE_USD
from agents.booking_chat import BookingChat
from evaluation.run_effectiveness_suite import render_results, run_suite
from evaluation.scenario import SCENARIO
from memory import MemoryMode

RESULTS_PATH = Path(__file__).resolve().parent / "RESULTS.md"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"

_MODES = (MemoryMode.FLAT, MemoryMode.LEGACY, MemoryMode.V2)
_MIAMI = re.compile(r"miami|\bmia\b|eze-mia", re.IGNORECASE)
_MIAMI_NEGATED = re.compile(
    r"(?:no|sin|evit\w*|rechaz\w*|nada|fuera|salte\w*|descart\w*).{0,60}(?:miami|\bmia\b)"
    r"|(?:miami|\bmia\b).{0,50}(?:no\b|rechaz|evit|fuera|descart)",
    re.IGNORECASE,
)
_STALE_AFFIRM = re.compile(
    r"sigue en pie|sigue vigente|sigue siendo|la misma tarifa|no cambi[oó]",
    re.IGNORECASE,
)


@dataclass
class LiveTurn:
    index: int
    kind: str
    user: str
    as_of: str
    reply: str
    memory_prompt: str
    memory_tokens: int
    tools: list[dict[str, object]] = field(default_factory=list)


@dataclass
class LiveMetrics:
    constraint_compliance: float
    tool_failure_repeat: float
    stale_hallucination: float
    raw_detail_recall: float
    answer_detail_recall: float
    avg_prompt_tokens: float
    norte_attempts: int
    drilldown_called: bool
    close_proposes_miami: bool
    ask_fare_reply: str
    close_reply: str
    book_reply: str
    memory_at_close_has_rejection: bool
    memory_at_close_has_409: bool
    memory_at_ask_has_stale_fare: bool
    memory_at_close_has_age: bool


@dataclass
class LiveRun:
    adapter_name: str
    mode: str
    supports_drilldown: bool
    metrics: LiveMetrics
    turns: list[LiveTurn]
    attempts: list[str]
    facts: list[dict[str, str]]
    elapsed_seconds: float


def proposes_miami(text: str) -> bool:
    """True si el texto ofrece Miami, no si lo está rechazando."""
    if not _MIAMI.search(text):
        return False
    stripped = _MIAMI_NEGATED.sub(" ", text)
    return _MIAMI.search(stripped) is not None


def affirms_stale_fare(text: str) -> bool:
    """True si presenta 890 como tarifa vigente y no muestra el precio nuevo."""
    has_new = re.search(rf"\b{LIVE_FARE_USD}\b", text) is not None
    if has_new:
        return False
    if re.search(rf"\b{STALE_FARE_USD}\b", text):
        return True
    return _STALE_AFFIRM.search(text) is not None


def detail_hits(text: str) -> int:
    found = 0
    if re.search(r"\b7\b", text):
        found += 1
    if re.search(r"cel[ií]ac|gluten", text, re.IGNORECASE):
        found += 1
    return found


def _turn(turns: list[LiveTurn], kind: str) -> LiveTurn:
    return next(turn for turn in turns if turn.kind == kind)


def score_live_run(
    turns: list[LiveTurn],
    attempts: list[str],
    *,
    supports_drilldown: bool,
) -> LiveMetrics:
    close = _turn(turns, "close")
    ask = _turn(turns, "ask_fare")
    book = _turn(turns, "book")
    violation = proposes_miami(close.reply)
    norte_attempts = sum(1 for name in attempts if name == HOTEL_NORTE)
    drill_blob = "\n".join(
        str(call.get("result") or "")
        for turn in turns
        for call in turn.tools
        if call.get("name") == "leer_pasaje"
    )
    drilldown_called = bool(drill_blob.strip())
    asked = 2
    via_pas = detail_hits(drill_blob) if supports_drilldown else 0
    in_answer = detail_hits(close.reply)
    tokens = [turn.memory_tokens for turn in turns]
    close_memory = close.memory_prompt.casefold()
    ask_memory = ask.memory_prompt.casefold()
    return LiveMetrics(
        constraint_compliance=0.0 if violation else 100.0,
        tool_failure_repeat=100.0 if norte_attempts > 1 else 0.0,
        stale_hallucination=100.0 if affirms_stale_fare(ask.reply) else 0.0,
        raw_detail_recall=100.0 * via_pas / asked,
        answer_detail_recall=100.0 * in_answer / asked,
        avg_prompt_tokens=(sum(tokens) / len(tokens)) if tokens else 0.0,
        norte_attempts=norte_attempts,
        drilldown_called=drilldown_called,
        close_proposes_miami=violation,
        ask_fare_reply=ask.reply,
        close_reply=close.reply,
        book_reply=book.reply,
        memory_at_close_has_rejection="miami" in close_memory and "rechaz" in close_memory,
        memory_at_close_has_409="409" in close_memory or "sin cupo" in close_memory,
        memory_at_ask_has_stale_fare=str(STALE_FARE_USD) in ask.memory_prompt,
        memory_at_close_has_age=bool(re.search(r"\b7\b", close.memory_prompt)),
    )


def run_live_mode(mode: MemoryMode) -> LiveRun:
    started = datetime.now(timezone.utc)
    chat = BookingChat(mode, history_messages=0)
    turns: list[LiveTurn] = []
    for turn in SCENARIO:
        chat.now = turn.as_of - timedelta(minutes=1)
        print(f"  [{chat.adapter.name}] turno {turn.index} {turn.kind}", flush=True)
        reply = chat.reply(turn.user)
        print(f"    {reply[:160].replace(chr(10), ' ')}", flush=True)
        turns.append(
            LiveTurn(
                index=turn.index,
                kind=turn.kind,
                user=turn.user,
                as_of=turn.as_of.isoformat(),
                reply=reply,
                memory_prompt=chat.last_memory_prompt,
                memory_tokens=chat.last_memory_tokens,
                tools=list(chat.turn_tools),
            )
        )
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    facts = _fact_rows(chat.adapter)
    return LiveRun(
        adapter_name=chat.adapter.name,
        mode=mode.value,
        supports_drilldown=bool(chat.adapter.supports_drilldown),
        metrics=score_live_run(
            turns,
            list(chat.desk.attempts),
            supports_drilldown=bool(chat.adapter.supports_drilldown),
        ),
        turns=turns,
        attempts=list(chat.desk.attempts),
        facts=facts,
        elapsed_seconds=elapsed,
    )


def _fact_rows(adapter: object) -> list[dict[str, str]]:
    memory = getattr(adapter, "memory", None)
    facts = getattr(memory, "facts", None)
    if not facts:
        return []
    rows: list[dict[str, str]] = []
    for fact in facts.values():
        category = getattr(fact.category, "value", str(fact.category))
        rows.append(
            {
                "relation": str(fact.relation),
                "category": str(category),
                "ttl_seconds": "" if fact.ttl_seconds is None else str(fact.ttl_seconds),
                "prompt_text": str(fact.metadata.get("prompt_text") or "")[:240],
            }
        )
    return rows


def render_live_report(runs: list[LiveRun], *, model_id: str, controlled: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Resultados — efectividad de memoria en OKF-Agente-Viajes",
        "",
        f"Corrida del {generated}. Modelo del agente: `{model_id}`.",
        "Papers de referencia: MemoryTax (arXiv:2610.29823), "
        "MemDev-Bench (arXiv:2610.27524) y Remembering Is Not Enough "
        "(arXiv:2610.36652).",
        "",
        "Tool Failure Repeat Rate y Stale Data Hallucination Rate: menor es mejor.",
        "",
        "## Agente conversacional",
        "",
        "Los 12 turnos del escenario los responde el agente, con las herramientas "
        "de reserva y el adaptador de memoria. El reloj salta a la marca de cada "
        "turno (la tarifa vence antes del turno 11). La charla reciente no vuelve "
        "al prompt: entre un turno y el siguiente solo entra lo que el adaptador recupera.",
        "",
        "| Adaptador | Constraint Compliance Rate (%) | Tool Failure Repeat Rate (%) "
        "| Stale Data Hallucination Rate (%) | Raw Detail Recall via M_pas (%) "
        "| Tokens Promedio Inyectados en Prompt |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
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
    lines.append(_live_reading(runs))
    lines.append("")
    lines.append("### Qué se midió en cada respuesta")
    lines.append("")
    lines.append(
        "| Adaptador | Intentos Hotel Norte | Miami en el cierre | "
        "890 todavía en memoria al pedir la tarifa | Drill-down M_pas | "
        "Detalle en la respuesta (%) |"
    )
    lines.append("| --- | ---: | --- | --- | --- | ---: |")
    for run in runs:
        metrics = run.metrics
        lines.append(
            "| {name} | {norte} | {miami} | {stale} | {drill} | {answer:.0f} |".format(
                name=run.adapter_name,
                norte=metrics.norte_attempts,
                miami="sí" if metrics.close_proposes_miami else "no",
                stale="sí" if metrics.memory_at_ask_has_stale_fare else "no",
                drill="sí" if metrics.drilldown_called else "no",
                answer=metrics.answer_detail_recall,
            )
        )
    lines.append("")
    lines.append(_traces(runs))
    lines.append("## Banco controlado")
    lines.append("")
    lines.append(
        "Misma conversación y mismas métricas, con el bucle PRAO y sin modelo. "
        "La política de decisión es idéntica en los tres adaptadores; cambia solo la memoria. "
        "Sirve para aislar el adaptador del criterio del modelo."
    )
    lines.append("")
    controlled_body = controlled.split("\n", 2)[-1].strip()
    lines.append(controlled_body)
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _live_reading(runs: list[LiveRun]) -> str:
    sentences = []
    notes = []
    for run in runs:
        metrics = run.metrics
        calls = "1 llamada" if metrics.norte_attempts == 1 else f"{metrics.norte_attempts} llamadas"
        sentences.append(
            f"{run.adapter_name}: compliance {metrics.constraint_compliance:.0f}%, "
            f"reintento {metrics.tool_failure_repeat:.0f}% "
            f"({calls} a Hotel Norte), "
            f"alucinación de tarifa {metrics.stale_hallucination:.0f}%, "
            f"recall por M_pas {metrics.raw_detail_recall:.0f}%, "
            f"el cierre nombra el dato en {metrics.answer_detail_recall:.0f}% "
            f"de los dos detalles pedidos."
        )
        notes.append(_memory_note(run))
    return (
        "Lectura de esta corrida: "
        + " ".join(sentences)
        + " "
        + " ".join(notes)
        + " El recall vía M_pas cuenta una llamada a leer_pasaje que devuelva la edad y la dieta. "
        + "Si el dato ya venía en el texto recuperado, la respuesta puede tenerlo igual y esa columna queda en 0."
    )


def _memory_note(run: LiveRun) -> str:
    metrics = run.metrics
    kept = []
    if metrics.memory_at_close_has_rejection:
        kept.append("el rechazo de Miami")
    if metrics.memory_at_close_has_409:
        kept.append("el 409")
    if metrics.memory_at_close_has_age:
        kept.append("la edad")
    if kept:
        body = "al cierre la memoria todavía trae " + ", ".join(kept)
    else:
        body = "al cierre la memoria ya no trae el rechazo, el 409 ni la edad"
    if metrics.memory_at_ask_has_stale_fare:
        fare = "el 890 sigue en la memoria al preguntar por la tarifa"
    else:
        fare = "el 890 ya no está en la memoria al preguntar por la tarifa"
    return f"{run.adapter_name}: {body}; {fare}."


def _traces(runs: list[LiveRun]) -> str:
    blocks = ["### Transcripciones decisivas", ""]
    for run in runs:
        blocks.append(f"#### {run.adapter_name}")
        blocks.append("")
        blocks.append(f"Duración {run.elapsed_seconds:.0f} s. Intentos de reserva: {', '.join(run.attempts) or 'ninguno'}.")
        blocks.append("")
        if run.facts:
            blocks.append("Hechos guardados:")
            blocks.append("")
            for fact in run.facts:
                ttl = f", ttl={fact['ttl_seconds']}s" if fact["ttl_seconds"] else ""
                blocks.append(
                    f"- `{fact['category']}` {fact['relation']}{ttl}: {fact['prompt_text']}"
                )
            blocks.append("")
        for kind, title in (
            ("book", "Turno 5, reserva"),
            ("ask_fare", "Turno 11, tarifa vencida"),
            ("close", "Turno 12, cierre"),
        ):
            turn = _turn(run.turns, kind)
            blocks.append(f"**{title}**")
            blocks.append("")
            blocks.append(f"Viajero: {turn.user}")
            blocks.append("")
            blocks.append("Memoria inyectada:")
            blocks.append("")
            blocks.append("```")
            blocks.append(turn.memory_prompt.strip() or "(vacía)")
            blocks.append("```")
            blocks.append("")
            if turn.tools:
                blocks.append("Herramientas:")
                blocks.append("")
                for call in turn.tools:
                    args = call.get("args") or {}
                    blocks.append(f"- `{call.get('name')}` {args} → {call.get('result')}")
                blocks.append("")
            blocks.append("Agente:")
            blocks.append("")
            blocks.append(turn.reply.strip() or "(sin texto)")
            blocks.append("")
    return "\n".join(blocks)


def write_evidence(runs: list[LiveRun], directory: Path = EVIDENCE_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "live_run.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": [_jsonable_run(run) for run in runs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _jsonable_run(run: LiveRun) -> dict:
    raw = asdict(run)
    return raw


def main() -> int:
    load_dotenv()
    model_id = os.getenv("OKF_PRIMARY_MODEL_ID", "desconocido")
    provider = os.getenv("OKF_PRIMARY_MODEL_PROVIDER", "desconocido")
    print("Banco controlado", flush=True)
    controlled = render_results(run_suite())
    live_runs: list[LiveRun] = []
    for mode in _MODES:
        print(f"Agente {mode.value}", flush=True)
        live_runs.append(run_live_mode(mode))
        write_evidence(live_runs)
    report = render_live_report(
        live_runs,
        model_id=f"{provider}:{model_id}",
        controlled=controlled,
    )
    RESULTS_PATH.write_text(report, encoding="utf-8")
    write_evidence(live_runs)
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
