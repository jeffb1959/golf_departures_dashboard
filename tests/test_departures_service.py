"""Tests unitaires des règles métier des départs pertinents."""

from __future__ import annotations

from datetime import date, datetime, time
import unittest

from app.departures_service import filter_relevant_departures
from app.reservation_parser import GolfReservation


def make_reservation(
    reservation_id: str,
    departure_date: date,
    departure_time: time,
) -> GolfReservation:
    """Crée une réservation entièrement fictive."""

    return GolfReservation(
        date=departure_date,
        heure=departure_time,
        joueurs=["Joueur Exemple"],
        reservation_id=reservation_id,
    )


class DeparturesServiceTests(unittest.TestCase):
    def test_future_departure_is_kept(self) -> None:
        reservation = make_reservation("FUTUR-1", date(2026, 9, 2), time(8, 0))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 12, 0)
        )

        self.assertEqual(result, [reservation])

    def test_today_departure_before_start_is_kept(self) -> None:
        reservation = make_reservation("AVANT-1", date(2026, 9, 1), time(14, 0))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 13, 59)
        )

        self.assertEqual(result, [reservation])

    def test_today_departure_during_five_hour_period_is_kept(self) -> None:
        reservation = make_reservation("EN-COURS-1", date(2026, 9, 1), time(8, 5))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 11, 30)
        )

        self.assertEqual(result, [reservation])

    def test_departure_is_kept_one_second_before_limit(self) -> None:
        reservation = make_reservation("LIMITE-1", date(2026, 9, 1), time(8, 5))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 13, 4, 59)
        )

        self.assertEqual(result, [reservation])

    def test_departure_is_removed_exactly_at_five_hour_limit(self) -> None:
        reservation = make_reservation("LIMITE-2", date(2026, 9, 1), time(8, 5))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 13, 5)
        )

        self.assertEqual(result, [])

    def test_departure_is_removed_after_limit(self) -> None:
        reservation = make_reservation("TERMINE-1", date(2026, 9, 1), time(8, 5))

        result = filter_relevant_departures(
            [reservation], now=datetime(2026, 9, 1, 14, 0)
        )

        self.assertEqual(result, [])

    def test_departures_are_sorted_by_date_then_time(self) -> None:
        later_day = make_reservation("TRI-3", date(2026, 9, 3), time(7, 0))
        later_time = make_reservation("TRI-2", date(2026, 9, 2), time(10, 0))
        earlier_time = make_reservation("TRI-1", date(2026, 9, 2), time(8, 0))

        result = filter_relevant_departures(
            [later_day, later_time, earlier_time],
            now=datetime(2026, 9, 1, 12, 0),
        )

        self.assertEqual(result, [earlier_time, later_time, later_day])

    def test_empty_list_returns_empty_list(self) -> None:
        result = filter_relevant_departures([], now=datetime(2026, 9, 1, 12, 0))

        self.assertEqual(result, [])

    def test_original_list_is_not_modified_and_result_is_new(self) -> None:
        first = make_reservation("ORIGINAL-1", date(2026, 9, 2), time(10, 0))
        second = make_reservation("ORIGINAL-2", date(2026, 9, 2), time(8, 0))
        reservations = [first, second]
        original_order = reservations.copy()

        result = filter_relevant_departures(
            reservations, now=datetime(2026, 9, 1, 12, 0)
        )

        self.assertEqual(reservations, original_order)
        self.assertEqual(result, [second, first])
        self.assertIsNot(result, reservations)

    def test_same_day_departures_are_evaluated_independently(self) -> None:
        finished = make_reservation("MEME-JOUR-1", date(2026, 9, 1), time(7, 0))
        still_relevant = make_reservation("MEME-JOUR-2", date(2026, 9, 1), time(9, 0))
        upcoming = make_reservation("MEME-JOUR-3", date(2026, 9, 1), time(15, 0))

        result = filter_relevant_departures(
            [upcoming, finished, still_relevant],
            now=datetime(2026, 9, 1, 12, 30),
        )

        self.assertEqual(result, [still_relevant, upcoming])


if __name__ == "__main__":
    unittest.main()
