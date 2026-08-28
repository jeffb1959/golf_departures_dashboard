"""Tests de la couche métier associant météo et départ de golf."""

from datetime import date, datetime, time, timezone
import unittest
from zoneinfo import ZoneInfo

from app.golf_weather_service import ROUND_WEATHER_HOURS, build_departure_weather
from app.reservation_parser import GolfReservation
from app.weather_client import (
    DailyForecastPeriod,
    EnvironmentCanadaForecast,
    HourlyForecastPeriod,
)


TORONTO = ZoneInfo("America/Toronto")


def reservation(day=date(2026, 7, 18), at=time(8)):
    return GolfReservation(day, at, ["Joueur Test"], "TEST-1")


def daily(timestamp, temperature_class, temperature, *, summary="Beau temps"):
    return DailyForecastPeriod(
        timestamp, "période fictive", summary, temperature, temperature_class, 30, "01"
    )


def hourly(
    hour,
    *,
    day=date(2026, 7, 18),
    minute=0,
    tz=TORONTO,
    temperature=20.0,
    precipitation=10,
    wind=12.0,
    fold=0,
):
    return HourlyForecastPeriod(
        datetime.combine(day, time(hour, minute, fold=fold), tzinfo=tz),
        "sunny",
        temperature,
        precipitation,
        wind,
        "N",
        3.0,
        "01",
    )


def forecast(*, daily_periods=(), hourly_periods=()):
    return EnvironmentCanadaForecast(list(daily_periods), list(hourly_periods))


class DailySelectionTests(unittest.TestCase):
    def test_selects_high_fields_and_independent_low_for_departure_date(self):
        result = build_departure_weather(
            reservation(),
            forecast(
                daily_periods=(
                    daily(datetime(2026, 7, 18, 6, tzinfo=TORONTO), "low", 12),
                    daily(
                        datetime(2026, 7, 18, 7, tzinfo=TORONTO),
                        "high",
                        25,
                        summary="Ensoleillé avec passages nuageux",
                    ),
                )
            ),
        )
        self.assertEqual(result.daily_summary, "Ensoleillé avec passages nuageux")
        self.assertEqual(result.daily_temperature_high, 25)
        self.assertEqual(result.daily_temperature_low, 12)
        self.assertEqual(result.daily_precipitation_probability, 30)
        self.assertEqual(result.daily_icon_code, "01")

    def test_compares_daily_date_after_conversion_to_toronto(self):
        period = daily(datetime(2026, 7, 19, 2, tzinfo=timezone.utc), "high", 23)
        result = build_departure_weather(reservation(), forecast(daily_periods=(period,)))
        self.assertEqual(result.daily_temperature_high, 23)

    def test_missing_high_leaves_high_fields_empty_but_keeps_low(self):
        low = daily(datetime(2026, 7, 18, 6, tzinfo=TORONTO), "low", 11)
        result = build_departure_weather(reservation(), forecast(daily_periods=(low,)))
        self.assertIsNone(result.daily_summary)
        self.assertIsNone(result.daily_temperature_high)
        self.assertIsNone(result.daily_precipitation_probability)
        self.assertIsNone(result.daily_icon_code)
        self.assertEqual(result.daily_temperature_low, 11)


