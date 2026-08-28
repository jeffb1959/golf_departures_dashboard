"""Tests du rendu visuel des départs de golf."""

from __future__ import annotations

from datetime import datetime
import tempfile
import os
import unittest
from zoneinfo import ZoneInfo

from PIL import Image, ImageFont

from app.display_service import DisplayDeparture, HourlyDisplayItem
from app.render_departures import (
    render_departures_image,
    save_departures_preview,
    wrap_text_to_lines,
)


def make_departure(
    *,
    reservation_id: str = "R1",
    title: str = "Prochain départ : Samedi 29 août 10:27 hrs",
    is_featured: bool = False,
    players_line: str = "Alice, Bob, Charlie",
    weather_mode: str = "daily",
    daily_summary: str | None = "Ciel clair et agréable.",
    hourly_items: tuple[HourlyDisplayItem, ...] = (),
) -> DisplayDeparture:
    return DisplayDeparture(
        reservation_id=reservation_id,
        departure_datetime=datetime(2026, 8, 29, 10, 27, tzinfo=ZoneInfo("America/Toronto")),
        is_featured=is_featured,
        title=title,
        players_line=players_line,
        weather_mode=weather_mode,
        daily_summary=daily_summary,
        hourly_items=hourly_items,
    )


def make_hourly_item(
    time_label: str,
    *,
    temperature: float | None = 16.0,
    precipitation_probability: int | None = 0,
    wind_speed: float | None = 15.0,
    wind_direction: str | None = "SO",
    icon_code: str | None = None,
) -> HourlyDisplayItem:
    return HourlyDisplayItem(
        time_label=time_label,
        condition="",
        temperature=temperature,
        precipitation_probability=precipitation_probability,
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        icon_code=icon_code,
    )


class RenderDeparturesImageTests(unittest.TestCase):
    def test_render_departures_image_returns_pillow_image(self):
        image = render_departures_image(())
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.mode, "1")

    def test_image_size_is_default_800x480(self):
        image = render_departures_image(())
        self.assertEqual(image.size, (800, 480))

    def test_empty_list_still_generates_image_with_message(self):
        image = render_departures_image(())
        values = set(image.getdata())
        self.assertEqual(len(values), 2)
        self.assertIn(0, values)

    def test_save_departures_preview_creates_png(self):
        departure = make_departure()
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "preview.png")
            save_departures_preview((departure,), output)
            self.assertTrue(os.path.exists(output))
            with Image.open(output) as saved:
                self.assertEqual(saved.format, "PNG")

    def test_daily_departure_renders_without_error(self):
        departure = make_departure(weather_mode="daily")
        image = render_departures_image((departure,))
        self.assertEqual(image.size, (800, 480))
        self.assertIsInstance(image, Image.Image)

    def test_hourly_departure_renders_without_error(self):
        departure = make_departure(
            weather_mode="hourly",
            hourly_items=(
                make_hourly_item("8h", temperature=16.0, precipitation_probability=0, wind_speed=15.0, wind_direction="SO"),
                make_hourly_item("9h", temperature=17.0, precipitation_probability=10, wind_speed=16.0, wind_direction="SO"),
            ),
        )
        image = render_departures_image((departure,))
        self.assertEqual(image.size, (800, 480))

    def test_multiple_departures_render(self):
        departure_1 = make_departure(
            reservation_id="R1",
            title="Prochain départ : Samedi 29 août 8:00 hrs",
            daily_summary="Temps clair.",
        )
        departure_2 = make_departure(
            reservation_id="R2",
            title="Dimanche 30 août 9:30 hrs",
            is_featured=False,
            weather_mode="daily",
            daily_summary="Ciel nuageux.",
            players_line="Dave, Éric, François",
        )
        departure_3 = make_departure(
            reservation_id="R3",
            title="Lundi 31 août 7:15 hrs",
            weather_mode="unavailable",
            daily_summary=None,
            players_line="Georges, Henri",
        )
        image = render_departures_image((departure_1, departure_2, departure_3))
        self.assertIsInstance(image, Image.Image)

    def test_unavailable_weather_is_stable(self):
        departure = make_departure(
            weather_mode="unavailable",
            daily_summary="",
            hourly_items=(),
        )
        image = render_departures_image((departure,))
        self.assertIsInstance(image, Image.Image)

    def test_long_daily_summary_is_wrapped(self):
        long_summary = (
            "Ciel variable avec passages nuageux puis éclaircies, "
            "vent du sud-sud-ouest modéré, possibilité d'humidité, UV "
            "élevé l'après-midi, brouillard local possible près des arbres."
        )
        departure = make_departure(weather_mode="daily", daily_summary=long_summary)
        image = render_departures_image((departure,), width=300, height=240)
        self.assertEqual(image.size, (300, 240))

    def test_six_departures_does_not_raise(self):
        departures = tuple(
            make_departure(reservation_id=f"R{i}", title=f"Prochain départ : Lundi {1 + i} août 8:{i:02d} hrs")
            for i in range(6)
        )
        image = render_departures_image(departures)
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.size, (800, 480))

    def test_dense_content_keeps_renderer_stable(self):
        departures = tuple(
            make_departure(
                reservation_id=f"R{i}",
                title="Prochain départ : Lundi 01 août 8:00 hrs",
                players_line="Jean, Jean-Pierre, Jean-Philippe, Jean-Michel, Jean-Claude, "
                "Émilie, Élodie, Étienne, Éric, Émile, François, Frédéric",
                weather_mode="daily",
                daily_summary=(
                    "Une très longue description météorologique avec beaucoup de mots pour vérifier "
                    "que le moteur de wrapping ne déborde pas du cadre, en gardant la lisibilité "
                    "du texte et sans faire planter le rendu."
                ),
            )
            for i in range(6)
        )
        image = render_departures_image(departures, width=480, height=320)
        self.assertIsInstance(image, Image.Image)
        self.assertEqual(image.size, (480, 320))

    def test_custom_dimensions(self):
        departure = make_departure()
        image = render_departures_image((departure,), width=600, height=360)
        self.assertEqual(image.size, (600, 360))

    def test_wrap_text_to_lines_respects_width(self):
        import PIL.ImageDraw
        dummy = Image.new("1", (100, 50), 1)
        draw = PIL.ImageDraw.ImageDraw(dummy)
        lines = wrap_text_to_lines(
            "Ce texte est suffisamment long pour nécessiter plusieurs lignes.",
            draw=draw,
            font=ImageFont.load_default(),
            max_width=40,
        )
        self.assertGreater(len(lines), 1)

    def test_input_tuple_is_not_modified(self):
        departures = [
            make_departure(reservation_id="R1", weather_mode="daily", daily_summary="Aperçu"),
            make_departure(
                reservation_id="R2",
                weather_mode="hourly",
                hourly_items=(make_hourly_item("8h"),),
            ),
        ]
        original = tuple(departures)
        render_departures_image(tuple(departures))
        self.assertEqual(tuple(departures), original)


if __name__ == "__main__":
    unittest.main()
