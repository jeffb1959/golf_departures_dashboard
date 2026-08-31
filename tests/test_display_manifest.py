"""Tests pour la construction du manifeste d'affichage."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.display_manifest import (
    DEFAULT_ARTIFACT_URL,
    DisplayArtifactNotFoundError,
    DisplayManifest,
    LOCAL_TIMEZONE,
    build_display_manifest,
)


class FakeTarget:
    """Profil minimal pour valider le manifeste sans dépendance à une vraie cible."""

    name = "fake_profile"
    width = 800
    height = 480
    output_format = "raw_1bit"
    mime_type = "application/octet-stream"
    file_extension = ".bin"


class DisplayManifestTests(unittest.TestCase):
    def test_build_display_manifest_with_fake_target(self) -> None:
        payload = b"hello-manifest"
        expected_sha = hashlib.sha256(payload).hexdigest()
        expected_size = len(payload)

        with tempfile.TemporaryDirectory() as tmp:
            target = FakeTarget()
            artifact_path = Path(tmp) / f"departures_display{target.file_extension}"
            artifact_path.write_bytes(payload)
            manifest = build_display_manifest(
                target=target,  # type: ignore[arg-type]
                output_dir=tmp,
                artifact_url="/api/display/artifact",
            )

            self.assertIsInstance(manifest, DisplayManifest)
            self.assertEqual(manifest.schema_version, 1)
            self.assertEqual(manifest.profile, target.name)
            self.assertEqual(manifest.width, target.width)
            self.assertEqual(manifest.height, target.height)
            self.assertEqual(manifest.output_format, target.output_format)
            self.assertEqual(manifest.mime_type, target.mime_type)
            self.assertEqual(manifest.payload_size, expected_size)
            self.assertEqual(manifest.sha256, expected_sha)
            self.assertEqual(manifest.artifact_url, "/api/display/artifact")
            self.assertEqual(len(manifest.sha256), 64)
            self.assertTrue(manifest.sha256.islower())
            self.assertEqual(manifest.to_dict()["payload_size"], expected_size)
            self.assertIsInstance(manifest.generated_at, datetime)
            self.assertEqual(manifest.generated_at.tzinfo, LOCAL_TIMEZONE)

    def test_build_display_manifest_uses_real_file_size_and_mtime(self) -> None:
        payload = b"abc" * 7
        target = FakeTarget()
        mtime = 1_700_000_000
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / f"departures_display{target.file_extension}"
            artifact_path.write_bytes(payload)
            os.utime(artifact_path, times=(mtime, mtime))
            expected_generated_at = datetime.fromtimestamp(mtime, tz=LOCAL_TIMEZONE)

            manifest = build_display_manifest(
                target=target,  # type: ignore[arg-type]
                output_dir=tmp,
            )

            self.assertEqual(manifest.payload_size, len(payload))
            self.assertEqual(manifest.generated_at, expected_generated_at)
            self.assertEqual(manifest.generated_at.tzinfo, LOCAL_TIMEZONE)

    def test_build_display_manifest_uses_default_artifact_url(self) -> None:
        target = FakeTarget()
        payload = b"x" * 4

        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / f"departures_display{target.file_extension}"
            artifact_path.write_bytes(payload)

            manifest = build_display_manifest(
                target=target,  # type: ignore[arg-type]
                output_dir=tmp,
            )
            self.assertEqual(manifest.artifact_url, DEFAULT_ARTIFACT_URL)

    def test_manifest_payload_hash_is_stable_for_known_payload(self) -> None:
        payload = bytes(range(64))
        target = FakeTarget()
        expected_sha = hashlib.sha256(payload).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / f"departures_display{target.file_extension}"
            artifact_path.write_bytes(payload)
            manifest = build_display_manifest(
                target=target,  # type: ignore[arg-type]
                output_dir=tmp,
            )
            self.assertEqual(manifest.sha256, expected_sha)
            self.assertEqual(len(manifest.sha256), 64)

    def test_display_artifact_not_found_error(self) -> None:
        target = FakeTarget()

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DisplayArtifactNotFoundError):
                build_display_manifest(
                    target=target,  # type: ignore[arg-type]
                    output_dir=tmp,
                )

    def test_display_artifact_path_must_be_regular_file(self) -> None:
        target = FakeTarget()
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / f"departures_display{target.file_extension}"
            artifact_path.mkdir()
            with self.assertRaises(DisplayArtifactNotFoundError):
                build_display_manifest(
                    target=target,  # type: ignore[arg-type]
                    output_dir=tmp,
                )


if __name__ == "__main__":
    unittest.main()
