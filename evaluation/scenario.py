"""Conversación de 12 turnos para el banco de efectividad.

El reloj salta tres horas antes del turno 11. La tarifa guardada en el turno 9
con TTL de una hora ya está vencida. Entre el rechazo de Miami (turno 3) y el
cierre (turno 12) hay ocho turnos de hoteles, seguros y logística.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ScenarioTurn:
    index: int
    kind: str
    user: str
    as_of: datetime


def _clock(index: int) -> datetime:
    if index >= 11:
        return BASE + timedelta(hours=3)
    return BASE + timedelta(minutes=index - 1)


def build_scenario() -> tuple[ScenarioTurn, ...]:
    script = (
        (
            "constraint",
            "Armemos un viaje de Buenos Aires a Madrid para dos adultos y una nena. "
            "El presupuesto máximo es 3500 dólares: es un tope duro.",
        ),
        (
            "aside",
            "De paso, la nena tiene 7 años y es celíaca: no puede comer gluten.",
        ),
        (
            "rejection",
            "Rechazo cualquier escala en Miami. No tienen visa de tránsito.",
        ),
        (
            "hotel_search",
            "Buscame hoteles en el centro de Madrid, cerca del Prado.",
        ),
        (
            "book",
            "Reservá el Hotel Norte para esas fechas.",
        ),
        (
            "insurance",
            "¿Qué seguros de viaje cubren cancelación?",
        ),
        (
            "museum",
            "Sumá entradas al Museo del Prado y al Reina Sofía.",
        ),
        (
            "transfer",
            "Necesito traslado del aeropuerto de Barajas al centro.",
        ),
        (
            "quote",
            "Cotizame el vuelo EZE-MAD con la tarifa vigente.",
        ),
        (
            "restaurant",
            "¿Hay algún restaurante sin cola cerca del hotel?",
        ),
        (
            "ask_fare",
            "¿Sigue en pie la tarifa aérea que me pasaste?",
        ),
        (
            "close",
            "Reprogramá el vuelo y cerrá la reserva del hotel. "
            "Decime la edad exacta de la nena y qué restricción alimentaria tiene.",
        ),
    )
    if len(script) != 12:
        raise RuntimeError(f"la conversación tiene que tener 12 turnos, hay {len(script)}")
    return tuple(
        ScenarioTurn(index=index, kind=kind, user=user, as_of=_clock(index))
        for index, (kind, user) in enumerate(script, start=1)
    )


SCENARIO = build_scenario()
ASIDE_PASSAGE = SCENARIO[1].user
