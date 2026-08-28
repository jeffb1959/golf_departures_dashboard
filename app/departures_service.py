"""Règles métier pour déterminer les départs pertinents à afficher."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from app.reservation_parser import GolfReservation


DEPARTURE_RELEVANCE_HOURS = 5


def filter_relevant_departures(
    reservations: Iterable[GolfReservation],
    *,
    now: datetime | None = None,
) -> list[GolfReservation]:
    """Retourne les départs dont la période de pertinence n'est pas terminée."""

    current_time = now if now is not None else datetime.now()
    relevance_duration = timedelta(hours=DEPARTURE_RELEVANCE_HOURS)

    relevant = []
    for reservation in reservations:
        departure_time = datetime.combine(
            reservation.date,
            reservation.heure,
            tzinfo=current_time.tzinfo,
        )
        if current_time < departure_time + relevance_duration:
            relevant.append(reservation)

    return sorted(relevant, key=lambda reservation: (reservation.date, reservation.heure))
