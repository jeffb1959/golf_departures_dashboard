"""Tests unitaires du cache JSON des réservations."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import reservation_cache, reservation_parser


def sample_reservation(day: int, reservation_id: str) -> reservation_parser.GolfReservation:
    return reservation_parser.GolfReservation(
        date=date(2026, 8, day),
        heure=time(8, 57),
        joueurs=["Alice Exemple", "Bob Exemple", "Charles Exemple"],
        reservation_id=reservation_id,
    )


class ReservationCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def cache_path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts, "reservation_cache.json")

    def write_payload(self, cache_path: Path, payload: object) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_save_then_load_single_reservation(self) -> None:
        path = self.cache_path("single")
        expected = sample_reservation(18, "ID-FICTIF-1")
        reservation_cache.save_reservations_cache([expected], cache_path=path)
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.reservations, [expected])

    def test_load_rebuilds_date_and_time_types(self) -> None:
        path = self.cache_path("types")
        reservation_cache.save_reservations_cache(
            [sample_reservation(19, "ID-FICTIF-2")], cache_path=path
        )
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertIsInstance(loaded.reservations[0].date, date)
        self.assertIsInstance(loaded.reservations[0].heure, time)

    def test_players_are_preserved(self) -> None:
        path = self.cache_path("players")
        expected = sample_reservation(20, "ID-FICTIF-3")
        reservation_cache.save_reservations_cache([expected], cache_path=path)
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertEqual(loaded.reservations[0].joueurs, expected.joueurs)

    def test_reservation_id_is_preserved(self) -> None:
        path = self.cache_path("id")
        reservation_cache.save_reservations_cache(
            [sample_reservation(21, "ID-FICTIF-4")], cache_path=path
        )
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertEqual(loaded.reservations[0].reservation_id, "ID-FICTIF-4")

    def test_multiple_reservations_are_preserved(self) -> None:
        path = self.cache_path("multiple")
        expected = [
            sample_reservation(22, "ID-FICTIF-5"),
            sample_reservation(23, "ID-FICTIF-6"),
        ]
        reservation_cache.save_reservations_cache(expected, cache_path=path)
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertEqual(loaded.reservations, expected)

    def test_empty_reservation_list_is_valid(self) -> None:
        path = self.cache_path("empty")
        reservation_cache.save_reservations_cache([], cache_path=path)
        loaded = reservation_cache.load_reservations_cache(cache_path=path)
        self.assertEqual(loaded.reservations, [])

    def test_updated_at_is_preserved(self) -> None:
        path = self.cache_path("timestamp")
        expected = datetime(2026, 8, 14, 20, 15, 30)
        saved = reservation_cache.save_reservations_cache(
            [], updated_at=expected, cache_path=path
        )
        self.assertEqual(saved.updated_at, expected)

    def test_parent_directory_is_created(self) -> None:
        path = self.cache_path("new", "nested")
        self.assertFalse(path.parent.exists())
        reservation_cache.save_reservations_cache([], cache_path=path)
        self.assertTrue(path.parent.is_dir())

    def test_missing_file_returns_none(self) -> None:
        path = self.cache_path("missing")
        self.assertIsNone(reservation_cache.load_reservations_cache(cache_path=path))

    def test_corrupted_json_is_rejected(self) -> None:
        path = self.cache_path("corrupted")
        path.parent.mkdir(parents=True)
        path.write_text("{ JSON invalide", encoding="utf-8")
        with self.assertRaises(reservation_cache.ReservationCacheError):
            reservation_cache.load_reservations_cache(cache_path=path)

    def test_unknown_version_is_rejected(self) -> None:
        path = self.cache_path("version")
        self.write_payload(
            path,
            {"version": 99, "updated_at": "2026-08-14T20:15:00", "reservations": []},
        )
        with self.assertRaises(reservation_cache.ReservationCacheError):
            reservation_cache.load_reservations_cache(cache_path=path)

    def test_invalid_reservation_is_rejected(self) -> None:
        path = self.cache_path("invalid")
        self.write_payload(
            path,
            {
                "version": reservation_cache.CURRENT_CACHE_VERSION,
                "updated_at": "2026-08-14T20:15:00",
                "reservations": [{"date": "2026-08-18", "heure": "08:57"}],
            },
        )
        with self.assertRaises(reservation_cache.ReservationCacheError):
            reservation_cache.load_reservations_cache(cache_path=path)

    def test_non_mapping_reservation_is_rejected(self) -> None:
        path = self.cache_path("invalid-entry")
        self.write_payload(
            path,
            {
                "version": reservation_cache.CURRENT_CACHE_VERSION,
                "updated_at": "2026-08-14T20:15:00",
                "reservations": ["entrée invalide"],
            },
        )
        with self.assertRaises(reservation_cache.ReservationCacheError):
            reservation_cache.load_reservations_cache(cache_path=path)

    def test_save_uses_atomic_replace(self) -> None:
        path = self.cache_path("atomic")
        calls: list[tuple[Path, Path]] = []
        original_replace = os.replace

        def record_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            calls.append((Path(source), Path(destination)))
            original_replace(source, destination)

        with patch.object(reservation_cache.os, "replace", side_effect=record_replace):
            reservation_cache.save_reservations_cache([], cache_path=path)

        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0][0], path)
        self.assertEqual(calls[0][1], path)

    def test_only_public_reservation_fields_are_stored(self) -> None:
        path = self.cache_path("fields")
        reservation_cache.save_reservations_cache(
            [sample_reservation(24, "ID-FICTIF-7")], cache_path=path
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload["reservations"][0]),
            {"date", "heure", "joueurs", "reservation_id"},
        )

    @unittest.skipIf(os.name == "nt", "Permissions POSIX non disponibles sous Windows")
    def test_cache_permissions_are_0600(self) -> None:
        path = self.cache_path("permissions")
        reservation_cache.save_reservations_cache([], cache_path=path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_default_path_targets_data_volume(self) -> None:
        self.assertEqual(
            reservation_cache.DEFAULT_CACHE_PATH,
            Path("/data/reservation_cache.json"),
        )


if __name__ == "__main__":
    unittest.main()
