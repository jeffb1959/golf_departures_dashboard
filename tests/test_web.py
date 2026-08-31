"""Tests HTTP de l'application Flask."""

from __future__ import annotations

import hashlib
from datetime import datetime
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from zoneinfo import ZoneInfo

from app import web
from app import display_targets
from app.display_artifact import get_display_artifact_path
from app.reservation_refresh import ReservationRefreshResult
from app.dashboard_refresh import DashboardRefreshError, DashboardRefreshResult


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

    def post_dashboard_refresh(self, authorization: str | None = None):
        headers = {"Authorization": authorization} if authorization else {}
        return self.client.post("/api/dashboard/refresh", headers=headers)

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

    def test_api_display_manifest_returns_metadata_headers_when_available(self) -> None:
        payload = b"manifest-payload"
        target = display_targets.get_display_target("waveshare_75_bw")
        mtime = 1_700_000_000
        expected_generated_at = datetime.fromtimestamp(mtime, tz=ZoneInfo("America/Toronto"))
        expected_sha = hashlib.sha256(payload).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = self._create_artifact(tmp, payload)
            os.utime(artifact_path, times=(mtime, mtime))

            with patch.object(web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)):
                response = self.client.get("/api/display/manifest")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, dict)
        self.assertEqual(
            data,
            {
                "schema_version": 1,
                "profile": target.name,
                "width": target.width,
                "height": target.height,
                "output_format": target.output_format,
                "mime_type": target.mime_type,
                "payload_size": len(payload),
                "sha256": expected_sha,
                "generated_at": expected_generated_at.isoformat(),
                "artifact_url": "/api/display/artifact",
            },
        )
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.headers.get("X-Display-Profile"), target.name)

    def test_api_display_manifest_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)):
                response = self.client.get("/api/display/manifest")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "display_artifact_not_found"},
        )

    def test_api_display_manifest_invalid_profile(self) -> None:
        with patch.dict(os.environ, {"DISPLAY_PROFILE": "inconnu"}, clear=True):
            response = self.client.get("/api/display/manifest")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "display_not_configured"},
        )

    def test_api_display_manifest_does_not_refresh_services(self) -> None:
        payload = b"manifest-stable"
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            web, "DEFAULT_DISPLAY_OUTPUT_DIR", Path(tmp)
        ), patch("app.display_artifact.generate_display_artifact") as generate_display, patch.object(
            web, "refresh_dashboard"
        ) as refresh_dashboard, patch.object(
            web, "refresh_reservation_cache"
        ) as refresh_reservation:
            target = display_targets.get_display_target("waveshare_75_bw")
            self._create_artifact(tmp, payload)

            response = self.client.get("/api/display/manifest")

            self.assertEqual(response.status_code, 200)
            refresh_reservation.assert_not_called()
            refresh_dashboard.assert_not_called()
            generate_display.assert_not_called()
            self.assertEqual(response.get_json()["profile"], target.name)

    def test_dashboard_refresh_without_configured_token_returns_503(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            web, "refresh_dashboard"
        ) as refresh:
            response = self.post_dashboard_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "refresh_not_configured"},
        )
        refresh.assert_not_called()

    def test_dashboard_refresh_without_authorization_returns_401(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            response = self.post_dashboard_refresh()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"status": "error", "error": "unauthorized"})

    def test_dashboard_refresh_with_wrong_bearer_returns_401(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True):
            response = self.post_dashboard_refresh(f"Bearer {OTHER_FAKE_TOKEN}")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"status": "error", "error": "unauthorized"})

    def test_dashboard_refresh_success_returns_payload(self) -> None:
        result = DashboardRefreshResult(
            reservations_count=3,
            reservations_updated_at=datetime(2026, 8, 31, 17, 0),
            display_profile="waveshare_75_bw",
            display_payload_size=48_000,
            display_departures_count=3,
            display_generated_at=datetime(2026, 8, 31, 17, 0),
        )
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch.object(
            web, "refresh_dashboard", return_value=result
        ):
            response = self.post_dashboard_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "status": "ok",
                "reservations": {
                    "count": 3,
                    "updated_at": "2026-08-31T17:00:00",
                },
                "display": {
                    "profile": "waveshare_75_bw",
                    "payload_size": 48000,
                    "departures_count": 3,
                    "generated_at": "2026-08-31T17:00:00",
                },
            },
        )

    def test_dashboard_refresh_reservations_stage_error_returns_503(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch(
            "app.web.refresh_dashboard",
            side_effect=DashboardRefreshError("reservations"),
        ):
            response = self.post_dashboard_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "dashboard_reservations_refresh_failed"},
        )

    def test_dashboard_refresh_display_stage_error_returns_503(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch(
            "app.web.refresh_dashboard",
            side_effect=DashboardRefreshError("display"),
        ):
            response = self.post_dashboard_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.get_json(),
            {"status": "error", "error": "dashboard_display_refresh_failed"},
        )

    def test_dashboard_refresh_calls_orchestrator(self) -> None:
        with patch.dict(os.environ, {"GOLF_REFRESH_TOKEN": FAKE_TOKEN}, clear=True), patch.object(
            web,
            "refresh_dashboard",
            return_value=DashboardRefreshResult(
                reservations_count=0,
                reservations_updated_at=datetime(2026, 8, 31, 17, 0),
                display_profile="waveshare_75_bw",
                display_payload_size=0,
                display_departures_count=0,
                display_generated_at=datetime(2026, 8, 31, 17, 0),
            ),
        ) as refresh:
            response = self.post_dashboard_refresh(f"Bearer {FAKE_TOKEN}")

        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
