"""Association pure des prévisions météo à une réservation de golf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.reservation_parser import GolfReservation
from app.weather_client import EnvironmentCanadaForecast, HourlyForecastPeriod


ROUND_WEATHER_HOURS = 4
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")
_ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class DepartureWeather:
    """Prévisions quotidiennes et horaires utiles pendant une ronde."""

    departure_datetime: datetime
    daily_summary: str | None
    daily_temperature_high: float | None
    daily_temperature_low: float | None
    daily_precipitation_probability: int | None
    daily_icon_code: str | None
    hourly_detail_available: bool
    hourly_periods: tuple[HourlyForecastPeriod, ...]
    round_precipitation_probability_max: int | None
    round_temperature_min: float | None
    round_temperature_max: float | None
    round_wind_speed_max: float | None


def _maximum(values: list[int | float | None]) -> int | float | None:
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _minimum(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return min(available) if available else None


def build_departure_weather(
    reservation: GolfReservation,
    forecast: EnvironmentCanadaForecast,
) -> DepartureWeather:
    """Construit la météo d'une réservation sans effectuer d'entrée-sortie."""

    departure = datetime.combine(
        reservation.date,
        reservation.heure,
        tzinfo=LOCAL_TIMEZONE,
    )
    departure_date = departure.date()

    matching_daily = [
        period
        for period in forecast.daily
        if period.timestamp.astimezone(LOCAL_TIMEZONE).date() == departure_date
    ]
    daily_high = next(
        (period for period in matching_daily if period.temperature_class == "high"),
        None,
    )
    daily_low = next(
        (period for period in matching_daily if period.temperature_class == "low"),
        None,
    )

    round_end = departure + timedelta(hours=ROUND_WEATHER_HOURS)
    departure_utc = departure.astimezone(timezone.utc)
    round_end_utc = round_end.astimezone(timezone.utc)
    hourly = tuple(
        sorted(
            (
                period
                for period in forecast.hourly
                if period.timestamp.astimezone(timezone.utc) < round_end_utc
                and period.timestamp.astimezone(timezone.utc) + _ONE_HOUR
                > departure_utc
            ),
            key=lambda period: period.timestamp.astimezone(timezone.utc),
        )
    )

    coverage_cursor = departure_utc
    complete = True
    for period in hourly:
        slot_start = period.timestamp.astimezone(timezone.utc)
        slot_end = slot_start + _ONE_HOUR
        if slot_start > coverage_cursor:
            complete = False
            break
        if slot_end > coverage_cursor:
            coverage_cursor = slot_end
    hourly_detail_available = complete and coverage_cursor >= round_end_utc

    precipitation_max: int | None = None
    temperature_min: float | None = None
    temperature_max: float | None = None
    wind_speed_max: float | None = None
    if hourly_detail_available:
        precipitation_max = _maximum(
            [period.precipitation_probability for period in hourly]
        )  # type: ignore[assignment]
        temperature_min = _minimum([period.temperature for period in hourly])
        temperature_max = _maximum(
            [period.temperature for period in hourly]
        )  # type: ignore[assignment]
        wind_speed_max = _maximum(
            [period.wind_speed for period in hourly]
        )  # type: ignore[assignment]

    return DepartureWeather(
        departure_datetime=departure,
        daily_summary=daily_high.text_summary if daily_high else None,
        daily_temperature_high=daily_high.temperature if daily_high else None,
        daily_temperature_low=daily_low.temperature if daily_low else None,
        daily_precipitation_probability=(
            daily_high.precipitation_probability if daily_high else None
        ),
        daily_icon_code=daily_high.icon_code if daily_high else None,
        hourly_detail_available=hourly_detail_available,
        hourly_periods=hourly,
        round_precipitation_probability_max=precipitation_max,
        round_temperature_min=temperature_min,
        round_temperature_max=temperature_max,
        round_wind_speed_max=wind_speed_max,
    )
