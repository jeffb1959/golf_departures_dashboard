"""Registry pour la sélection du profil d'affichage."""

from __future__ import annotations

import os

from app.display_targets.waveshare_75_bw import waveshare_75_bw

DEFAULT_DISPLAY_PROFILE = "waveshare_75_bw"

_REGISTERED_DISPLAY_TARGETS = {
    waveshare_75_bw.name: waveshare_75_bw,
}


def get_display_target(profile_name: str | None = None):
    """Retourne le profil à partir d'un nom explicite ou de DISPLAY_PROFILE."""

    selected = (profile_name or os.getenv("DISPLAY_PROFILE", "")).strip()
    if not selected:
        selected = DEFAULT_DISPLAY_PROFILE

    try:
        return _REGISTERED_DISPLAY_TARGETS[selected]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTERED_DISPLAY_TARGETS))
        raise ValueError(
            f"Profil d'affichage inconnu: {selected!r}. "
            f"Profils disponibles: {available}."
        ) from exc
