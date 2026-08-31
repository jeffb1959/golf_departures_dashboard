"""Tests de la couche d'abstraction des profils d'affichage."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import os
import unittest
from unittest.mock import patch

from PIL import Image

from app.display_targets.base import DisplayTarget
from app.display_targets.registry import (
    DEFAULT_DISPLAY_PROFILE,
    get_display_target,
)
from app.display_targets.waveshare_75_bw import Waveshare75BWDisplayTarget
from app.display_service import DisplayDeparture


class WaveshareDisplayTargetTests(unittest.TestCase):
    def test_default_profile_is_waveshare_75_bw(self):
        with patch.dict(os.environ, {}, clear=True):
            target = get_display_target()
        self.assertEqual(target.name, DEFAULT_DISPLAY_PROFILE)

    def test_explicit_profile_selection(self):
        target = get_display_target("waveshare_75_bw")
        self.assertEqual(target.name, "waveshare_75_bw")

    def test_display_profile_environment_variable(self):
        with patch.dict(os.environ, {"DISPLAY_PROFILE": "waveshare_75_bw"}):
            target = get_display_target()
        self.assertEqual(target.name, "waveshare_75_bw")

    def test_unknown_profile_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "Profil d'affichage inconnu"):
            get_display_target("inconnu")

    def test_profile_width_and_height(self):
        target = get_display_target("waveshare_75_bw")
        self.assertIsInstance(target, DisplayTarget)
        self.assertEqual(target.width, 800)
        self.assertEqual(target.height, 480)

    def test_payload_exact_size(self):
        target = get_display_target("waveshare_75_bw")
        payload = target.build_payload(())
        self.assertEqual(len(payload), 48_000)

    def test_all_white_payload_is_zero(self):
        target = get_display_target("waveshare_75_bw")
        if isinstance(target, Waveshare75BWDisplayTarget):
            image = Image.new("1", (target.width, target.height), 1)
            payload = target.encode_payload(image)
            self.assertEqual(payload, bytes(len(payload)))

    def test_all_black_payload_is_ff(self):
        target = get_display_target("waveshare_75_bw")
        if isinstance(target, Waveshare75BWDisplayTarget):
            image = Image.new("1", (target.width, target.height), 0)
            payload = target.encode_payload(image)
            self.assertEqual(payload, bytes([0xFF]) * len(payload))

    def test_msb_ordering_is_correct(self):
        target = get_display_target("waveshare_75_bw")
        if isinstance(target, Waveshare75BWDisplayTarget):
            left_black = Image.new("1", (target.width, target.height), 1)
            left_black.putpixel((0, 0), 0)
            payload_left = target.encode_payload(left_black)
            self.assertEqual(payload_left[0], 0x80)

            right_black = Image.new("1", (target.width, target.height), 1)
            right_black.putpixel((7, 0), 0)
            payload_right = target.encode_payload(right_black)
            self.assertEqual(payload_right[0], 0x01)

    def test_wrong_resolution_raises_clear_error(self):
        target = get_display_target("waveshare_75_bw")
        if isinstance(target, Waveshare75BWDisplayTarget):
            wrong_image = Image.new("1", (10, 10), 1)
            with self.assertRaisesRegex(
                ValueError,
                "Résolution invalide",
            ):
                target.encode_payload(wrong_image)

    def test_target_can_render_display_departures(self):
        departure = DisplayDeparture(
            reservation_id="R1",
            departure_datetime=datetime(2026, 8, 31, 9, 15, tzinfo=ZoneInfo("America/Toronto")),
            is_featured=True,
            title="Prochain départ : Lundi 31 août 9:15 hrs",
            players_line="Alice, Bob",
            weather_mode="daily",
            daily_summary="Ciel clair.",
            hourly_items=(),
        )
        target = get_display_target("waveshare_75_bw")
        image = target.render_departures_image((departure,))
        self.assertEqual(image.size, (target.width, target.height))
        self.assertEqual(image.mode, "1")

    def test_encode_does_not_modify_source_image(self):
        target = get_display_target("waveshare_75_bw")
        if isinstance(target, Waveshare75BWDisplayTarget):
            image = Image.new("1", (target.width, target.height), 1)
            image.putpixel((1, 1), 0)
            before = image.tobytes()
            _ = target.encode_payload(image)
            after = image.tobytes()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
