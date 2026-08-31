"""Tests for display artifact orchestration."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app import reservation_cache, reservation_parser
from app.display_artifact import (
    LOCAL_TIMEZONE,
    DisplayArtifactResult,
    build_display_artifact,
    generate_display_artifact,
)
from app.display_service import DisplayDeparture
from app.display_targets.waveshare_75_bw import Waveshare75BWDisplayTarget
from app.weather_client import EnvironmentCanadaForecast, HomeAssistantWeatherConfig


class FakeDisplayTarget:
    """Minimal target that returns a deterministic payload."""

    def __init__(self, payload: bytes, *, file_extension: str = ".bin", name: str = "fake") -> None:
        self.name = name
        self.file_extension = file_extension
        self._payload = payload
        self.build_payload_calls = 0
        self.last_departure_count = 0

    def build_payload(self, departures: object) -> bytes:
        self.build_payload_calls += 1
        self.last_departure_count = len(tuple(departures))
        return self._payload


def _build_cache(reservations: list[reservation_parser.GolfReservation]) -> reservation_cache.ReservationCache:
    return reservation_cache.ReservationCache(
        version=reservation_cache.CURRENT_CACHE_VERSION,
        updated_at=datetime(2026, 8, 1, 8, 0),
        reservations=reservations,
    )


class DisplayArtifactTests(unittest.TestCase):
    def test_build_display_artifact_writes_payload_with_target_metadata(self) -> None:
        departures = (
            DisplayDeparture(
                reservation_id="R1",
                departure_datetime=datetime(2026, 8, 1, 8, 0),
                is_featured=True,
                title="Prochain départ : ...",
                players_line="",
                weather_mode="unavailable",
                daily_summary=None,
                hourly_items=(),
            ),
        )
        target = FakeDisplayTarget(b"hello", file_extension=".bin", name="fake_target")

        with tempfile.TemporaryDirectory() as tmp:
            result = build_display_artifact(
                departures,
                target=target,
                output_dir=tmp,
            )

            self.assertIsInstance(result, DisplayArtifactResult)
            self.assertEqual(result.profile_name, "fake_target")
            self.assertEqual(result.departures_count, 1)
            self.assertEqual(result.payload_size, 5)
            self.assertEqual(result.output_path.name, "departures_display.bin")
            self.assertEqual(result.output_path.read_bytes(), b"hello")
            self.assertEqual(target.build_payload_calls, 1)
            self.assertEqual(target.last_departure_count, 1)

    def test_build_display_artifact_uses_target_extension(self) -> None:
        target = FakeDisplayTarget(b"X", file_extension=".custom", name="fake")
        with tempfile.TemporaryDirectory() as tmp:
            result = build_display_artifact(
                (),
                target=target,
                output_dir=tmp,
            )
            self.assertEqual(result.output_path.name, "departures_display.custom")

    def test_build_display_artifact_creates_output_dir_and_replaces_existing_file(self) -> None:
        target = FakeDisplayTarget(b"new", file_extension=".bin")
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "nested" / "dir"
            output_path = output_dir / "departures_display.bin"
            output_dir.mkdir(parents=True)
            output_path.write_bytes(b"OLD")
            result = build_display_artifact(
                (),
                target=target,
                output_dir=output_dir,
            )
            self.assertTrue(output_dir.is_dir())
            self.assertEqual(output_path.read_bytes(), b"new")
            self.assertEqual(result.payload_size, 3)

    def test_generate_display_artifact_uses_limit_five(self) -> None:
        reservations = [
            reservation_parser.GolfReservation(
                date=datetime(2026, 8, 1).date(),
                heure=datetime(2026, 8, 1, 8).time(),
                joueurs=["Alice"],
                reservation_id=f"R{i}",
            )
            for i in range(8)
        ]

        observed_limits: dict[str, int | None] = {"value": None}

        def fake_filter_departures(reservations_input, *, now=None):
            return list(reservations_input)

        def fake_load_cache(cache_path):
            return _build_cache(reservations)

        def fake_load_weather_config():
            return HomeAssistantWeatherConfig(
                url="http://localhost",
                token="tok",
                entity_id="weather.test",
            )

        def fake_get_forecasts(config):
            return EnvironmentCanadaForecast(daily=(), hourly=())

        def fake_build_display_departures(
            reservations_input,
            forecast,
            *,
            limit: int,
        ) -> tuple[DisplayDeparture, ...]:
            observed_limits["value"] = limit
            return tuple(
                DisplayDeparture(
                    reservation_id=res.reservation_id,
                    departure_datetime=datetime(
                        res.date.year,
                        res.date.month,
                        res.date.day,
                        res.heure.hour,
                        res.heure.minute,
                    ),
                    is_featured=index == 0,
                    title=f"Dep {index}",
                    players_line="Alice",
                    weather_mode="unavailable",
                    daily_summary=None,
                    hourly_items=(),
                )
                for index, res in enumerate(reservations_input[:limit])
            )

        class TargetFake(FakeDisplayTarget):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            result = generate_display_artifact(
                output_dir=tmp,
                cache_path=Path(tmp) / "cache.json",
                now=datetime(2026, 8, 1, 8, 0, tzinfo=LOCAL_TIMEZONE),
                load_cache_fn=fake_load_cache,
                filter_departures_fn=fake_filter_departures,
                load_weather_config_fn=fake_load_weather_config,
                get_forecasts_fn=fake_get_forecasts,
                build_display_departures_fn=fake_build_display_departures,
                get_display_target_fn=lambda _: TargetFake(b"X", file_extension=".bin"),
            )

            self.assertEqual(observed_limits["value"], 5)
            self.assertEqual(result.departures_count, 5)

    def test_generate_display_artifact_explicit_profile_is_forwarded(self) -> None:
        target = FakeDisplayTarget(b"raw", file_extension=".raw")

        with tempfile.TemporaryDirectory() as tmp:
            def fake_load_cache(cache_path):
                return _build_cache(
                    [
                        reservation_parser.GolfReservation(
                            date=datetime(2026, 8, 1).date(),
                            heure=datetime(2026, 8, 1, 8).time(),
                            joueurs=["Alice"],
                            reservation_id="R1",
                        )
                    ]
                )

            selected = {"value": None}

            generate_display_artifact(
                output_dir=tmp,
                cache_path=Path(tmp) / "cache.json",
                profile_name="explicit_profile",
                load_cache_fn=fake_load_cache,
                filter_departures_fn=lambda reservations, *, now: list(reservations),
                load_weather_config_fn=lambda: HomeAssistantWeatherConfig(
                    url="http://localhost",
                    token="tok",
                    entity_id="weather.test",
                ),
                get_forecasts_fn=lambda config: EnvironmentCanadaForecast(daily=(), hourly=()),
                build_display_departures_fn=lambda reservations, forecast, *, limit: (),
                get_display_target_fn=lambda profile_name: selected.__setitem__("value", profile_name) or target,
            )

            self.assertEqual(selected["value"], "explicit_profile")
            self.assertEqual(target.build_payload_calls, 1)

    def test_generate_display_artifact_error_if_cache_missing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "introuvable"):
            generate_display_artifact(
                cache_path=Path("/tmp/does_not_exist.json"),
                load_cache_fn=lambda cache_path: None,
            )

    def test_waveshare_target_produces_800x480_payload_size(self) -> None:
        from app.display_service import build_display_departures

        reservations = (
            reservation_parser.GolfReservation(
                date=datetime(2026, 8, 29).date(),
                heure=datetime(2026, 8, 29, 8, 0).time(),
                joueurs=["Alice", "Bob"],
                reservation_id="R1",
            ),
            reservation_parser.GolfReservation(
                date=datetime(2026, 8, 29).date(),
                heure=datetime(2026, 8, 29, 8, 30).time(),
                joueurs=["Chloe"],
                reservation_id="R2",
            ),
        )
        display_departures = build_display_departures(
            reservations,
            EnvironmentCanadaForecast(daily=(), hourly=()),
            limit=5,
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = build_display_artifact(
                display_departures,
                target=Waveshare75BWDisplayTarget(),
                output_dir=tmp,
            )
            self.assertEqual(result.payload_size, 48_000)
            self.assertEqual(len(result.output_path.read_bytes()), 48_000)


if __name__ == "__main__":
    unittest.main()
