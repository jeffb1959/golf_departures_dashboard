"""Tests de la couche de présentation des départs de golf."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
import unittest

from app.display_service import WEEKDAY_LABELS, MONTH_LABELS, HourlyDisplayItem, build_display_departures
from app.golf_weather_service import ROUND_WEATHER_HOURS
from app.reservation_parser import GolfReservation
from app.weather_client import DailyForecastPeriod, EnvironmentCanadaForecast, HourlyForecastPeriod


TORONTO = ZoneInfo("America/Toronto")


def make_reservation(
    reservation_id: str,
    day: date,
    hour: int,
    minute: int = 0,
    players: tuple[str, ...] = ("Joueur 1", "Joueur 2"),
) -> GolfReservation:
    return GolfReservation(
        date=day,
        heure=time(hour, minute),
        joueurs=list(players),
        reservation_id=reservation_id,
    )


def make_daily(timestamp: datetime, summary: str) -> DailyForecastPeriod:
    return DailyForecastPeriod(
        timestamp=timestamp,
        period="high",
        text_summary=summary,
        temperature=18.0,
        temperature_class="high",
        precipitation_probability=30,
        icon_code="01",
    )


def make_hourly(
    timestamp: datetime,
    *,
    condition: str = "Nuageux",
    temperature: float | None = 10.0,
    precipitation_probability: int | None = 10,
    wind_speed: float | None = 12.0,
    wind_direction: str | None = "NO",
    icon_code: str | None = "02",
) -> HourlyForecastPeriod:
    return HourlyForecastPeriod(
        timestamp=timestamp,
        condition=condition,
        temperature=temperature,
        precipitation_probability=precipitation_probability,
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        uv_index=None,
        icon_code=icon_code,
    )


def make_forecast(
    *, daily: tuple[DailyForecastPeriod, ...] = (), hourly: tuple[HourlyForecastPeriod, ...] = ()
) -> EnvironmentCanadaForecast:
    return EnvironmentCanadaForecast(list(daily), list(hourly))


class BuildDisplayDepartureTests(unittest.TestCase):
    def test_no_reservations_returns_empty_tuple(self):
        self.assertEqual(build_display_departures((), make_forecast()), ())

    def test_sort_by_datetime_and_default_limit_is_6(self):
        source = [
            make_reservation("R1", date(2026, 8, 30), 8),
            make_reservation("R2", date(2026, 8, 29), 12),
            make_reservation("R3", date(2026, 8, 29), 7),
            make_reservation("R4", date(2026, 8, 29), 18),
            make_reservation("R5", date(2026, 8, 31), 9),
            make_reservation("R6", date(2026, 9, 1), 14),
            make_reservation("R7", date(2026, 9, 1), 8),
        ]
        result = build_display_departures(source, make_forecast())
        self.assertEqual([item.reservation_id for item in result], ["R3", "R2", "R4", "R1", "R5", "R7"])
        self.assertEqual(len(result), 6)

    def test_limit_parameter(self):
        source = tuple(make_reservation(f"R{i}", date(2026, 8, 29), 8 + i) for i in range(6))
        result = build_display_departures(source, make_forecast(), limit=4)
        self.assertEqual(len(result), 4)

    def test_limit_less_than_one_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_display_departures((make_reservation("R1", date(2026, 8, 29), 8),), make_forecast(), limit=0)

    def test_featured_first_only(self):
        result = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 9),
                make_reservation("R2", date(2026, 8, 29), 10),
            ),
            make_forecast(),
        )
        self.assertTrue(result[0].is_featured)
        self.assertFalse(result[1].is_featured)

    def test_featured_title_format(self):
        item = build_display_departures(
            (make_reservation("R1", date(2026, 8, 29), 10, 27),),
            make_forecast(),
        )[0]
        self.assertEqual(item.title, "Prochain départ : Samedi 29 août 10:27 hrs")

    def test_title_without_featured_prefix(self):
        item = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 9),
                make_reservation("R2", date(2026, 8, 31), 8, 21),
            ),
            make_forecast(),
        )[1]
        self.assertEqual(item.title, "Lundi 31 août 8:21 hrs")

    def test_hour_8_03_has_no_leading_zero(self):
        item = build_display_departures(
            (make_reservation("R1", date(2026, 8, 29), 8, 3),),
            make_forecast(),
        )[0]
        self.assertEqual(item.title, "Prochain départ : Samedi 29 août 8:03 hrs")

    def test_french_weekdays(self):
        expected = [day.capitalize() for day in WEEKDAY_LABELS]
        day_of_week_start = date(2026, 8, 24)  # lundi
        items = build_display_departures(
            tuple(
                make_reservation(f"R{i}", day_of_week_start.fromordinal(day_of_week_start.toordinal() + i), 8)
                for i in range(7)
            ),
            make_forecast(),
        )
        for item in items:
            title = item.title.replace("Prochain départ : ", "")
            self.assertIn(title.split(" ")[0], expected)

    def test_french_months_with_accents(self):
        item = build_display_departures(
            (
                make_reservation("R1", date(2026, 2, 1), 8),
                make_reservation("R2", date(2026, 8, 1), 8),
            ),
            make_forecast(),
        )[0]
        self.assertIn("février", item.title)

    def test_players_join_with_comma_space(self):
        item = build_display_departures(
            (
                make_reservation(
                    "R1",
                    date(2026, 8, 29),
                    8,
                    players=("Jean Francois Bouchard", "Jean Pierre Lagacé"),
                ),
            ),
            make_forecast(),
        )[0]
        self.assertEqual(
            item.players_line,
            "Jean Francois Bouchard, Jean Pierre Lagacé",
        )

    def test_input_list_is_not_modified(self):
        source = [
            make_reservation("R1", date(2026, 8, 29), 9),
            make_reservation("R2", date(2026, 8, 30), 10),
        ]
        copy = tuple(source)
        build_display_departures(source, make_forecast())
        self.assertEqual(tuple(source), copy)


class WeatherDisplayTests(unittest.TestCase):
    def test_first_with_complete_hourly_detail_is_hourly_mode(self):
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
                make_reservation("R2", date(2026, 8, 29), 10),
            ),
            make_forecast(
                daily=(
                    make_daily(
                        datetime(2026, 8, 29, 6, tzinfo=TORONTO),
                        summary="Aperçu de la journée.",
                    ),
                ),
                hourly=(
                    make_hourly(datetime(2026, 8, 29, 8, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 9, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 10, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 11, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 12, tzinfo=TORONTO)),
                ),
            ),
        )
        self.assertEqual(display[0].weather_mode, "hourly")

    def test_first_hourly_mode_converts_selected_periods(self):
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
            ),
            make_forecast(
                daily=(
                    make_daily(
                        datetime(2026, 8, 29, 6, tzinfo=TORONTO),
                        summary="Aperçu de la journée.",
                    ),
                ),
                hourly=(
                    make_hourly(
                        datetime(2026, 8, 29, 8, tzinfo=TORONTO),
                        condition="Nuageux",
                        temperature=0.0,
                        precipitation_probability=0,
                        wind_speed=5.0,
                        wind_direction="SO",
                        icon_code="03",
                    ),
                    make_hourly(
                        datetime(2026, 8, 29, 9, tzinfo=TORONTO),
                        condition="Éclaircie",
                        temperature=1.0,
                        precipitation_probability=50,
                        wind_speed=6.0,
                        wind_direction="SO",
                        icon_code="04",
                    ),
                    make_hourly(datetime(2026, 8, 29, 10, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 11, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 12, tzinfo=TORONTO)),
                ),
            ),
        )
        expected_time_labels = ("8h", "9h", "10h", "11h", "12h")
        items = display[0].hourly_items
        self.assertTrue(all(isinstance(item, HourlyDisplayItem) for item in items))
        self.assertEqual(tuple(item.time_label for item in items), expected_time_labels)
        self.assertEqual(items[0].condition, "Nuageux")
        self.assertEqual(items[0].temperature, 0.0)
        self.assertEqual(items[0].precipitation_probability, 0)
        self.assertEqual(items[0].wind_speed, 5.0)
        self.assertEqual(items[0].wind_direction, "SO")
        self.assertEqual(items[0].icon_code, "03")
        self.assertEqual(items[1].condition, "Éclaircie")
        self.assertEqual(items[1].icon_code, "04")

    def test_first_hourly_items_time_labels_are_in_toronto(self):
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
            ),
            make_forecast(
                hourly=(
                    make_hourly(datetime(2026, 8, 29, 12, tzinfo=timezone.utc)),
                    make_hourly(datetime(2026, 8, 29, 13, tzinfo=timezone.utc)),
                    make_hourly(datetime(2026, 8, 29, 14, tzinfo=timezone.utc)),
                    make_hourly(datetime(2026, 8, 29, 15, tzinfo=timezone.utc)),
                    make_hourly(datetime(2026, 8, 29, 16, tzinfo=timezone.utc)),
                ),
                daily=(make_daily(datetime(2026, 8, 29, 6, tzinfo=TORONTO), summary="Aperçu."),),
            ),
        )
        self.assertEqual(display[0].hourly_items[0].time_label, "8h")
        self.assertEqual(display[0].hourly_items[1].time_label, "9h")

    def test_first_hourly_incomplete_has_no_hourly_items_and_daily_mode(self):
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
            ),
            make_forecast(
                daily=(make_daily(datetime(2026, 8, 29, 6, tzinfo=TORONTO), summary="Aperçu."),),
                hourly=(
                    make_hourly(datetime(2026, 8, 29, 9, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 10, tzinfo=TORONTO)),
                ),
            ),
        )
        self.assertEqual(display[0].weather_mode, "daily")
        self.assertEqual(display[0].hourly_items, ())

    def test_first_incomplete_without_daily_is_unavailable(self):
        display = build_display_departures(
            (make_reservation("R1", date(2026, 8, 29), 8, 30),),
            make_forecast(hourly=(make_hourly(datetime(2026, 8, 29, 9, tzinfo=TORONTO)),)),
        )[0]
        self.assertEqual(display.weather_mode, "unavailable")
        self.assertEqual(display.hourly_items, ())

    def test_second_never_shows_hourly_even_if_available(self):
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
                make_reservation("R2", date(2026, 8, 29), 10),
            ),
            make_forecast(
                daily=(make_daily(datetime(2026, 8, 29, 6, tzinfo=TORONTO), summary="Aperçu."),),
                hourly=(
                    make_hourly(datetime(2026, 8, 29, 8, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 9, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 10, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 11, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 12, tzinfo=TORONTO)),
                ),
            ),
        )
        self.assertEqual(display[1].weather_mode, "daily")
        self.assertEqual(display[1].hourly_items, ())

    def test_second_keeps_exact_daily_summary(self):
        summary = "Vent, UV, brouillard et humidex précisés dans le détail."
        display = build_display_departures(
            (
                make_reservation("R1", date(2026, 8, 29), 8, 30),
                make_reservation("R2", date(2026, 8, 29), 10, 30),
            ),
            make_forecast(
                daily=(
                    make_daily(datetime(2026, 8, 29, 6, tzinfo=TORONTO), summary=summary),
                    make_daily(datetime(2026, 8, 30, 6, tzinfo=TORONTO), summary="Aperçu 30"),
                ),
                hourly=(
                    make_hourly(datetime(2026, 8, 29, 8, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 9, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 10, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 11, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 29, 12, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 30, 8, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 30, 9, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 30, 10, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 30, 11, tzinfo=TORONTO)),
                    make_hourly(datetime(2026, 8, 30, 12, tzinfo=TORONTO)),
                ),
            ),
        )
        self.assertEqual(display[1].weather_mode, "daily")
        self.assertEqual(display[1].daily_summary, summary)


if __name__ == "__main__":
    unittest.main()
