"""Tests HTTP de l'application Flask."""

from __future__ import annotations

from datetime import datetime
import os
import unittest
from unittest.mock import patch

from app import web
from app.reservation_refresh import ReservationRefreshResult


FAKE_TOKEN = "jeton-fictif-long-et-aleatoire"
OTHER_FAKE_TOKEN = "autre-jeton-fictif"
FAKE_PASSWORD = "mot-de-passe-fictif"


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        web.app.config["TESTING"] = True
        self.client = web.app.test_client()

    def post_refresh(self, authorization: str | None = None):
        headers = {"Authorization": authorization} if authorization else {}
        return self.client.post("/api/reservations/refresh", headers=headers)

    def test_health_still_returns_200(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"status": "ok", "service": "golf_departures_dashboard"},
        )

    def test_refresh_without_configured_token_returns_503(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            web, "refresh_reservation_cache"
        ) as refresh:
            response = self.post_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "refresh_not_configured"},
        )
        refresh.assert_not_called()

    def test_refresh_without_authorization_returns_401(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            response = self.post_refresh()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"status": "error", "error": "unauthorized"})

    def test_malformed_authorization_returns_401(self) -> None:
        malformed_headers = (FAKE_TOKEN, f"Basic {FAKE_TOKEN}", "Bearer", "Bearer   ")
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            for header in malformed_headers:
                with self.subTest(header=header):
                    response = self.post_refresh(header)
                    self.assertEqual(response.status_code, 401)

    def test_wrong_bearer_token_returns_401(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            response = self.post_refresh(f"Bearer {OTHER_FAKE_TOKEN}")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"status": "error", "error": "unauthorized"})

    def test_correct_token_calls_refresh_once(self) -> None:
        result = ReservationRefreshResult(1, datetime(2026, 8, 14, 12, 0))
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch.object(
            web, "refresh_reservation_cache", return_value=result
        ) as refresh:
            response = self.post_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with()

    def test_success_returns_count_and_iso_timestamp(self) -> None:
        result = ReservationRefreshResult(3, datetime(2026, 8, 14, 22, 30, 45, 123456))
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch.object(
            web, "refresh_reservation_cache", return_value=result
        ):
            response = self.post_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "status": "ok",
                "reservations": 3,
                "updated_at": "2026-08-14T22:30:45",
            },
        )

    def test_refresh_error_returns_503(self) -> None:
        sensitive_error = RuntimeError(f"{FAKE_PASSWORD} {FAKE_TOKEN}")
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch.object(
            web, "refresh_reservation_cache", side_effect=sensitive_error
        ):
            response = self.post_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "error", "error": "refresh_failed"})

    def test_get_refresh_returns_405_without_triggering_refresh(self) -> None:
        with patch.object(web, "refresh_reservation_cache") as refresh:
            response = self.client.get("/api/reservations/refresh")

        self.assertEqual(response.status_code, 405)
        refresh.assert_not_called()

    def test_responses_never_contain_tokens_or_passwords(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            responses = (
                self.post_refresh(),
                self.post_refresh(f"Bearer {OTHER_FAKE_TOKEN}"),
            )

        for response in responses:
            body = response.get_data(as_text=True)
            self.assertNotIn(FAKE_TOKEN, body)
            self.assertNotIn(OTHER_FAKE_TOKEN, body)
            self.assertNotIn(FAKE_PASSWORD, body)


if __name__ == "__main__":
    unittest.main()
