"""Tests de l'orchestration de rafraîchissement complet du dashboard."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import unittest

from app.dashboard_refresh import (
    DashboardRefreshError,
    DashboardRefreshResult,
    LOCAL_TIMEZONE,
    refresh_dashboard,
)
from app.reservation_refresh import ReservationRefreshResult
from app.display_artifact import DisplayArtifactResult


class DummyReservationRefreshResult:
    """Objet minimal compatible."""

    def __init__(self, count: int, updated_at: datetime) -> None:
        self.reservations_count = count
        self.updated_at = updated_at


class DummyDisplayArtifactResult:
    """Objet minimal compatible."""

    def __init__(self, profile: str, payload_size: int, departures_count: int, generated_at: datetime) -> None:
        self.profile_name = profile
        self.payload_size = payload_size
        self.departures_count = departures_count
        self.generated_at = generated_at


class DashboardRefreshTests(unittest.TestCase):
    def test_refresh_dashboard_calls_refresh_then_display_with_same_reference_time(self) -> None:
        now = datetime(2026, 8, 31, 17, 0, tzinfo=LOCAL_TIMEZONE)
        calls: list[str] = []

        def fake_refresh_reservations(*, now: datetime):
            calls.append(f"reservations:{now.isoformat()}")
            return DummyReservationRefreshResult(2, now)

        def fake_generate_display(*, now: datetime):
            calls.append(f"display:{now.isoformat()}")
            return DummyDisplayArtifactResult(
                profile="waveshare_75_bw",
                payload_size=48000,
                departures_count=2,
                generated_at=now,
            )

        result = refresh_dashboard(
            now=now,
            refresh_reservations_fn=fake_refresh_reservations,
            generate_display_fn=fake_generate_display,
        )

        self.assertEqual(
            result,
            DashboardRefreshResult(
                reservations_count=2,
                reservations_updated_at=now,
                display_profile="waveshare_75_bw",
                display_payload_size=48000,
                display_departures_count=2,
                display_generated_at=now,
            ),
        )
        self.assertEqual(calls, [f"reservations:{now.isoformat()}", f"display:{now.isoformat()}"])

    def test_refresh_dashboard_uses_default_timezone_for_reference_now(self) -> None:
        seen: dict[str, datetime | None] = {"reservation_now": None, "display_now": None}

        def fake_refresh_reservations(now: datetime):
            seen["reservation_now"] = now
            return DummyReservationRefreshResult(0, now)

        def fake_generate_display(*, now: datetime):
            seen["display_now"] = now
            return DummyDisplayArtifactResult(
                profile="waveshare_75_bw",
                payload_size=0,
                departures_count=0,
                generated_at=now,
            )

        result = refresh_dashboard(
            refresh_reservations_fn=fake_refresh_reservations,
            generate_display_fn=fake_generate_display,
        )
        self.assertEqual(seen["reservation_now"], seen["display_now"])
        self.assertIsNotNone(seen["reservation_now"])
        assert seen["reservation_now"] is not None
        self.assertEqual(seen["reservation_now"].tzinfo, ZoneInfo("America/Toronto"))

        self.assertEqual(result.reservations_updated_at, seen["reservation_now"])
        self.assertEqual(result.display_generated_at, seen["display_now"])

    def test_refresh_dashboard_fails_on_reservations_error_with_stage(self) -> None:
        def fake_refresh_reservations(*, now: datetime):
            raise RuntimeError("imap")

        called = {"display": False}

        def fake_generate_display(*, now: datetime):
            called["display"] = True
            return DummyDisplayArtifactResult(
                profile="waveshare_75_bw",
                payload_size=0,
                departures_count=0,
                generated_at=datetime(2026, 8, 31, 17, 0, tzinfo=ZoneInfo("America/Toronto")),
            )

        with self.assertRaisesRegex(DashboardRefreshError, "reservations") as context:
            refresh_dashboard(
                now=datetime(2026, 8, 31, 17, 0, tzinfo=ZoneInfo("America/Toronto")),
                refresh_reservations_fn=fake_refresh_reservations,
                generate_display_fn=fake_generate_display,
            )
        self.assertEqual(context.exception.stage, "reservations")
        self.assertFalse(called["display"])

    def test_refresh_dashboard_fails_on_display_error_with_stage(self) -> None:
        now = datetime(2026, 8, 31, 17, 0, tzinfo=ZoneInfo("America/Toronto"))

        def fake_refresh_reservations(*, now: datetime):
            return DummyReservationRefreshResult(2, now)

        def fake_generate_display(*, now: datetime):
            raise RuntimeError("artifact")

        with self.assertRaisesRegex(DashboardRefreshError, "display") as context:
            refresh_dashboard(
                now=now,
                refresh_reservations_fn=fake_refresh_reservations,
                generate_display_fn=fake_generate_display,
            )
        self.assertEqual(context.exception.stage, "display")


if __name__ == "__main__":
    unittest.main()
