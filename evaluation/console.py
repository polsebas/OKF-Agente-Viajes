"""Consola interactiva de reservas.

Desde la raíz del paquete, en tu terminal:

    uv run python -m evaluation.console
    uv run python -m evaluation.console --demo
    uv run python main.py --consola
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

from agents.booking import HOTEL_NORTE, BookingDesk
from agents.booking_chat import BookingChat
from agents.prao import TravelPraoLoop, TurnTrace
from evaluation.scenario import BASE, SCENARIO
from memory import MemoryMode, build_memory_adapter

_MODE_ALIASES = {
    "flat": MemoryMode.FLAT,
    "resumen": MemoryMode.FLAT,
    "legacy": MemoryMode.LEGACY,
    "v2": MemoryMode.V2,
    "memgraphrag_v2": MemoryMode.V2,
    "memgraphrag_legacy": MemoryMode.LEGACY,
    "flat_summarizer": MemoryMode.FLAT,
}

HELP = """Estás hablando con el agente. Escribí como en un chat.
Comandos, si los necesitás:
  modo flat|legacy|v2   cambia la memoria y empieza de cero
  memoria               muestra lo que la memoria inyecta ahora
  avanzar [horas]       mueve el reloj (default 3) para vencer una tarifa
  demo                  corre el guion de 12 turnos, sin el modelo
  ayuda
  salir
"""


class ReservationConsole:
    def __init__(self, mode: MemoryMode = MemoryMode.V2) -> None:
        self.mode = mode
        self.quoted = False
        self.chat: BookingChat | None = None
        self._boot()

    def _boot(self) -> None:
        self.adapter = build_memory_adapter(self.mode)
        self.desk = BookingDesk()
        self.loop = TravelPraoLoop(self.adapter, self.desk)
        self.now = BASE
        self.index = 0
        self.quoted = False
        self.chat = None

    def _chat(self) -> BookingChat:
        if self.chat is None:
            self.chat = BookingChat(self.mode)
            self.chat.now = self.now
        return self.chat

    async def handle(self, line: str) -> str | None:
        text = line.strip()
        if not text:
            return ""
        folded = text.casefold()
        if folded in {"salir", "exit", "quit", "q"}:
            return None
        if folded in {"ayuda", "help", "?"}:
            return HELP
        if folded.startswith("modo "):
            return self._switch_mode(folded.removeprefix("modo ").strip())
        if folded == "demo":
            return await self.demo()
        if folded == "memoria":
            return await self._memory()
        if folded.startswith("avanzar"):
            return self._advance(folded)
        chat = self._chat()
        return await asyncio.to_thread(self._speak, chat, text)

    async def _memory(self) -> str:
        adapter = self.chat.adapter if self.chat is not None else self.adapter
        moment = self.chat.now if self.chat is not None else self.now
        view = await adapter.aretrieve("estado del viaje hotel vuelo tarifa", as_of=moment)
        body = view.prompt.strip() or "(la memoria está vacía)"
        return f"[{adapter.name} | {view.tokens} tokens]\n{body}"

    def _speak(self, chat: BookingChat, text: str) -> str:
        started = False

        def on_delta(chunk: str) -> None:
            nonlocal started
            if not started:
                print("\nagente> ", end="", flush=True)
                started = True
            print(chunk, end="", flush=True)

        def on_status(note: str) -> None:
            print(f"\n… {note}", flush=True)

        reply = chat.reply(text, on_delta=on_delta, on_status=on_status)
        if started:
            print("\n")
            return ""
        return reply

    async def demo(self) -> str:
        self._boot()
        traces = await self.loop.run(SCENARIO)
        self.index = len(SCENARIO)
        self.now = SCENARIO[-1].as_of
        self.quoted = True
        lines = [f"Demo con {self.adapter.name}. Hotel Norte abre sin cupo; la reserva sigue en Hotel Prado.\n"]
        for turn, trace in zip(SCENARIO, traces, strict=True):
            lines.append(f"vos> {turn.user}")
            lines.append(f"agente> {_format_reply(trace, self.adapter.name)}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _switch_mode(self, name: str) -> str:
        mode = _MODE_ALIASES.get(name)
        if mode is None:
            return "Modos: flat, legacy, v2."
        self.mode = mode
        self._boot()
        return f"Memoria: {self.adapter.name}. Sesión nueva."

    def _advance(self, folded: str) -> str:
        parts = folded.split()
        hours = 3.0
        if len(parts) > 1:
            try:
                hours = float(parts[1].replace(",", "."))
            except ValueError:
                return "Usá `avanzar` o `avanzar 3`."
        if hours < 0:
            return "Las horas tienen que ser positivas."
        base = self.chat.now if self.chat is not None else self.now
        self.now = base + timedelta(hours=hours)
        if self.chat is not None:
            self.chat.now = self.now
        return f"Reloj en {self.now.strftime('%Y-%m-%d %H:%M UTC')}."


def _format_reply(trace: TurnTrace, adapter_name: str) -> str:
    lines = [trace.observation.strip() or "(sin acción)"]
    if trace.kind == "book" and HOTEL_NORTE in trace.observation and "409" in trace.observation:
        lines.append("El cupo de Hotel Norte sigue en cero. El 409 queda en la memoria de este modo.")
    if trace.route:
        lines.append(f"Vuelo elegido: {trace.route}.")
    if trace.kind == "close" and trace.hotel:
        lines.append(f"Hotel del cierre: {trace.hotel}.")
    if trace.drilldown_text:
        lines.append(f"Pasaje M_pas: {trace.drilldown_text}")
    if trace.kind == "ask_fare":
        estado = "recotizada en el escritorio" if trace.refreshed_quote else "tomada de la memoria"
        lines.append(f"Tarifa {estado}.")
    lines.append(f"[{adapter_name}]")
    return "\n".join(lines)


async def _repl(mode: MemoryMode) -> None:
    session = ReservationConsole(mode)
    print(f"Agente de reservas — {session.adapter.name}")
    print("Escribile como en un chat. La respuesta sale de a una, con el modelo local.")
    print("Las reservas, las tarifas y la memoria pasan por herramientas, no por un guion.")
    print("`ayuda` para los comandos. `salir` para terminar.\n")
    while True:
        try:
            line = await asyncio.to_thread(input, "vos> ")
        except (EOFError, KeyboardInterrupt):
            print("\nChau.")
            return
        reply = await session.handle(line)
        if reply is None:
            print("Chau.")
            return
        if reply:
            print(f"\nagente>\n{reply}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consola interactiva de reservas con memoria.")
    parser.add_argument("--modo", default="v2", help="flat, legacy o v2")
    parser.add_argument("--demo", action="store_true", help="corre los 12 turnos y sale")
    args = parser.parse_args(argv)
    mode = _MODE_ALIASES.get(args.modo.casefold())
    if mode is None:
        print("Modo desconocido. Usá flat, legacy o v2.", file=sys.stderr)
        return 2
    if args.demo:
        print(asyncio.run(ReservationConsole(mode).demo()), end="")
        return 0
    if not sys.stdin.isatty():
        print(
            "Esta consola necesita tu terminal. Corré:\n"
            "  uv run python -m evaluation.console\n"
            "o, para ver los 12 turnos sin escribir:\n"
            "  uv run python -m evaluation.console --demo",
            file=sys.stderr,
        )
        return 2
    asyncio.run(_repl(mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
