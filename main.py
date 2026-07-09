"""Entrypoint interactivo del agente OKF de itinerarios.

Uso:
    uv run python main.py
    # o
    .venv/bin/python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Carga .env antes de importar el agente (que construye el modelo al importar).
_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

from agents.travel_agent import ask, create_travel_agent  # noqa: E402
from core.config import get_vault_root  # noqa: E402


def _print_response(response) -> None:
    content = getattr(response, "content", None) or str(response)
    print(f"\nagente>\n{content}\n")


def run_once(message: str) -> None:
    agent = create_travel_agent()
    response = ask(agent, message)
    _print_response(response)


def run_repl() -> None:
    print("Escribí tu consulta. Comandos: 'salir' / 'exit' / 'quit' para terminar.\n")
    agent = create_travel_agent()
    while True:
        try:
            message = input("vos> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nChau.")
            return

        if not message:
            continue
        if message.lower() in {"salir", "exit", "quit", "q"}:
            print("Chau.")
            return

        try:
            response = ask(agent, message)
        except Exception as exc:  # noqa: BLE001 — CLI: mostrar error y seguir
            print(f"\n[error] {type(exc).__name__}: {exc}\n")
            continue

        _print_response(response)


def main() -> None:
    vault = get_vault_root()
    print(f"OKF Travel Agent — vault: {vault}")

    # Modo one-shot: python main.py "tu pregunta"
    if len(sys.argv) > 1:
        run_once(" ".join(sys.argv[1:]))
        return

    if not sys.stdin.isatty():
        print(
            "No hay terminal interactiva. Usá:\n"
            '  .venv/bin/python main.py "tu pregunta"\n'
            "o corré el REPL desde tu propia terminal.",
            file=sys.stderr,
        )
        sys.exit(2)

    run_repl()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo arrancar: {exc}", file=sys.stderr)
        sys.exit(1)
