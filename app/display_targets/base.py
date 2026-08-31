"""Abstractions communes des profils d'affichage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from PIL import Image

from app.display_service import DisplayDeparture


class DisplayTarget(ABC):
    """Contrat commun pour les profils d'écran supportés."""

    name: str
    width: int
    height: int
    color_mode: str
    output_format: str
    file_extension: str
    mime_type: str

    @abstractmethod
    def render_departures_image(
        self,
        departures: tuple[DisplayDeparture, ...] | list[DisplayDeparture],
    ) -> Image.Image:
        """Retourne l'image de base à partir d'une liste de départs."""

        raise NotImplementedError

    @abstractmethod
    def encode_payload(self, image: Image.Image) -> bytes:
        """Encode l'image rendue dans le format final du profil."""

        raise NotImplementedError

    def build_payload(
        self,
        departures: tuple[DisplayDeparture, ...] | list[DisplayDeparture],
    ) -> bytes:
        """Construit le payload final directement depuis les données métiers."""

        image = self.render_departures_image(departures)
        return self.encode_payload(image)
