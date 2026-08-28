"""Orchestration du rafraîchissement du cache Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys

from app.chronogolf_client import ChronogolfClient, ImapConfig, load_imap_config
from app.reservation_cache import DEFAULT_CACHE_PATH, save_reservations_cache


@dataclass(frozen=True)
class ReservationRefreshResult:
    """Résultat structuré d'un rafraîchissement du cache."""

    reservations_count: int
    updated_at: datetime


def refresh_reservation_cache(
    *,
    now: datetime | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
    client_factory=ChronogolfClient,
    config: ImapConfig | None = None,
) -> ReservationRefreshResult:
    """Récupère les réservations puis remplace le cache après succès IMAP."""

    refresh_time = now if now is not None else datetime.now()
    imap_config = config if config is not None else load_imap_config()
    client = client_factory(imap_config)
    reservations = client.get_upcoming_reservations(
        reference=refresh_time,
        today=refresh_time.date(),
    )
    cache = save_reservations_cache(
        reservations,
        updated_at=refresh_time,
        cache_path=cache_path,
    )
    return ReservationRefreshResult(
        reservations_count=len(cache.reservations),
        updated_at=cache.updated_at,
    )


def main() -> int:
    """Rafraîchit le cache depuis la ligne de commande."""

    try:
        result = refresh_reservation_cache()
    except Exception:
        print("Erreur: rafraîchissement du cache impossible.", file=sys.stderr)
        return 1

    print(f"reservations_count={result.reservations_count}")
    print(f"updated_at={result.updated_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
