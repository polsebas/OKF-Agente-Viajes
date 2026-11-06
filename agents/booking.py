"""Herramientas deterministas de reserva.

El cupo de Hotel Norte responde HTTP 409. La tarifa aérea cambia cuando se
vence ``FARE_TTL_SECONDS``: la fuente de verdad es esta función, no el recuerdo.
"""

from __future__ import annotations

from datetime import datetime, timedelta


class BookingConflict(Exception):
    def __init__(self, resource: str, status: int, detail: str) -> None:
        self.resource = resource
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status} {detail}")


HOTEL_NORTE = "Hotel Norte"
HOTEL_PRADO = "Hotel Prado"
MIAMI_ROUTE = "EZE-MIA-MAD"
SAFE_ROUTE = "EZE-GRU-MAD"
STALE_FARE_USD = 890
LIVE_FARE_USD = 1120
FARE_TTL_SECONDS = 3600
BUDGET_USD = "3500 USD"


class BookingDesk:
    """Inventario chico. Hotel Norte abre sin cupo: el 409 es la respuesta del escritorio."""

    def __init__(self) -> None:
        self.quote_issued_at: datetime | None = None
        self.inventory = {HOTEL_NORTE: 0, HOTEL_PRADO: 5}
        self.attempts: list[str] = []

    def has_room(self, name: str) -> bool:
        return self.inventory.get(name, 0) > 0

    def alternative_to(self, name: str) -> str | None:
        for candidate, rooms in self.inventory.items():
            if candidate != name and rooms > 0:
                return candidate
        return None

    def book_hotel(self, name: str) -> str:
        self.attempts.append(name)
        if not self.has_room(name):
            raise BookingConflict(
                name,
                409,
                f"Conflict: sin cupo en {name}",
            )
        self.inventory[name] -= 1
        return f"reserva confirmada en {name}"

    def quote_flight(self, as_of: datetime) -> int:
        if self.quote_issued_at is None:
            self.quote_issued_at = as_of
        expiry = self.quote_issued_at + timedelta(seconds=FARE_TTL_SECONDS)
        if as_of >= expiry:
            return LIVE_FARE_USD
        return STALE_FARE_USD
