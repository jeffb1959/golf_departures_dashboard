"""Tests HTTP de l'application Flask."""

from __future__ import annotations

from datetime import datetime
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app import web
from app import display_targets
from app.display_artifact import get_display_artifact_path
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

    def _create_artifact(self, directory: str | Path, payload: bytes) -> Path:
        target = display_targets.get_display_target("waveshare_75_bw")
        artifact_path = get_display_artifact_path(target, output_dir=directory)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(payload)
        return artifact_path

    def test_api_display_artifact_returns_file_and_headers_when_available(self) -> None:
        payload = b"0123456789ABCDEF"
        with tempfile.TemporaryDirectory() as tmp:
            target = display_targets.get_display_target("waveshare_75_bw")
            artifact_path = self._create_artifact(tmp, payload)

            with patch.object(web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)):
                response = self.client.get("/api/display/artifact")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, payload)
            self.assertTrue(response.headers["Content-Type"].startswith(target.mime_type))
            self.assertEqual(response.headers.get("X-Display-Profile"), target.name)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertEqual(response.headers.get("Content-Length"), str(len(payload)))
            self.assertTrue(artifact_path.is_file())

    def test_api_display_artifact_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)):
                response = self.client.get("/api/display/artifact")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(
                response.get_json(),
                {"status": "error", "error": "display_artifact_not_found"},
            )

    def test_api_display_artifact_invalid_profile(self) -> None:
        with patch.dict(os.environ, {"DISPLAY_PROFILE": "inconnu"}, clear=True):
            response = self.client.get("/api/display/artifact")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json(),
                {"status": "error", "error": "display_not_configured"},
            )

    def test_api_display_artifact_does_not_generate_artifact(self) -> None:
        payload = b"1234"
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)
        ), patch(
            "app.display_artifact.generate_display_artifact",
            side_effect=RuntimeError("should not be called"),
        ) as generate:
            target = display_targets.get_display_target("waveshare_75_bw")
            self._create_artifact(tmp, payload)

            response = self.client.get("/api/display/artifact")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        generate.assert_not_called()

    def test_api_display_artifact_invalid_profile_logs_configured_error(self) -> None:
        with patch.dict(os.environ, {"DISPLAY_PROFILE": "inconnu"}, clear=True), patch.object(
            web.app.logger, "error"
        ) as logger_error:
            response = self.client.get("/api/display/artifact")

        self.assertEqual(response.status_code, 503)
        logger_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
