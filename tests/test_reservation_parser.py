"""Tests unitaires du parseur de confirmations Chronogolf."""

from __future__ import annotations

from datetime import date, datetime, time
from email.message import EmailMessage
import unittest

from app import reservation_parser


PLAIN_CONFIRMATION_TEXT = """\
Réservation confirmée

Club de golf Exemple

Réservation confirmée
mar. 18 août 2026
08:57
3 joueurs • Parcours de golf (18 trous)
Lac du Chêne

Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon
ID de réservation : ABCD-1234
"""

HTML_CONFIRMATION_TEXT = """\
<html><body>
<p>Réservation confirmée</p>
<p>Club de golf Exemple</p>
<p>Réservation confirmée</p>
<p>mar. 18 août 2026</p>
<p>08:57</p>
<p>3 joueurs • Parcours de golf (18 trous)</p>
<p>Lac du Chêne</p>
<p>Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon</p>
<p>ID de réservation : ABCD-1234</p>
</body></html>
"""


class ReservationParserTests(unittest.TestCase):
    def test_parse_french_date_with_weekday(self) -> None:
        self.assertEqual(
            reservation_parser.parse_french_date("mar. 18 août 2026"),
            date(2026, 8, 18),
        )

    def test_parse_hour(self) -> None:
        self.assertEqual(reservation_parser.parse_hour("08:57"), time(8, 57))

    def test_parse_english_dates(self) -> None:
        self.assertEqual(
            reservation_parser.parse_english_date("Fri, September 4, 2026"),
            date(2026, 9, 4),
        )
        self.assertEqual(
            reservation_parser.parse_english_date("September 4, 2026"),
            date(2026, 9, 4),
        )

    def test_parse_english_hours(self) -> None:
        expected = {
            "8:30 AM": time(8, 30),
            "1:05 PM": time(13, 5),
            "12:00 AM": time(0, 0),
            "12:00 PM": time(12, 0),
        }
        for value, parsed in expected.items():
            with self.subTest(value=value):
                self.assertEqual(reservation_parser.parse_hour(value), parsed)

    def test_parse_hour_rejects_non_full_line_text(self) -> None:
        invalid_values = (
            "(UTC-05:00) Eastern Time",
            "Envoyé : 13 août 2026 08:57",
            "texte 08:57 autre texte",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(reservation_parser.ReservationParseError):
                    reservation_parser.parse_hour(value)

    def test_parse_players_and_activity(self) -> None:
        count, activity = reservation_parser.parse_players_and_activity(
            "3 joueurs • Parcours de golf (18 trous)"
        )
        self.assertEqual(count, 3)
        self.assertEqual(activity, "Parcours de golf (18 trous)")

    def test_parse_location_from_confirmation_body(self) -> None:
        reservation = reservation_parser.parse_confirmation_reservation(
            """\
Réservation confirmée

Club de golf Exemple

Réservation confirmée
mer. 19 septembre 2026
09:30
3 joueurs • Parcours de golf (18 trous)
Terrain du Parc
Nom : Alice Martin, Bob B.
ID de réservation : TOUR-99
"""
        )
        self.assertEqual(reservation.joueurs, ["Alice Martin", "Bob B"])

    def test_parse_three_players_with_commas_and_et(self) -> None:
        players = reservation_parser.parse_players(
            "Alice Martin, Bob Durand et Charles Léon"
        )
        self.assertEqual(players, ["Alice Martin", "Bob Durand", "Charles Léon"])

    def test_parse_three_players_with_name_and_and(self) -> None:
        players = reservation_parser.parse_players(
            "Alice. Martin, Bob. Martin, and Charles Martin"
        )
        self.assertEqual(players, ["Alice Martin", "Bob Martin", "Charles Martin"])

    def test_clean_player_name_with_spurious_dot(self) -> None:
        self.assertEqual(
            reservation_parser.parse_player_name("Alice. Tremblay"),
            "Alice Tremblay",
        )

    def test_parse_reservation_id_line(self) -> None:
        self.assertEqual(
            reservation_parser.parse_reservation_id_line(
                "ID de réservation : ABCD-1234"
            ),
            "ABCD-1234",
        )
        self.assertEqual(
            reservation_parser.parse_reservation_id_line("Booking ID: TEST-5678"),
            "TEST-5678",
        )

    def test_parse_complete_current_english_confirmation(self) -> None:
        reservation = reservation_parser.parse_confirmation_reservation(
            """\
Reservation confirmed
Example Golf Club
Reservation confirmed
Fri, September 4, 2026
8:30 AM
3 players • Round of golf (18 holes)
Lorette
Name: Alice. Martin, Bob. Martin, and Charles Martin
Booking ID: TEST-1234
"""
        )
        self.assertEqual(reservation.date, date(2026, 9, 4))
        self.assertEqual(reservation.heure, time(8, 30))
        self.assertEqual(reservation.joueurs, ["Alice Martin", "Bob Martin", "Charles Martin"])
        self.assertEqual(reservation.reservation_id, "TEST-1234")

    def test_english_confirmation_ignores_forwarded_header_date(self) -> None:
        reservation = reservation_parser.parse_confirmation_reservation(
            """\
Sent: January 2, 2026
January 2, 2026
Reservation confirmed
September 4, 2026
1:05 PM
2 players • Round of golf (18 holes)
Example course
Name: Alice Martin and Bob Martin
Booking ID: TEST-5678
"""
        )
        self.assertEqual(reservation.date, date(2026, 9, 4))
        self.assertEqual(reservation.heure, time(13, 5))

    def test_parse_complete_historical_english_confirmation(self) -> None:
        reservation = reservation_parser.parse_confirmation_reservation(
            """\
October 1, 2025
Tee Time Reservation Confirmation
Reservation 0H8D-6F4Z
11:45 AM
October 18, 2025
Lorette
Round of golf (18 holes)
● ● ● Alice. Martin, Bob. Martin, and Guest
"""
        )
        self.assertEqual(reservation.date, date(2025, 10, 18))
        self.assertEqual(reservation.heure, time(11, 45))
        self.assertEqual(reservation.joueurs, ["Alice Martin", "Bob Martin", "Guest"])
        self.assertEqual(reservation.reservation_id, "0H8D-6F4Z")

    def test_parse_complete_confirmation(self) -> None:
        received_at = datetime(2026, 8, 10, 12, 0, 0)
        reservation = reservation_parser.parse_confirmation_reservation(
            PLAIN_CONFIRMATION_TEXT,
            received_at=received_at,
        )
        self.assertEqual(reservation.date, date(2026, 8, 18))
        self.assertEqual(reservation.heure, time(8, 57))
        self.assertEqual(
            reservation.joueurs,
            ["Alice Tremblay", "Bob Martin", "Charles Gagnon"],
        )
        self.assertEqual(reservation.reservation_id, "ABCD-1234")
        self.assertEqual(reservation.received_at, received_at)

    def test_parse_format1_confirmation_with_timezone_and_full_block(self) -> None:
        text = """\
(UTC-05:00) Eastern Time

Club de golf Lorette

Réservation confirmée
mar. 18 août 2026
08:57
3 joueurs • Parcours de golf (18 trous)
Terrain Lorette

Nom : Alice. Tremblay, Bob Martin et Charles. Gagnon
ID de réservation : TEST-1234
"""
        reservation = reservation_parser.parse_confirmation_reservation(text)
        self.assertEqual(reservation.date, date(2026, 8, 18))
        self.assertEqual(reservation.heure, time(8, 57))
        self.assertEqual(
            reservation.joueurs,
            ["Alice Tremblay", "Bob Martin", "Charles Gagnon"],
        )
        self.assertEqual(reservation.reservation_id, "TEST-1234")

    def test_parse_format2_confirmation_block(self) -> None:
        text = """\
Club de golf Lorette

Réservation confirmée

mer. 19 août 2026
08:12
4 joueurs • Ronde de golf (18 trous)
Terrain Lorette

Nom : Alice Martin, Bob. Dupont, Charles Gagnon et Diane Roy
ID de réservation : TEST-5678
"""
        reservation = reservation_parser.parse_confirmation_reservation(text)
        self.assertEqual(reservation.date, date(2026, 8, 19))
        self.assertEqual(reservation.heure, time(8, 12))
        self.assertEqual(
            reservation.joueurs,
            ["Alice Martin", "Bob Dupont", "Charles Gagnon", "Diane Roy"],
        )
        self.assertEqual(reservation.reservation_id, "TEST-5678")

    def test_parse_with_non_breaking_spaces(self) -> None:
        text = (
            "Réservation confirmée\n\n"
            "Club de golf Exemple\n\n"
            "Réservation confirmée\n"
            "mar.\u00a0\u2007 18\u00a0août\u00a02026\n"
            "08:57\n"
            "3\u00a0joueurs\u202f\u00b7\u00a0Parcours\u00a0de\u00a0golf\u00a0(18\u00a0trous)\n"
            "Lac\u00a0du\u00a0Chêne\n\n"
            "Nom\u00a0:\u00a0Alice.\u00a0Tremblay\n"
            "ID\u00a0de\u00a0réservation\u00a0:\u00a0ABCD-1234\n"
        )
        reservation = reservation_parser.parse_confirmation_reservation(text)
        self.assertEqual(reservation.joueurs, ["Alice Tremblay"])

    def test_discard_past_reservation(self) -> None:
        reservations = [
            self._reservation(date(2026, 8, 9), time(8), "R-1"),
            self._reservation(date(2026, 8, 10), time(9), "R-2"),
        ]
        filtered = reservation_parser.filter_upcoming_reservations(
            reservations, today=date(2026, 8, 10)
        )
        self.assertEqual([item.reservation_id for item in filtered], ["R-2"])

    def test_keep_today_reservation(self) -> None:
        reservation = self._reservation(date(2026, 8, 10), time(12), "R-3")
        self.assertEqual(
            reservation_parser.filter_upcoming_reservations(
                [reservation], today=date(2026, 8, 10)
            ),
            [reservation],
        )

    def test_keep_future_reservation(self) -> None:
        reservation = self._reservation(date(2026, 8, 11), time(12), "R-4")
        self.assertEqual(
            reservation_parser.filter_upcoming_reservations(
                [reservation], today=date(2026, 8, 10)
            ),
            [reservation],
        )

    def test_sort_reservations_by_date_then_time(self) -> None:
        first = self._reservation(date(2026, 8, 12), time(9), "R-1")
        second = self._reservation(date(2026, 8, 11), time(18), "R-2")
        third = self._reservation(date(2026, 8, 11), time(9), "R-3")
        self.assertEqual(
            reservation_parser.sort_reservations([first, second, third]),
            [third, second, first],
        )

    def test_deduplicate_by_reservation_id_keep_latest_received(self) -> None:
        first = self._reservation(
            date(2026, 8, 11), time(9), "DUP-1", datetime(2026, 8, 1, 12)
        )
        second = self._reservation(
            date(2026, 8, 11), time(9), "DUP-1", datetime(2026, 8, 2, 12)
        )
        different = self._reservation(
            date(2026, 8, 12), time(9), "DUP-2", datetime(2026, 8, 1, 12)
        )
        deduplicated = reservation_parser.deduplicate_reservations(
            [first, second, different]
        )
        self.assertEqual(len(deduplicated), 2)
        self.assertIn(second, deduplicated)
        self.assertIn(different, deduplicated)

    def test_incomplete_confirmation_is_reported(self) -> None:
        with self.assertRaises(reservation_parser.ReservationParseError) as context:
            reservation_parser.parse_confirmation_reservation(
                """\
Réservation confirmée
mar. 19 août 2026
08:57
Nom : Alice. Tremblay
"""
            )
        self.assertEqual(
            str(context.exception),
            "Informations essentielles incomplètes : reservation_id",
        )
        self.assertNotIn("Alice", str(context.exception))

    def test_extract_message_plain_body(self) -> None:
        message = self._message(PLAIN_CONFIRMATION_TEXT, "plain")
        body = reservation_parser.extract_confirmation_body_text(message.as_bytes())
        self.assertIn("3 joueurs", body)
        self.assertIn("ID de réservation", body)

    def test_extract_message_html(self) -> None:
        message = self._message(HTML_CONFIRMATION_TEXT, "html")
        body = reservation_parser.extract_confirmation_body_text(message.as_bytes())
        self.assertIn("Lac du Chêne", body)
        self.assertIn("ID de réservation", body)

    @staticmethod
    def _reservation(
        reservation_date: date,
        reservation_time: time,
        reservation_id: str,
        received_at: datetime | None = None,
    ) -> reservation_parser.GolfReservation:
        return reservation_parser.GolfReservation(
            date=reservation_date,
            heure=reservation_time,
            joueurs=["Joueur A", "Joueur B"],
            reservation_id=reservation_id,
            received_at=received_at,
        )

    @staticmethod
    def _message(content: str, subtype: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = "noreply@example.test"
        message["To"] = "user@example.test"
        message["Subject"] = "Confirmation de réservation"
        message.set_content(content, subtype=subtype, charset="utf-8")
        return message


if __name__ == "__main__":
    unittest.main()