class HourlySelectionTests(unittest.TestCase):
    def test_exact_hour_selects_four_slots(self):
        periods = [hourly(value) for value in range(7, 14)]
        result = build_departure_weather(
            reservation(at=time(8)), forecast(hourly_periods=periods)
        )
        self.assertEqual([item.timestamp.hour for item in result.hourly_periods], [8, 9, 10, 11])
        self.assertTrue(result.hourly_detail_available)

    def test_non_round_departure_selects_all_five_overlapping_slots(self):
        periods = [hourly(value) for value in range(7, 14)]
        result = build_departure_weather(
            reservation(at=time(8, 42)), forecast(hourly_periods=periods)
        )
        self.assertEqual(
            [item.timestamp.hour for item in result.hourly_periods], [8, 9, 10, 11, 12]
        )
        self.assertTrue(result.hourly_detail_available)

    def test_sorts_input_and_excludes_slots_outside_round(self):
        periods = [hourly(value) for value in (13, 11, 8, 7, 12, 10, 9)]
        result = build_departure_weather(
            reservation(at=time(8, 42)), forecast(hourly_periods=periods)
        )
        self.assertEqual(
            [item.timestamp.hour for item in result.hourly_periods], [8, 9, 10, 11, 12]
        )

    def test_missing_first_slot_makes_coverage_incomplete(self):
        result = build_departure_weather(
            reservation(at=time(8, 42)),
            forecast(hourly_periods=[hourly(value) for value in range(9, 13)]),
        )
        self.assertFalse(result.hourly_detail_available)

    def test_missing_last_slot_makes_coverage_incomplete(self):
        result = build_departure_weather(
            reservation(at=time(8, 42)),
            forecast(hourly_periods=[hourly(value) for value in range(8, 12)]),
        )
        self.assertFalse(result.hourly_detail_available)

    def test_middle_gap_makes_coverage_incomplete(self):
        result = build_departure_weather(
            reservation(at=time(8, 42)),
            forecast(hourly_periods=[hourly(value) for value in (8, 9, 11, 12)]),
        )
        self.assertFalse(result.hourly_detail_available)


class HourlyAggregateTests(unittest.TestCase):
    def test_aggregates_values_while_ignoring_none_and_preserving_zero(self):
        periods = [
            hourly(8, temperature=None, precipitation=0, wind=None),
            hourly(9, temperature=17, precipitation=None, wind=9),
            hourly(10, temperature=24, precipitation=65, wind=22),
            hourly(11, temperature=20, precipitation=15, wind=14),
        ]
        result = build_departure_weather(reservation(), forecast(hourly_periods=periods))
        self.assertEqual(result.round_precipitation_probability_max, 65)
        self.assertEqual(result.round_temperature_min, 17)
        self.assertEqual(result.round_temperature_max, 24)
        self.assertEqual(result.round_wind_speed_max, 22)

    def test_zero_precipitation_is_not_treated_as_missing(self):
        periods = [hourly(value, precipitation=0) for value in range(8, 12)]
        result = build_departure_weather(reservation(), forecast(hourly_periods=periods))
        self.assertEqual(result.round_precipitation_probability_max, 0)

    def test_all_none_produces_none_aggregates(self):
        periods = [
            hourly(value, temperature=None, precipitation=None, wind=None)
            for value in range(8, 12)
        ]
        result = build_departure_weather(reservation(), forecast(hourly_periods=periods))
        self.assertIsNone(result.round_precipitation_probability_max)
        self.assertIsNone(result.round_temperature_min)
        self.assertIsNone(result.round_temperature_max)
        self.assertIsNone(result.round_wind_speed_max)

    def test_incomplete_coverage_suppresses_every_aggregate(self):
        periods = [hourly(8, precipitation=80), hourly(10, temperature=30), hourly(11, wind=40)]
        result = build_departure_weather(reservation(), forecast(hourly_periods=periods))
        self.assertFalse(result.hourly_detail_available)
        self.assertEqual(
            (
                result.round_precipitation_probability_max,
                result.round_temperature_min,
                result.round_temperature_max,
                result.round_wind_speed_max,
            ),
            (None, None, None, None),
        )


class TimezoneTests(unittest.TestCase):
    def test_departure_is_explicitly_aware_in_toronto(self):
        result = build_departure_weather(reservation(), forecast())
        self.assertEqual(result.departure_datetime.tzinfo, TORONTO)
        self.assertEqual(ROUND_WEATHER_HOURS, 4)

    def test_fall_dst_repeated_hour_is_compared_as_aware_instants(self):
        day = date(2026, 11, 1)
        periods = [
            hourly(0, day=day),
            hourly(1, day=day, fold=0),
            hourly(1, day=day, fold=1),
            hourly(2, day=day),
            hourly(3, day=day),
            hourly(4, day=day),
        ]
        result = build_departure_weather(
            reservation(day=day, at=time(0, 30)), forecast(hourly_periods=periods)
        )
        self.assertTrue(result.hourly_detail_available)
        self.assertEqual(len(result.hourly_periods), 6)


if __name__ == "__main__":
    unittest.main()
