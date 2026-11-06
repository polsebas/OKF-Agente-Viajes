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
    def __init__(self) -> None:
        self.quote_issued_at: datetime | None = None

    def book_hotel(self, name: str) -> str:
        if name == HOTEL_NORTE:
            raise BookingConflict(
                HOTEL_NORTE,
                409,
                "Conflict: sin cupo en Hotel Norte",
            )
        return f"reserva confirmada en {name}"

    def quote_flight(self, as_of: datetime) -> int:
        if self.quote_issued_at is None:
            self.quote_issued_at = as_of
        expiry = self.quote_issued_at + timedelta(seconds=FARE_TTL_SECONDS)
        if as_of >= expiry:
            return LIVE_FARE_USD
        return STALE_FARE_USD
