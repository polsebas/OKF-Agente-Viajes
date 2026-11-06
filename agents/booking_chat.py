"""Charla con el agente de viajes. El modelo habla; las tools y la memoria no inventan."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta

from agno.agent import Agent
from agno.tools import tool
from dotenv import load_dotenv

from agents.booking import FARE_TTL_SECONDS, BookingConflict, BookingDesk
from core.config import get_resilient_model
from evaluation.scenario import BASE
from memory import MemoryMode, build_memory_adapter
from memory.protocol import FactWrite

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_TOOL_STATUS = {
    "reservar_hotel": "estoy mirando el cupo del hotel",
    "cotizar_vuelo": "estoy cotizando el vuelo",
    "registrar_hecho": "lo estoy anotando en la memoria",
    "leer_pasaje": "estoy abriendo el pasaje original",
}

_INSTRUCTIONS = """\
Sos un agente de viajes. Hablás en castellano rioplatense, en prosa corta, como en un chat.
Respondé lo que te acaban de decir. No armes listas ni actúes como un formulario.

No inventes precios, cupos ni datos del pasajero. Si hace falta un precio, llamá a cotizar_vuelo.
Si hay que reservar, llamá a reservar_hotel. Si la tool devuelve HTTP 409, no vuelvas a pedir ese hotel.
Cuando el viajero pone un tope, rechaza una escala o cuenta un dato personal, llamá a registrar_hecho
con la categoría que corresponda y un resumen corto. El texto crudo ya queda guardado.
Si te piden un dato exacto (edad, dieta, una frase textual) y en la memoria hay un id, llamá a leer_pasaje.
La memoria recuperada es lo que sabés de antes. No contradigas un rechazo ni un fallo que figure ahí.
"""


class BookingChat:
    def __init__(self, mode: MemoryMode = MemoryMode.V2, *, history_messages: int = 8) -> None:
        load_dotenv()
        self.mode = mode
        self.history_messages = history_messages
        self.adapter = build_memory_adapter(mode)
        self.desk = BookingDesk()
        self.now = BASE
        self._turn = 0
        self.transcript: list[tuple[str, str]] = []
        self.last_memory_prompt = ""
        self.last_memory_tokens = 0
        self.turn_tools: list[dict[str, object]] = []
        model = get_resilient_model()
        # qwen3 piensa en voz alta y la charla se traba. El itinerario OKF no se toca.
        if getattr(model, "provider", None) == "Ollama":
            extra = dict(getattr(model, "request_params", None) or {})
            extra["think"] = False
            model.request_params = extra
        self.agent = Agent(
            model=model,
            tools=self._tools(),
            instructions=_INSTRUCTIONS,
            markdown=False,
            tool_call_limit=5,
            add_history_to_context=False,
        )

    def advance(self, hours: float) -> None:
        self.now = self.now + timedelta(hours=hours)

    def reply(
        self,
        user_text: str,
        *,
        on_delta=None,
        on_status=None,
    ) -> str:
        self._turn += 1
        self.now = self.now + timedelta(minutes=1)
        self.turn_tools = []
        self._remember_utterance(user_text)
        view = asyncio.run(self.adapter.aretrieve(user_text, as_of=self.now))
        self.last_memory_prompt = view.prompt
        self.last_memory_tokens = view.tokens
        memory = view.prompt.strip() or "(todavía no hay nada en memoria)"
        window = self.transcript[-self.history_messages :] if self.history_messages else []
        recent = "\n".join(f"{who}: {said}" for who, said in window)
        prompt = (
            f"Reloj de la reserva: {self.now.strftime('%Y-%m-%d %H:%M UTC')}.\n\n"
            f"Memoria recuperada:\n{memory}\n\n"
            f"Conversación reciente:\n{recent or '(empieza ahora)'}\n\n"
            f"Viajero: {user_text}"
        )
        pieces: list[str] = []
        try:
            for event in self.agent.run(prompt, stream=True, stream_events=True):
                kind = getattr(event, "event", "")
                if kind == "RunContent":
                    chunk = getattr(event, "content", None)
                    if isinstance(chunk, str) and chunk:
                        pieces.append(chunk)
                        if on_delta is not None:
                            on_delta(chunk)
                elif kind == "ToolCallStarted" and on_status is not None:
                    tool = getattr(event, "tool", None)
                    name = str(getattr(tool, "tool_name", None) or getattr(tool, "name", "") or "")
                    on_status(_TOOL_STATUS.get(name, "estoy usando una herramienta"))
                elif kind == "ToolCallCompleted":
                    tool = getattr(event, "tool", None)
                    name = str(getattr(tool, "tool_name", None) or getattr(tool, "name", "") or "")
                    self.turn_tools.append(
                        {
                            "name": name,
                            "args": getattr(tool, "tool_args", None),
                            "result": str(getattr(tool, "result", "") or ""),
                        }
                    )
                elif kind == "RunCompleted" and not pieces:
                    content = getattr(event, "content", None)
                    if isinstance(content, str) and content.strip():
                        pieces.append(content)
                        if on_delta is not None:
                            on_delta(content)
        except Exception as exc:
            return f"No pude hablar con el modelo ({type(exc).__name__}: {exc})."
        text = _clean("".join(pieces))
        self.transcript.append(("Viajero", user_text))
        self.transcript.append(("Agente", text))
        return text

    def _remember_utterance(self, user_text: str) -> None:
        asyncio.run(
            self.adapter.awrite(
                FactWrite(
                    passage=user_text,
                    head="Viajero",
                    head_type="Traveler",
                    relation="SAID",
                    tail=f"turno-{self._turn}",
                    tail_type="Utterance",
                    schema_text="dicho del viajero en la conversacion",
                    prompt_text=user_text,
                    as_of=self.now,
                    category="declarative",
                )
            )
        )

    def _tools(self) -> list:
        desk = self.desk
        adapter = self.adapter
        chat = self

        @tool
        def reservar_hotel(nombre: str) -> str:
            """Reserva un hotel por nombre. Si no hay cupo, devuelve HTTP 409 y no hay que reintentar ese hotel."""
            try:
                return desk.book_hotel(nombre)
            except BookingConflict as exc:
                asyncio.run(
                    adapter.awrite(
                        FactWrite(
                            passage=str(exc),
                            head=exc.resource,
                            head_type="Hotel",
                            relation="BOOKING_FAILED",
                            tail=exc.resource,
                            tail_type="Error",
                            schema_text=f"fallo de reserva hotel {exc.resource}",
                            prompt_text=f"{exc.resource} BOOKING_FAILED HTTP 409 Conflict sin cupo",
                            as_of=chat.now,
                            category="tool_failure",
                        )
                    )
                )
                alternative = desk.alternative_to(exc.resource)
                if alternative is None:
                    return f"HTTP {exc.status} Conflict: sin cupo en {exc.resource}. No lo reintentes."
                confirmed = desk.book_hotel(alternative)
                return (
                    f"HTTP {exc.status} Conflict: sin cupo en {exc.resource}. "
                    f"No lo reintentes. {confirmed}."
                )

        @tool
        def cotizar_vuelo() -> str:
            """Devuelve la tarifa vigente de EZE-MAD. No inventes otro precio."""
            price = desk.quote_flight(chat.now)
            asyncio.run(
                adapter.awrite(
                    FactWrite(
                        passage=f"Cotización EZE-MAD: {price} USD",
                        head="EZE-MAD",
                        head_type="Flight",
                        relation="QUOTED_PRICE",
                        tail=f"{price} USD",
                        tail_type="Price",
                        schema_text="tarifa aérea cotización vuelo precio",
                        prompt_text=f"Tarifa aérea QUOTED_PRICE {price} USD",
                        as_of=chat.now,
                        category="declarative",
                        ttl_seconds=FARE_TTL_SECONDS,
                    )
                )
            )
            return f"Tarifa vigente EZE-MAD: {price} USD. Vence en {FARE_TTL_SECONDS // 60} minutos de reloj."

        @tool
        def registrar_hecho(categoria: str, resumen: str) -> str:
            """Guarda un hecho corto. categoria: hard_constraint, rejected_option, declarative o tool_failure."""
            allowed = {"hard_constraint", "rejected_option", "declarative", "tool_failure"}
            kind = categoria.strip().lower().replace("-", "_").replace(" ", "_")
            if kind not in allowed:
                return f"Categoría inválida. Usá una de: {', '.join(sorted(allowed))}."
            asyncio.run(
                adapter.awrite(
                    FactWrite(
                        passage=resumen.strip(),
                        head="Viajero",
                        head_type="Traveler",
                        relation=kind.upper(),
                        tail=resumen.strip()[:120],
                        tail_type="Note",
                        schema_text=f"hecho de conversacion {kind}",
                        prompt_text=f"{kind}: {resumen.strip()}",
                        as_of=chat.now,
                        category=kind,
                    )
                )
            )
            return "Quedó en memoria."

        @tool
        def leer_pasaje(fact_id: str) -> str:
            """Lee el texto crudo de M_pas para un id de la memoria. No lo resumas."""
            if not adapter.supports_drilldown:
                return "Este modo de memoria no abre el pasaje crudo."
            try:
                return adapter.expand_fact_evidence(fact_id)
            except Exception as exc:
                return f"No encontré ese pasaje ({exc})."

        tools = [reservar_hotel, cotizar_vuelo, registrar_hecho]
        if adapter.supports_drilldown:
            tools.append(leer_pasaje)
        return tools


def _clean(text: str) -> str:
    cleaned = _THINK.sub("", text).strip()
    return cleaned or "Perdón, me quedé pensando y no dije nada. ¿Seguimos?"
