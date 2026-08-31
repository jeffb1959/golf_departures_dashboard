"""Orchestration complète du rafraîchissement du dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sys
from zoneinfo import ZoneInfo

from app.display_artifact import generate_display_artifact, DisplayArtifactResult
from app.reservation_refresh import ReservationRefreshResult, refresh_reservation_cache


LOCAL_TIMEZONE = ZoneInfo("America/Toronto")


@dataclass(frozen=True)
class DashboardRefreshResult:
    """Résultat structuré d'une actualisation complète du dashboard."""

    reservations_count: int
    reservations_updated_at: datetime
    display_profile: str
    display_payload_size: int
    display_departures_count: int
    display_generated_at: datetime


@dataclass(frozen=True)
class DashboardRefreshError(ValueError):
    """Erreur structurée d'orchestration du rafraîchissement."""

    stage: str

    def __str__(self) -> str:
        return f"Échec lors de la phase {self.stage}."


def refresh_dashboard(
    *,
    now: datetime | None = None,
    refresh_reservations_fn=refresh_reservation_cache,
    generate_display_fn=generate_display_artifact,
) -> DashboardRefreshResult:
    """Rafraîchit le cache puis génère l'artefact d'affichage."""

    reference_now = now if now is not None else datetime.now(tz=LOCAL_TIMEZONE)

    try:
        reservations_result: ReservationRefreshResult = refresh_reservations_fn(now=reference_now)
    except Exception as exc:  # pragma: no cover - délégué aux tests pour la granularité
        raise DashboardRefreshError(stage="reservations") from exc

    try:
        display_result: DisplayArtifactResult = generate_display_fn(now=reference_now)
    except Exception as exc:
        raise DashboardRefreshError(stage="display") from exc

    return DashboardRefreshResult(
        reservations_count=reservations_result.reservations_count,
        reservations_updated_at=reservations_result.updated_at,
        display_profile=display_result.profile_name,
        display_payload_size=display_result.payload_size,
        display_departures_count=display_result.departures_count,
        display_generated_at=display_result.generated_at,
    )


def main() -> int:
    """Point d'entrée CLI pour le rafraîchissement complet."""

    try:
        result = refresh_dashboard()
    except DashboardRefreshError:
        print("Échec du rafraîchissement du dashboard.", file=sys.stderr)
        return 1

    print(f"reservations={result.reservations_count}")
    print(f"reservations_updated_at={result.reservations_updated_at.isoformat()}")
    print(f"display_profile={result.display_profile}")
    print(f"display_payload_size={result.display_payload_size}")
    print(f"display_departures_count={result.display_departures_count}")
    print(f"display_generated_at={result.display_generated_at.isoformat()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
