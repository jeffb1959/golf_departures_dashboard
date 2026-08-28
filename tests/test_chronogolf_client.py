"""Tests unitaires du client IMAP Chronogolf, sans connexion réseau."""

from __future__ import annotations

from datetime import date, datetime
from email.header import Header
import imaplib
import os
import socket
import ssl
import unittest
from unittest.mock import patch

from app import chronogolf_client


FAKE_PASSWORD = "mot-de-passe-fictif"


def make_headers(subject: str, date_header: str) -> bytes:
    return f"Subject: {subject}\r\nDate: {date_header}\r\n\r\n".encode("utf-8")


def make_body(date_line: str, hour: str, reservation_id: str) -> bytes:
    return "\n".join(
        (
            "Réservation confirmée",
            "Club de golf Exemple",
            "Réservation confirmée",
            date_line,
            hour,
            "3 joueurs • Parcours de golf (18 trous)",
            "Terrain Exemple",
            "Nom : Alice Exemple, Bob Exemple et Charles Exemple",
            f"ID de réservation : {reservation_id}",
        )
    ).encode("utf-8")


class FakeImap:
    def __init__(
        self,
        search_data: str = "",
        headers: dict[str, bytes] | None = None,
        bodies: dict[str, bytes] | None = None,
        *,
        select_status: str = "OK",
        search_status: str = "OK",
        login_error: Exception | None = None,
    ) -> None:
        self.search_data = search_data
        self.headers = headers or {}
        self.bodies = bodies or {}
        self.select_status = select_status
        self.search_status = search_status
        self.login_error = login_error
        self.calls: list[tuple[object, ...]] = []

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))
        if self.login_error:
            raise self.login_error

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.calls.append(("select", mailbox, readonly))
        return self.select_status, [b""]

    def search(self, *args: object) -> tuple[str, list[bytes]]:
        self.calls.append(("search", *args))
        return self.search_status, [self.search_data.encode()]

    def fetch(self, message_id: str, query: str) -> tuple[str, list[tuple[bytes, bytes]]]:
        self.calls.append(("fetch", message_id, query))
        source = self.headers if "HEADER.FIELDS" in query else self.bodies
        payload = source.get(message_id)
        return ("OK", [(b"data", payload)]) if payload is not None else ("NO", [])

    def close(self) -> tuple[str, list[bytes]]:
        self.calls.append(("close",))
        return "OK", []

    def logout(self) -> tuple[str, list[bytes]]:
        self.calls.append(("logout",))
        return "OK", []


