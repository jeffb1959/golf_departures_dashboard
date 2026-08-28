"""Tests unitaires de l'orchestration du rafraîchissement."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, time
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import reservation_cache, reservation_parser, reservation_refresh
from app.chronogolf_client import ChronogolfIMAPError, ImapConfig


FAKE_PASSWORD = "mot-de-passe-fictif"


def sample_reservation(reservation_id: str) -> reservation_parser.GolfReservation:
    return reservation_parser.GolfReservation(
        date=date(2026, 8, 18),
        heure=time(8, 57),
        joueurs=["Alice Exemple", "Bob Exemple"],
        reservation_id=reservation_id,
    )


def fake_config() -> ImapConfig:
    return ImapConfig(
        host="imap.exemple.test",
        port=993,
        user="utilisateur@exemple.test",
        password=FAKE_PASSWORD,
    )


class FakeClient:
    def __init__(self, reservations: list[reservation_parser.GolfReservation]) -> None:
        self.reservations = reservations
        self.calls: list[tuple[datetime, date]] = []

    def get_upcoming_reservations(
        self, *, reference: datetime, today: date
    ) -> list[reservation_parser.GolfReservation]:
        self.calls.append((reference, today))
        return self.reservations


class FailingClient:
    def __init__(self, _config: ImapConfig) -> None:
        pass

    def get_upcoming_reservations(self, **_kwargs: object) -> list:
        raise ChronogolfIMAPError("Erreur réseau fictive")


class ReservationRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.cache_path = Path(self.temporary_directory.name) / "reservation_cache.json"
        self.now = datetime(2026, 8, 14, 22, 30, 0)

    def test_refresh_with_reservations_writes_cache(self) -> None:
        expected = sample_reservation("ID-FICTIF-1")
        client = FakeClient([expected])

        result = reservation_refresh.refresh_reservation_cache(
            now=self.now,
            cache_path=self.cache_path,
            client_factory=lambda _config: client,
            config=fake_config(),
        )

        loaded = reservation_cache.load_reservations_cache(cache_path=self.cache_path)
        self.assertEqual(loaded.reservations, [expected])
        self.assertEqual(client.calls, [(self.now, self.now.date())])
        self.assertEqual(result.reservations_count, 1)

    def test_refresh_with_empty_list_writes_empty_cache(self) -> None:
        result = reservation_refresh.refresh_reservation_cache(
            now=self.now,
            cache_path=self.cache_path,
            client_factory=lambda _config: FakeClient([]),
            config=fake_config(),
        )

        loaded = reservation_cache.load_reservations_cache(cache_path=self.cache_path)
        self.assertEqual(loaded.reservations, [])
        self.assertEqual(result.reservations_count, 0)

    def test_updated_at_is_refresh_time(self) -> None:
        result = reservation_refresh.refresh_reservation_cache(
            now=self.now,
            cache_path=self.cache_path,
            client_factory=lambda _config: FakeClient([]),
            config=fake_config(),
        )

        self.assertEqual(result.updated_at, self.now)
        loaded = reservation_cache.load_reservations_cache(cache_path=self.cache_path)
        self.assertEqual(loaded.updated_at, self.now)

    def test_config_is_loaded_when_none(self) -> None:
        expected_config = fake_config()
        received_configs: list[ImapConfig] = []

        def factory(config: ImapConfig) -> FakeClient:
            received_configs.append(config)
            return FakeClient([])

        with patch.object(
            reservation_refresh, "load_imap_config", return_value=expected_config
        ) as loader:
            reservation_refresh.refresh_reservation_cache(
                now=self.now,
                cache_path=self.cache_path,
                client_factory=factory,
            )

        loader.assert_called_once_with()
        self.assertEqual(received_configs, [expected_config])

    def test_explicit_config_is_used_without_loading_environment(self) -> None:
        expected_config = fake_config()
        received_configs: list[ImapConfig] = []

        def factory(config: ImapConfig) -> FakeClient:
            received_configs.append(config)
            return FakeClient([])

        with patch.object(reservation_refresh, "load_imap_config") as loader:
            reservation_refresh.refresh_reservation_cache(
                now=self.now,
                cache_path=self.cache_path,
                client_factory=factory,
                config=expected_config,
            )

        loader.assert_not_called()
        self.assertEqual(received_configs, [expected_config])

    def test_existing_cache_is_unchanged_when_imap_fails(self) -> None:
        reservation_cache.save_reservations_cache(
            [sample_reservation("ID-A-CONSERver")], cache_path=self.cache_path
        )
        content_before = self.cache_path.read_bytes()

        with self.assertRaises(ChronogolfIMAPError):
            reservation_refresh.refresh_reservation_cache(
                now=self.now,
                cache_path=self.cache_path,
                client_factory=FailingClient,
                config=fake_config(),
            )

        self.assertEqual(self.cache_path.read_bytes(), content_before)

    def test_no_cache_is_created_when_imap_fails(self) -> None:
        with self.assertRaises(ChronogolfIMAPError):
            reservation_refresh.refresh_reservation_cache(
                now=self.now,
                cache_path=self.cache_path,
                client_factory=FailingClient,
                config=fake_config(),
            )

        self.assertFalse(self.cache_path.exists())

    def test_result_is_immutable_structured_result(self) -> None:
        result = reservation_refresh.refresh_reservation_cache(
            now=self.now,
            cache_path=self.cache_path,
            client_factory=lambda _config: FakeClient([sample_reservation("ID-FICTIF-2")]),
            config=fake_config(),
        )

        self.assertIsInstance(result, reservation_refresh.ReservationRefreshResult)
        self.assertEqual(result.reservations_count, 1)
        self.assertEqual(result.updated_at, self.now)
        with self.assertRaises(Exception):
            result.reservations_count = 2

    def test_main_success_prints_only_count_and_timestamp(self) -> None:
        expected = reservation_refresh.ReservationRefreshResult(2, self.now)
        output = StringIO()
        errors = StringIO()

        with patch.object(
            reservation_refresh, "refresh_reservation_cache", return_value=expected
        ), redirect_stdout(output), redirect_stderr(errors):
            exit_code = reservation_refresh.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            output.getvalue(),
            "reservations_count=2\nupdated_at=2026-08-14T22:30:00\n",
        )
        self.assertEqual(errors.getvalue(), "")

    def test_main_error_is_non_sensitive_and_nonzero(self) -> None:
        output = StringIO()
        errors = StringIO()
        sensitive_error = ChronogolfIMAPError(
            f"échec avec {FAKE_PASSWORD} et utilisateur@exemple.test"
        )

        with patch.object(
            reservation_refresh,
            "refresh_reservation_cache",
            side_effect=sensitive_error,
        ), redirect_stdout(output), redirect_stderr(errors):
            exit_code = reservation_refresh.main()

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn(FAKE_PASSWORD, errors.getvalue())
        self.assertNotIn("utilisateur@exemple.test", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
