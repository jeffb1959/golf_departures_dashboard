"""Orchestration de génération d'artefact d'affichage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import sys
import tempfile
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from app.departures_service import filter_relevant_departures
from app.display_service import DisplayDeparture, build_display_departures
from app.display_targets import get_display_target
from app.display_targets.base import DisplayTarget
from app.reservation_cache import (
    DEFAULT_CACHE_PATH,
    ReservationCache,
    load_reservations_cache,
)
from app.weather_client import EnvironmentCanadaForecast, HomeAssistantWeatherConfig, get_forecasts
from app.weather_client import load_weather_config


DEFAULT_DISPLAY_OUTPUT_DIR = Path("/data")
LOCAL_TIMEZONE = ZoneInfo("America/Toronto")


@dataclass(frozen=True)
class DisplayArtifactResult:
    """Résultat d'une génération d'artefact d'affichage."""

    profile_name: str
    output_path: Path
    payload_size: int
    departures_count: int
    generated_at: datetime


def _write_atomic_bytes(path: Path, payload: bytes) -> None:
    """Écrit des octets sur disque de manière atomique."""

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise


def _build_payload_from_target(
    departures: Iterable[DisplayDeparture] | tuple[DisplayDeparture, ...],
    target: DisplayTarget,
) -> bytes:
    return target.build_payload(tuple(departures))


def _build_output_path(output_dir: Path | str, target: DisplayTarget) -> Path:
    output_directory = Path(output_dir)
    output_directory.mkdir(parents=True, exist_ok=True)
    return output_directory / f"departures_display{target.file_extension}"


def build_display_artifact(
    departures: Iterable[DisplayDeparture] | tuple[DisplayDeparture, ...],
    *,
    target: DisplayTarget,
    output_dir: Path | str = DEFAULT_DISPLAY_OUTPUT_DIR,
    generated_at: datetime | None = None,
) -> DisplayArtifactResult:
    """Construit et écrit l'artefact à partir de départs déjà préparés."""

    departure_list = tuple(departures)
    payload = _build_payload_from_target(departure_list, target)
    output_path = _build_output_path(output_dir, target)
    _write_atomic_bytes(output_path, payload)
    return DisplayArtifactResult(
        profile_name=target.name,
        output_path=output_path,
        payload_size=len(payload),
        departures_count=len(departure_list),
        generated_at=generated_at or datetime.now(tz=LOCAL_TIMEZONE),
    )


def generate_display_artifact(
    *,
    output_dir: Path | str = DEFAULT_DISPLAY_OUTPUT_DIR,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    profile_name: str | None = None,
    now: datetime | None = None,
    load_cache_fn: Callable[..., ReservationCache | None] = load_reservations_cache,
    filter_departures_fn: Callable[..., list] = filter_relevant_departures,
    load_weather_config_fn: Callable[..., HomeAssistantWeatherConfig] = load_weather_config,
    get_forecasts_fn: Callable[[HomeAssistantWeatherConfig], EnvironmentCanadaForecast] = get_forecasts,
    build_display_departures_fn: Callable[..., tuple[DisplayDeparture, ...]] = build_display_departures,
    get_display_target_fn: Callable[[str | None], DisplayTarget] = get_display_target,
) -> DisplayArtifactResult:
    """Génère l'artefact final depuis le cache et la configuration applicative."""

    cache = load_cache_fn(cache_path=cache_path)
    if cache is None:
        raise RuntimeError(f"Cache des réservations introuvable: {cache_path}")

    reference_now = now if now is not None else datetime.now(tz=LOCAL_TIMEZONE)
    relevant_departures = filter_departures_fn(cache.reservations, now=reference_now)

    weather_config = load_weather_config_fn()
    forecast = get_forecasts_fn(weather_config)
    display_departures = build_display_departures_fn(
        relevant_departures,
        forecast,
        limit=5,
    )

    target = get_display_target_fn(profile_name)
    return build_display_artifact(
        display_departures,
        target=target,
        output_dir=output_dir,
        generated_at=reference_now,
    )


def main() -> int:
    """Point d'entrée CLI."""

    try:
        result = generate_display_artifact()
    except Exception as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 1

    print(f"profile={result.profile_name}")
    print(f"output_path={result.output_path}")
    print(f"payload_size={result.payload_size}")
    print(f"departures_count={result.departures_count}")
    print(f"generated_at={result.generated_at.isoformat()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
