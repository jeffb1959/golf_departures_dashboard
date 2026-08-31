"""Profil Waveshare 7.5" en 1 bit (monochrome)."""

from __future__ import annotations

from PIL import Image

from app.display_service import DisplayDeparture
from app.render_departures import render_departures_image

from app.display_targets.base import DisplayTarget


class Waveshare75BWDisplayTarget(DisplayTarget):
    """Profil Waveshare 7.5" noir et blanc, sortie RAW 1 bit."""

    name = "waveshare_75_bw"
    width = 800
    height = 480
    color_mode = "monochrome"
    output_format = "raw_1bit"
    file_extension = ".bin"
    mime_type = "application/octet-stream"

    expected_payload_bytes = (width * height) // 8

    _invert_table = bytes(255 - i for i in range(256))

    def render_departures_image(
        self,
        departures: tuple[DisplayDeparture, ...] | list[DisplayDeparture],
    ) -> Image.Image:
        image = render_departures_image(departures, width=self.width, height=self.height)
        if image.mode != "1":
            raise ValueError(f"La sortie render_departures_image doit être en mode '1', reçu {image.mode!r}.")
        return image

    def encode_payload(self, image: Image.Image) -> bytes:
        if image.mode != "1":
            raise ValueError("Le payload Waveshare attend une image Pillow en mode '1'.")
        if image.size != (self.width, self.height):
            raise ValueError(
                "Résolution invalide pour waveshare_75_bw: "
                f"attendu {(self.width, self.height)}, reçu {image.size}."
            )

        payload = image.tobytes()
        if len(payload) != self.expected_payload_bytes:
            raise ValueError(
                "Payload 1-bit inattendu pour waveshare_75_bw: "
                f"attendu {self.expected_payload_bytes}, reçu {len(payload)}."
            )

        # Inversion: Pillow mode '1' -> 0 = noir, 1 = blanc,
        # alors que le payload Waveshare attend : 0 = blanc, 1 = noir.
        return payload.translate(self._invert_table)


waveshare_75_bw = Waveshare75BWDisplayTarget()
