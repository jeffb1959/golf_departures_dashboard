"""Cache JSON persistant des réservations Chronogolf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import os
import tempfile

from app import reservation_parser


DEFAULT_CACHE_PATH = Path("/data/reservation_cache.json")
CURRENT_CACHE_VERSION = 1


class ReservationCacheError(ValueError):
    """Erreur de lecture ou de validation du cache de réservations."""


@dataclass(frozen=True)
class ReservationCache:
    """Contenu validé d'un cache chargé depuis le disque."""

    version: int
    updated_at: datetime
    reservations: list[reservation_parser.GolfReservation]


def reservation_to_record(
    reservation: reservation_parser.GolfReservation,
) -> dict[str, Any]:
    """Convertit une réservation en enregistrement JSON sérialisable."""

    return {
        "date": reservation.date.isoformat(),
        "heure": reservation.heure.isoformat(timespec="minutes"),
        "joueurs": list(reservation.joueurs),
        "reservation_id": reservation.reservation_id,
    }


def reservation_from_record(
    raw: Mapping[str, object],
) -> reservation_parser.GolfReservation:
    """Reconstruit une réservation depuis un enregistrement JSON."""

    date_value = raw.get("date")
    if not isinstance(date_value, str) or not date_value:
        raise ReservationCacheError("Champ `date` manquant ou invalide.")

    time_value = raw.get("heure")
    if not isinstance(time_value, str) or not time_value:
        raise ReservationCacheError("Champ `heure` manquant ou invalide.")

    players_value = raw.get("joueurs")
    if not isinstance(players_value, list):
        raise ReservationCacheError("Champ `joueurs` manquant ou invalide.")
    players = [player for player in players_value if isinstance(player, str)]
    if len(players) != len(players_value) or not players:
        raise ReservationCacheError("Champ `joueurs` manquant ou invalide.")

    reservation_id = raw.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise ReservationCacheError("Champ `reservation_id` manquant ou invalide.")

    try:
        reservation_date = date.fromisoformat(date_value)
    except ValueError as exc:
        raise ReservationCacheError("Champ `date` invalide.") from exc
    try:
        reservation_time = time.fromisoformat(time_value)
    except ValueError as exc:
        raise ReservationCacheError("Champ `heure` invalide.") from exc

    return reservation_parser.GolfReservation(
        date=reservation_date,
        heure=reservation_time,
        joueurs=players,
        reservation_id=reservation_id,
    )


def _validate_cache_payload(
    payload: Any,
) -> tuple[datetime, list[reservation_parser.GolfReservation]]:
    if not isinstance(payload, dict):
        raise ReservationCacheError("Le cache n'a pas le bon format.")

    version = payload.get("version")
    if version != CURRENT_CACHE_VERSION:
        raise ReservationCacheError(f"Version de cache non supportée: {version!r}.")

    updated_at_value = payload.get("updated_at")
    if not isinstance(updated_at_value, str):
        raise ReservationCacheError("Champ `updated_at` manquant ou invalide.")
    try:
        updated_at = datetime.fromisoformat(updated_at_value)
    except ValueError as exc:
        raise ReservationCacheError("Champ `updated_at` invalide.") from exc

    records = payload.get("reservations")
    if not isinstance(records, list):
        raise ReservationCacheError("Champ `reservations` manquant ou invalide.")
    if not all(isinstance(record, Mapping) for record in records):
        raise ReservationCacheError("Entrée de réservation invalide.")

    return updated_at, [reservation_from_record(record) for record in records]


def load_reservations_cache(
    *, cache_path: Path | str = DEFAULT_CACHE_PATH
) -> ReservationCache | None:
    """Charge et valide le cache, ou retourne ``None`` s'il est absent."""

    path = Path(cache_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReservationCacheError("Le cache contient un JSON invalide.") from exc
    except OSError as exc:
        raise ReservationCacheError("Impossible de lire le cache.") from exc

    updated_at, reservations = _validate_cache_payload(payload)
    return ReservationCache(
        version=CURRENT_CACHE_VERSION,
        updated_at=updated_at,
        reservations=reservations,
    )


def _write_cache_atomic(path: Path, content: dict[str, Any]) -> None:
    """Écrit le contenu dans un fichier temporaire avant remplacement atomique."""

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(content, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
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


def save_reservations_cache(
    reservations: Iterable[reservation_parser.GolfReservation],
    *,
    updated_at: datetime | None = None,
    cache_path: Path | str = DEFAULT_CACHE_PATH,
) -> ReservationCache:
    """Sauvegarde les réservations et retourne le cache relu et validé."""

    timestamp = updated_at or datetime.now()
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CURRENT_CACHE_VERSION,
        "updated_at": timestamp.isoformat(timespec="seconds"),
        "reservations": [reservation_to_record(item) for item in reservations],
    }
    _write_cache_atomic(path, payload)
    try:
        path.chmod(0o600)
    except OSError:
        pass

    loaded = load_reservations_cache(cache_path=path)
    if loaded is None:  # pragma: no cover - impossible après une écriture réussie
        raise ReservationCacheError("Le cache sauvegardé est introuvable.")
    return loaded
