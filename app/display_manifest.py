"""Manifest metadata for display artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from app.display_artifact import DEFAULT_DISPLAY_OUTPUT_DIR, get_display_artifact_path
from app.display_targets.base import DisplayTarget


LOCAL_TIMEZONE = ZoneInfo("America/Toronto")
DEFAULT_ARTIFACT_URL = "/api/display/artifact"
DEFAULT_SCHEMA_VERSION = 1
_HASH_CHUNK_SIZE = 65_536


@dataclass(frozen=True)
class DisplayManifest:
    """Métadonnées sérialisables d'un artefact d'affichage."""

    schema_version: int
    profile: str
    width: int
    height: int
    output_format: str
    mime_type: str
    payload_size: int
    sha256: str
    generated_at: datetime
    artifact_url: str = DEFAULT_ARTIFACT_URL

    def to_dict(self) -> dict[str, object]:
        """Transforme le manifeste en dictionnaire JSON sérialisable."""

        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "width": self.width,
            "height": self.height,
            "output_format": self.output_format,
            "mime_type": self.mime_type,
            "payload_size": self.payload_size,
            "sha256": self.sha256,
            "generated_at": self.generated_at.isoformat(),
            "artifact_url": self.artifact_url,
        }


class DisplayArtifactNotFoundError(FileNotFoundError):
    """Erreur levée si l'artefact attendu n'existe pas ou n'est pas un fichier."""


def _compute_file_hash(handle) -> str:
    hasher = hashlib.sha256()
    while True:
        chunk = handle.read(_HASH_CHUNK_SIZE)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()


def build_display_manifest(
    *,
    target: DisplayTarget,
    output_dir: str | Path = DEFAULT_DISPLAY_OUTPUT_DIR,
    artifact_url: str = DEFAULT_ARTIFACT_URL,
) -> DisplayManifest:
    """Construit le manifeste à partir de l'artefact déjà présent.

    Important: ``generated_at`` est basé sur le ``mtime`` du fichier artefact lu.
    """

    artifact_path = get_display_artifact_path(target, output_dir=output_dir)
    if not artifact_path.exists() or not artifact_path.is_file():
        raise DisplayArtifactNotFoundError(
            f"Artefact introuvable pour le profil {target.name!r}: {artifact_path}"
        )

    with open(artifact_path, "rb") as handle:
        stats = os.fstat(handle.fileno())
        payload_size = stats.st_size
        # Dérive le timestamp de génération depuis le mtime de l'artefact lu.
        generated_at = datetime.fromtimestamp(stats.st_mtime, tz=LOCAL_TIMEZONE)
        payload_hash = _compute_file_hash(handle)

    return DisplayManifest(
        schema_version=DEFAULT_SCHEMA_VERSION,
        profile=target.name,
        width=target.width,
        height=target.height,
        output_format=target.output_format,
        mime_type=target.mime_type,
        payload_size=payload_size,
        sha256=payload_hash,
        generated_at=generated_at,
        artifact_url=artifact_url,
    )
