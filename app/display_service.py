"""Couche de présentation pour préparer les départs de golf et leur météo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Iterable, Literal

from app.golf_weather_service import DepartureWeather, build_departure_weather
from app.reservation_parser import GolfReservation
from app.weather_client import EnvironmentCanadaForecast

LOCAL_TIMEZONE = ZoneInfo("America/Toronto")

WEEKDAY_LABELS = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)

MONTH_LABELS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


@dataclass(frozen=True)
class HourlyDisplayItem:
    """Élément météo heure par heure prêt pour affichage texte."""

    time_label: str
    condition: str
    temperature: float | None
    precipitation_probability: int | None
    wind_speed: float | None
    wind_direction: str | None
    icon_code: str | None


@dataclass(frozen=True)
class DisplayDeparture:
    """Modèle d’affichage pour un départ de golf."""

    reservation_id: str
    departure_datetime: datetime
    is_featured: bool
    title: str
    players_line: str
    weather_mode: Literal["hourly", "daily", "unavailable"]
    daily_summary: str | None
    hourly_items: tuple[HourlyDisplayItem, ...]


def _to_hourly_display_items(weather: DepartureWeather) -> tuple[HourlyDisplayItem, ...]:
    items: list[HourlyDisplayItem] = []
    for period in weather.hourly_periods:
        local_timestamp = period.timestamp.astimezone(LOCAL_TIMEZONE)
        time_label = f"{local_timestamp.hour}h"
        items.append(
            HourlyDisplayItem(
                time_label=time_label,
                condition=period.condition,
                temperature=period.temperature,
                precipitation_probability=period.precipitation_probability,
                wind_speed=period.wind_speed,
                wind_direction=period.wind_direction,
                icon_code=period.icon_code,
            )
        )
    return tuple(items)


def _to_display_title(departure: datetime, *, featured_label: bool) -> str:
    weekday = WEEKDAY_LABELS[departure.weekday()].capitalize()
    month = MONTH_LABELS[departure.month - 1]
    time_text = f"{departure.hour}:{departure.minute:02d} hrs"
    title_body = f"{weekday} {departure.day} {month} {time_text}"
    if featured_label:
        return f"Prochain départ : {title_body}"
    return title_body


def _sorted_departures(reservations: Iterable[GolfReservation]) -> list[GolfReservation]:
    return sorted(
        reservations,
        key=lambda reservation: datetime.combine(
            reservation.date,
            reservation.heure,
            tzinfo=LOCAL_TIMEZONE,
        ),
    )


def build_display_departures(
    reservations: Iterable[GolfReservation],
    forecast: EnvironmentCanadaForecast,
    *,
    limit: int = 6,
) -> tuple[DisplayDeparture, ...]:
    """Transforme les départs pertinents en blocs d’affichage directement exploitables."""

    if limit < 1:
        raise ValueError("limit doit être supérieur ou égal à 1.")

    sorted_reservations = _sorted_departures(reservations)
    limited_reservations = sorted_reservations[:limit]

    display_departures: list[DisplayDeparture] = []
    for index, reservation in enumerate(limited_reservations):
        departure = datetime.combine(
            reservation.date,
            reservation.heure,
            tzinfo=LOCAL_TIMEZONE,
        )
        is_featured = index == 0
        weather = build_departure_weather(reservation, forecast)
        daily_summary = weather.daily_summary.strip() if weather.daily_summary else None

        if is_featured and weather.hourly_detail_available:
            weather_mode: Literal["hourly", "daily", "unavailable"] = "hourly"
            hourly_items = _to_hourly_display_items(weather)
        else:
            hourly_items = ()
            if weather.daily_summary:
                weather_mode = "daily"
            else:
                weather_mode = "unavailable"

        display_departures.append(
            DisplayDeparture(
                reservation_id=reservation.reservation_id,
                departure_datetime=departure,
                is_featured=is_featured,
                title=_to_display_title(
                    departure,
                    featured_label=is_featured,
                ),
                players_line=", ".join(reservation.joueurs),
                weather_mode=weather_mode,
                daily_summary=daily_summary,
                hourly_items=hourly_items,
            )
        )

    return tuple(display_departures)
