"""Bucle PRAO del itinerario: Percibir, Razonar, Actuar, Observar.

La intención del turno corriente está etiquetada en el escenario. Lo que cambia
entre adaptadores es la memoria de los turnos anteriores: el razonador solo
mira ``MemoryView`` y, si el modo lo permite, ``expand_fact_evidence``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agents.booking import (
    BUDGET_USD,
    FARE_TTL_SECONDS,
    HOTEL_NORTE,
    HOTEL_PRADO,
    LIVE_FARE_USD,
    MIAMI_ROUTE,
    SAFE_ROUTE,
    STALE_FARE_USD,
    BookingConflict,
    BookingDesk,
)
from memory.protocol import FactWrite, MemoryView

_AGE_NEEDLE = "7"
_DIET_NEEDLE = "celíaca"


@dataclass
class TurnTrace:
    index: int
    kind: str
    prompt: str
    prompt_tokens: int
    retrieved_relations: tuple[str, ...] = ()
    retrieved_categories: tuple[str, ...] = ()
    route: str = ""
    hotel: str = ""
    fare_usd: int | None = None
    refreshed_quote: bool = False
    drilldown_text: str = ""
    violated_constraint: bool = False
    repeated_failure: bool = False
    decided_route: bool = False
    attempted_blocked_resource: bool = False
    checked_stale_fare: bool = False
    stale_hallucination: bool = False
    asked_raw_detail: bool = False
    raw_details_asked: int = 0
    raw_details_found: int = 0
    observation: str = ""
    notes: list[str] = field(default_factory=list)


def _rejects_miami(view: MemoryView) -> bool:
    for fact in view.facts:
        blob = f"{fact.text} {fact.tail} {fact.relation}".lower()
        if "miami" not in blob:
            continue
        if fact.category == "rejected_option" or "rechaz" in blob or "rejected" in blob:
            return True
    prompt = view.prompt.lower()
    return "miami" in prompt and "rechaz" in prompt


def _blocks_hotel(view: MemoryView, hotel: str) -> bool:
    name = hotel.lower()
    for fact in view.facts:
        blob = f"{fact.text} {fact.tail}".lower()
        if name not in blob:
            continue
        if fact.category == "tool_failure" or "409" in blob:
            return True
    prompt = view.prompt.lower()
    return name in prompt and "409" in prompt


def _remembered_stale_fare(view: MemoryView) -> bool:
    needle = str(STALE_FARE_USD)
    for fact in view.facts:
        if fact.relation == "QUOTED_PRICE" and needle in fact.text:
            return True
        if fact.relation == "SUMMARY" and needle in fact.text:
            return True
    return needle in view.prompt


def _count_details(text: str) -> int:
    found = 0
    if _AGE_NEEDLE in text:
        found += 1
    if _DIET_NEEDLE in text.lower() or "celiaca" in text.lower():
        found += 1
    return found


class TravelPraoLoop:
    """Un viaje, un adaptador, un escritorio de reservas."""

    def __init__(self, memory, desk: BookingDesk | None = None) -> None:
        self.memory = memory
        self.desk = desk or BookingDesk()

    async def run(self, turns) -> list[TurnTrace]:
        traces: list[TurnTrace] = []
        for turn in turns:
            traces.append(await self.step(turn))
        return traces

    async def step(self, turn) -> TurnTrace:
        view = await self.memory.aretrieve(turn.user, as_of=turn.as_of)
        trace = TurnTrace(
            index=turn.index,
            kind=turn.kind,
            prompt=view.prompt,
            prompt_tokens=view.tokens,
            retrieved_relations=tuple(fact.relation for fact in view.facts),
            retrieved_categories=tuple(fact.category for fact in view.facts),
        )
        await self._act(turn, view, trace)
        await self._observe(turn, trace)
        return trace

    async def _act(self, turn, view: MemoryView, trace: TurnTrace) -> None:
        if turn.kind == "book":
            await self._try_book(HOTEL_NORTE, trace, repeated=False)
            return
        if turn.kind == "quote":
            price = self.desk.quote_flight(turn.as_of)
            trace.fare_usd = price
            trace.observation = f"Cotización vigente del vuelo EZE-MAD: {price} USD"
            return
        if turn.kind == "ask_fare":
            trace.checked_stale_fare = True
            if _remembered_stale_fare(view):
                trace.fare_usd = STALE_FARE_USD
                trace.stale_hallucination = True
                trace.refreshed_quote = False
                trace.observation = f"La tarifa sigue en {STALE_FARE_USD} USD"
                return
            price = self.desk.quote_flight(turn.as_of)
            trace.fare_usd = price
            trace.refreshed_quote = True
            trace.stale_hallucination = price == STALE_FARE_USD
            trace.observation = f"Recotizado en el escritorio: {price} USD"
            return
        if turn.kind == "close":
            trace.decided_route = True
            trace.attempted_blocked_resource = True
            trace.asked_raw_detail = True
            trace.raw_details_asked = 2
            trace.route = SAFE_ROUTE if _rejects_miami(view) else MIAMI_ROUTE
            trace.violated_constraint = "MIA" in trace.route or "Miami" in trace.route
            hotel = HOTEL_PRADO if _blocks_hotel(view, HOTEL_NORTE) else HOTEL_NORTE
            trace.hotel = hotel
            trace.repeated_failure = hotel == HOTEL_NORTE
            if hotel == HOTEL_NORTE:
                await self._try_book(hotel, trace, repeated=True)
            else:
                trace.notes.append(self.desk.book_hotel(hotel))
            aside = next((fact for fact in view.facts if fact.relation == "HAS_ASIDE"), None)
            if aside is not None and self.memory.supports_drilldown:
                trace.drilldown_text = self.memory.expand_fact_evidence(aside.fact_id)
                recalled = trace.drilldown_text
            else:
                recalled = view.prompt
            trace.raw_details_found = _count_details(recalled)
            trace.observation = (
                f"Cierre: vuelo {trace.route}; hotel {hotel}; detalle recuperado: {recalled}"
            )
            return
        trace.observation = _distractor_observation(turn.kind)

    async def _try_book(self, hotel: str, trace: TurnTrace, *, repeated: bool) -> None:
        trace.hotel = hotel
        trace.repeated_failure = repeated
        try:
            trace.observation = self.desk.book_hotel(hotel)
        except BookingConflict as exc:
            trace.observation = (
                f"HTTP {exc.status} Conflict al reservar {exc.resource}: {exc.detail}"
            )
            trace.notes.append(trace.observation)

    async def _observe(self, turn, trace: TurnTrace) -> None:
        as_of: datetime = turn.as_of
        if turn.kind == "constraint":
            await self.memory.awrite(
                FactWrite(
                    passage=turn.user,
                    head="Presupuesto",
                    head_type="Budget",
                    relation="HARD_CAP",
                    tail=BUDGET_USD,
                    tail_type="Money",
                    schema_text="presupuesto máximo del viajero tope duro",
                    prompt_text=f"Presupuesto HARD_CAP {BUDGET_USD}",
                    as_of=as_of,
                    category="hard_constraint",
                )
            )
            return
        if turn.kind == "aside":
            await self.memory.awrite(
                FactWrite(
                    passage=turn.user,
                    head="Pasajera",
                    head_type="Passenger",
                    relation="HAS_ASIDE",
                    tail="restricción alimentaria",
                    tail_type="Detail",
                    schema_text="pasajero restricción alimentaria detalle incidental",
                    prompt_text="Pasajera HAS_ASIDE restricción alimentaria",
                    as_of=as_of,
                    category="declarative",
                )
            )
            return
        if turn.kind == "rejection":
            await self.memory.awrite(
                FactWrite(
                    passage=turn.user,
                    head="Cliente",
                    head_type="Traveler",
                    relation="REJECTED_LAYOVER",
                    tail="Miami",
                    tail_type="City",
                    schema_text="ruta aérea vuelo escala ciudad rechazada",
                    prompt_text="Cliente rechazó escala Miami en el vuelo",
                    as_of=as_of,
                    category="rejected_option",
                )
            )
            return
        if turn.kind == "book":
            await self.memory.awrite(
                FactWrite(
                    passage=trace.observation,
                    head=HOTEL_NORTE,
                    head_type="Hotel",
                    relation="BOOKING_FAILED",
                    tail=HOTEL_NORTE,
                    tail_type="Error",
                    schema_text="fallo de herramienta hotel reserva cupo",
                    prompt_text=f"{HOTEL_NORTE} BOOKING_FAILED HTTP 409 Conflict sin cupo",
                    as_of=as_of,
                    category="tool_failure",
                )
            )
            return
        if turn.kind == "quote":
            price = trace.fare_usd if trace.fare_usd is not None else STALE_FARE_USD
            await self.memory.awrite(
                FactWrite(
                    passage=trace.observation,
                    head="EZE-MAD",
                    head_type="Flight",
                    relation="QUOTED_PRICE",
                    tail=f"{price} USD",
                    tail_type="Price",
                    schema_text="tarifa aérea cotización vuelo precio",
                    prompt_text=f"Tarifa aérea QUOTED_PRICE {price} USD",
                    as_of=as_of,
                    category="declarative",
                    ttl_seconds=FARE_TTL_SECONDS,
                )
            )
            return
        if turn.kind == "ask_fare" and trace.refreshed_quote:
            price = trace.fare_usd if trace.fare_usd is not None else LIVE_FARE_USD
            await self.memory.awrite(
                FactWrite(
                    passage=trace.observation,
                    head="EZE-MAD",
                    head_type="Flight",
                    relation="QUOTED_PRICE_REFRESH",
                    tail=f"{price} USD",
                    tail_type="Price",
                    schema_text="tarifa aérea recotización vuelo precio",
                    prompt_text=f"Tarifa aérea recotizada {price} USD",
                    as_of=as_of,
                    category="declarative",
                    ttl_seconds=FARE_TTL_SECONDS,
                )
            )
            return
        if turn.kind in {"hotel_search", "insurance", "museum", "transfer", "restaurant", "close"}:
            label = _distractor_observation(turn.kind) or trace.observation
            relation = f"NOTED_{turn.kind.upper()}"
            await self.memory.awrite(
                FactWrite(
                    passage=turn.user,
                    head="Itinerario",
                    head_type="Note",
                    relation=relation,
                    tail=label,
                    tail_type="Note",
                    schema_text=f"nota de itinerario {label}",
                    prompt_text=f"Itinerario {relation} {label}",
                    as_of=as_of,
                    category="declarative",
                )
            )


def _distractor_observation(kind: str) -> str:
    return {
        "hotel_search": "opciones Hotel Prado y Hotel Norte en el centro",
        "insurance": "seguro de cancelación cotizado",
        "museum": "entradas Prado y Reina Sofía",
        "transfer": "traslado Barajas al centro",
        "restaurant": "restaurante cercano sin cola",
        "close": "cierre de la reserva",
    }.get(kind, "")