class ChronogolfClientTests(unittest.TestCase):
    def make_client(self, fake: FakeImap) -> chronogolf_client.ChronogolfClient:
        config = chronogolf_client.ImapConfig(
            host="imap.exemple.test",
            port=993,
            user="utilisateur@exemple.test",
            password=FAKE_PASSWORD,
        )
        return chronogolf_client.ChronogolfClient(
            config, imap_factory=lambda _host, _port: fake
        )

    def fetch(self, fake: FakeImap, *, reference: datetime | None = None):
        return self.make_client(fake).get_upcoming_reservations_with_report(
            reference=reference or datetime(2026, 8, 14),
            today=date(2026, 8, 14),
        )

    def test_load_config_from_explicit_mapping(self) -> None:
        config = chronogolf_client.load_imap_config(
            {
                "VIDEOTRON_IMAP_HOST": "imap.exemple.test",
                "VIDEOTRON_IMAP_PORT": "993",
                "VIDEOTRON_IMAP_USER": "personne@exemple.test",
                "VIDEOTRON_IMAP_PASSWORD": FAKE_PASSWORD,
            }
        )
        self.assertEqual(config.host, "imap.exemple.test")
        self.assertEqual(config.port, 993)
        self.assertEqual(config.user, "personne@exemple.test")
        self.assertEqual(config.password, FAKE_PASSWORD)

    def test_load_config_uses_os_environ_by_default(self) -> None:
        values = {
            "VIDEOTRON_IMAP_HOST": "imap.environnement.test",
            "VIDEOTRON_IMAP_PORT": "143",
            "VIDEOTRON_IMAP_USER": "env@exemple.test",
            "VIDEOTRON_IMAP_PASSWORD": FAKE_PASSWORD,
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(chronogolf_client.load_imap_config().port, 143)

    def test_missing_variable_names_only_and_never_password_value(self) -> None:
        with self.assertRaises(chronogolf_client.ImapConfigError) as context:
            chronogolf_client.load_imap_config(
                {
                    "VIDEOTRON_IMAP_HOST": "imap.exemple.test",
                    "VIDEOTRON_IMAP_PORT": "993",
                    "VIDEOTRON_IMAP_USER": "",
                    "VIDEOTRON_IMAP_PASSWORD": FAKE_PASSWORD,
                }
            )
        self.assertIn("VIDEOTRON_IMAP_USER", str(context.exception))
        self.assertNotIn(FAKE_PASSWORD, str(context.exception))

    def test_invalid_ports_are_rejected(self) -> None:
        base = {
            "VIDEOTRON_IMAP_HOST": "imap.exemple.test",
            "VIDEOTRON_IMAP_USER": "personne@exemple.test",
            "VIDEOTRON_IMAP_PASSWORD": FAKE_PASSWORD,
        }
        for invalid_port in ("invalide", "0", "-1"):
            with self.subTest(port=invalid_port):
                with self.assertRaises(chronogolf_client.ImapConfigError):
                    chronogolf_client.load_imap_config(
                        {**base, "VIDEOTRON_IMAP_PORT": invalid_port}
                    )

    def test_searches_from_j_minus_7_and_selects_readonly_inbox(self) -> None:
        fake = FakeImap()
        result = self.fetch(fake)
        self.assertEqual(result.search_since, date(2026, 8, 7))
        self.assertIn(("select", "INBOX", True), fake.calls)
        self.assertIn(("search", None, "SINCE", "07-Aug-2026"), fake.calls)

    def test_mime_subject_is_decoded_and_body_peek_is_used(self) -> None:
        encoded = Header("Confirmation de réservation", "utf-8").encode()
        fake = FakeImap(
            "1",
            {"1": make_headers(encoded, "Tue, 11 Aug 2026 11:00:00 +0000")},
            {"1": make_body("mar. 18 août 2026", "08:57", "ID-FICTIF-1")},
        )
        result = self.fetch(fake)
        self.assertEqual([r.reservation_id for r in result.reservations], ["ID-FICTIF-1"])
        self.assertIn(
            ("fetch", "1", "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])"), fake.calls
        )
        self.assertIn(("fetch", "1", "(BODY.PEEK[])") , fake.calls)

    def test_non_confirmation_subject_does_not_fetch_body(self) -> None:
        fake = FakeImap(
            "1 2",
            {
                "1": make_headers("Infolettre", "Tue, 11 Aug 2026 10:00:00 +0000"),
                "2": make_headers("Confirmation de réservation", "Tue, 11 Aug 2026 11:00:00 +0000"),
            },
            {"2": make_body("mar. 18 août 2026", "08:57", "ID-FICTIF-2")},
        )
        result = self.fetch(fake)
        self.assertEqual(result.confirmations_found, 1)
        self.assertNotIn(("fetch", "1", "(BODY.PEEK[])"), fake.calls)

    def test_invalid_confirmation_is_ignored_and_next_is_kept(self) -> None:
        headers = {
            key: make_headers("Confirmation de réservation", "Tue, 11 Aug 2026 11:00:00 +0000")
            for key in ("1", "2")
        }
        fake = FakeImap(
            "1 2", headers,
            {"1": b"contenu invalide", "2": make_body("mar. 18 août 2026", "08:57", "ID-VALIDE")},
        )
        result = self.fetch(fake)
        self.assertEqual(result.confirmations_ignored, 1)
        self.assertEqual([r.reservation_id for r in result.reservations], ["ID-VALIDE"])

    def test_past_is_rejected_while_today_and_future_are_kept(self) -> None:
        headers = {
            key: make_headers("Confirmation de réservation", "Tue, 11 Aug 2026 11:00:00 +0000")
            for key in ("1", "2", "3")
        }
        fake = FakeImap(
            "1 2 3", headers,
            {
                "1": make_body("jeu. 13 août 2026", "09:00", "ID-PASSE"),
                "2": make_body("ven. 14 août 2026", "09:00", "ID-AUJOURDHUI"),
                "3": make_body("sam. 15 août 2026", "09:00", "ID-FUTUR"),
            },
        )
        result = self.fetch(fake)
        self.assertEqual(
            [r.reservation_id for r in result.reservations],
            ["ID-AUJOURDHUI", "ID-FUTUR"],
        )

    def test_deduplicates_by_id_and_keeps_latest_received(self) -> None:
        fake = FakeImap(
            "1 2",
            {
                "1": make_headers("Confirmation de réservation", "Mon, 10 Aug 2026 08:00:00 +0000"),
                "2": make_headers("Confirmation de réservation", "Tue, 11 Aug 2026 08:00:00 +0000"),
            },
            {
                "1": make_body("mar. 18 août 2026", "08:00", "ID-DOUBLON"),
                "2": make_body("mer. 19 août 2026", "08:00", "ID-DOUBLON"),
            },
        )
        result = self.fetch(fake)
        self.assertEqual(len(result.reservations), 1)
        self.assertEqual(result.reservations[0].date, date(2026, 8, 19))

    def test_sorts_by_date_then_time(self) -> None:
        headers = {
            key: make_headers("Confirmation de réservation", "Tue, 11 Aug 2026 11:00:00 +0000")
            for key in ("1", "2", "3")
        }
        fake = FakeImap(
            "1 2 3", headers,
            {
                "1": make_body("mer. 19 août 2026", "09:00", "ID-C"),
                "2": make_body("mar. 18 août 2026", "10:00", "ID-A"),
                "3": make_body("mer. 19 août 2026", "08:00", "ID-B"),
            },
        )
        self.assertEqual(
            [r.reservation_id for r in self.fetch(fake).reservations],
            ["ID-A", "ID-B", "ID-C"],
        )

    def test_no_reservation_returns_empty_list(self) -> None:
        self.assertEqual(self.fetch(FakeImap()).reservations, [])

    def test_server_error_is_clean_and_connection_is_closed(self) -> None:
        fake = FakeImap(select_status="NO")
        with self.assertRaises(chronogolf_client.ChronogolfIMAPError) as context:
            self.fetch(fake)
        self.assertNotIn(FAKE_PASSWORD, str(context.exception))
        self.assertIn(("close",), fake.calls)
        self.assertIn(("logout",), fake.calls)

    def test_authentication_error_is_clean_and_logs_out(self) -> None:
        fake = FakeImap(login_error=imaplib.IMAP4.error("échec fictif"))
        with self.assertRaisesRegex(chronogolf_client.ChronogolfIMAPError, "authentification"):
            self.fetch(fake)
        self.assertIn(("close",), fake.calls)
        self.assertIn(("logout",), fake.calls)

    def test_network_and_ssl_errors_are_clean(self) -> None:
        cases = (
            (socket.gaierror("hôte fictif"), "réseau"),
            (ssl.SSLError("certificat fictif"), "SSL"),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                config = chronogolf_client.ImapConfig(
                    "imap.exemple.test", 993, "personne@exemple.test", FAKE_PASSWORD
                )
                client = chronogolf_client.ChronogolfClient(
                    config, imap_factory=lambda _host, _port, exc=error: (_ for _ in ()).throw(exc)
                )
                with self.assertRaises(chronogolf_client.ChronogolfIMAPError) as context:
                    client.get_upcoming_reservations()
                self.assertIn(expected, str(context.exception))
                self.assertNotIn(FAKE_PASSWORD, str(context.exception))


if __name__ == "__main__":
    unittest.main()
