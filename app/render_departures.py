"""Rendu visuel b/n des départs de golf pour prévisualisation e-paper."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from app.display_service import DisplayDeparture, HourlyDisplayItem


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """Charge une police système, avec plusieurs alternatives robustes (Unicode)."""

    if bold:
        candidate_fonts = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
        )
    else:
        candidate_fonts = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
        )

    for font_path in candidate_fonts:
        path = Path(font_path)
        if not path.is_file():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue

    return ImageFont.load_default()


def _render_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    x: int,
    y: int,
    width: int,
    height: int,
    fill: int = 0,
    *,
    line_spacing: int = 2,
) -> int:
    lines = wrap_text_to_lines(text, font, width, draw)
    cursor = y
    sample_bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_height = sample_bbox[3] - sample_bbox[1] + line_spacing

    for line in lines:
        line_bbox = draw.textbbox((0, 0), line, font=font)
        if line_bbox[2] > width and line:
            # fallback hard protection when text is wider than width.
            line = line[:10]
        if cursor + line_height > height:
            return y
        draw.text((x, cursor), line, font=font, fill=fill)
        cursor += line_height
    return cursor


def _line_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return draw.textbbox((0, 0), text, font=font)[2]


def wrap_text_to_lines(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[str, ...]:
    """Retourne des lignes qui rentrent au mieux dans `max_width`."""

    if not text:
        return ("",)

    words = text.split()
    if not words:
        return (text.strip(),)

    lines: list[str] = []
    current = ""

    def append_current() -> None:
        nonlocal current
        if current:
            lines.append(current)
            current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _line_width(draw, candidate, font) <= max_width:
            current = candidate
            continue

        if not current:
            # Mot trop long: on le coupe caractère par caractère.
            chunk = ""
            for char in word:
                next_chunk = f"{chunk}{char}"
                if _line_width(draw, next_chunk, font) <= max_width:
                    chunk = next_chunk
                    continue
                if chunk:
                    lines.append(chunk)
                chunk = char
            if chunk:
                current = chunk
        else:
            append_current()
            current = word
            if _line_width(draw, current, font) > max_width:
                # mot ultra long, on coupe.
                chunk = ""
                rem = current
                for char in rem:
                    next_chunk = f"{chunk}{char}"
                    if _line_width(draw, next_chunk, font) <= max_width:
                        chunk = next_chunk
                        continue
                    lines.append(chunk)
                    chunk = char
                if chunk:
                    lines.append(chunk)
                current = ""
    append_current()
    if not lines:
        lines.append("")
    return tuple(lines)


def _hourly_item_to_compact_token(item: HourlyDisplayItem) -> str:
    if item.temperature is None:
        temperature = "?"
    else:
        temperature = f"{int(item.temperature)}°"
    if item.precipitation_probability is None:
        precip = "?"
    else:
        precip = f"{item.precipitation_probability}%"
    if item.wind_direction is None and item.wind_speed is None:
        wind = "?"
    elif item.wind_direction is None:
        wind = f"{int(item.wind_speed)}"
    elif item.wind_speed is None:
        wind = item.wind_direction
    else:
        wind = f"{item.wind_direction}{int(item.wind_speed)}"
    return f"{item.time_label} {temperature} {precip} {wind}"


def _render_single_departure(
    draw: ImageDraw.ImageDraw,
    departure: DisplayDeparture,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    featured: bool,
    featured_font: ImageFont.ImageFont,
    normal_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    weather_font: ImageFont.ImageFont | None = None,
) -> int:
    if y >= height:
        return y

    content_x = x
    content_width = width - x - x
    fill = 0
    weather_font = weather_font or small_font

    title_font = featured_font if featured else normal_font
    title_lines = wrap_text_to_lines(departure.title, title_font, content_width, draw)
    if not title_lines:
        title_lines = (departure.title,)
    title_font_size = draw.textbbox((0, 0), "Ag", font=title_font)
    line_height = title_font_size[3] - title_font_size[1] + 2
    if y + (line_height * len(title_lines)) > height:
        return y

    for line in title_lines:
        draw.text((content_x, y), line, font=title_font, fill=fill)
        y += line_height

    players_text = departure.players_line or ""
    y = _render_wrapped_text(
        draw=draw,
        text=players_text,
        font=small_font,
        x=content_x,
        y=y,
        width=content_width,
        height=height,
        fill=fill,
        line_spacing=2,
    )
    if players_text:
        y += 4

    if departure.weather_mode == "hourly":
        weather_label = "Météo de la ronde :"
        y = _render_wrapped_text(
            draw=draw,
            text=weather_label,
            font=weather_font,
            x=content_x,
            y=y,
            width=content_width,
            height=height,
            fill=fill,
            line_spacing=1,
        )
        hourly_text = " | ".join(_hourly_item_to_compact_token(item) for item in departure.hourly_items)
        y = _render_wrapped_text(
            draw=draw,
            text=hourly_text,
            font=weather_font,
            x=content_x,
            y=y + 2,
            width=content_width,
            height=height,
            fill=fill,
            line_spacing=1,
        )
    elif departure.weather_mode == "daily":
        y = _render_wrapped_text(
            draw=draw,
            text=departure.daily_summary or "",
            font=small_font,
            x=content_x,
            y=y,
            width=content_width,
            height=height,
            fill=fill,
            line_spacing=1,
        )
    else:
        y = _render_wrapped_text(
            draw=draw,
            text="Météo non disponible",
            font=small_font,
            x=content_x,
            y=y,
            width=content_width,
            height=height,
            fill=fill,
            line_spacing=1,
        )
    return y


def render_departures_image(
    departures: tuple[DisplayDeparture, ...] | list[DisplayDeparture],
    *,
    width: int = 800,
    height: int = 480,
) -> Image.Image:
    """Construit une image 1-bit avec un rendu simple de la liste des départs."""

    if width < 200 or height < 150:
        raise ValueError("La taille minimale doit être au moins 200x150.")

    image = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(image, mode="1")

    margin = 16
    usable_width = width - (margin * 2)

    title_font = _load_font(25, bold=True)
    featured_title_font = _load_font(30, bold=True)
    normal_title_font = _load_font(20, bold=True)
    text_font = _load_font(16)

    title = "Départs de golf"
    draw.text((margin, 12), title, font=title_font, fill=0)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    y = 10 + (title_bbox[3] - title_bbox[1]) + 8

    if not departures:
        _render_wrapped_text(
            draw=draw,
            text="Aucun départ à afficher",
            font=text_font,
            x=margin,
            y=max(y, 80),
            width=usable_width,
            height=height - margin,
            fill=0,
            line_spacing=2,
        )
        return image

    for index, departure in enumerate(departures):
        y_cursor_before = y
        feature = index == 0
        y_next = _render_single_departure(
            draw,
            departure,
            margin,
            y,
            width,
            height - margin,
            featured=feature,
            featured_font=featured_title_font if feature else normal_title_font,
            normal_font=normal_title_font,
            small_font=text_font,
            weather_font=title_font,
        )
        if y_next <= y_cursor_before:
            break
        y = y_next + (11 if feature else 8)
        if y > height - 20:
            break

        if index != len(departures) - 1 and y < height - 5:
            draw.line((margin, y, width - margin, y), fill=0, width=1)
            y += 6

    return image


def save_departures_preview(
    departures: tuple[DisplayDeparture, ...] | list[DisplayDeparture],
    output_path: str,
    *,
    width: int = 800,
    height: int = 480,
) -> None:
    """Exporte une prévisualisation PNG sur disque."""

    image = render_departures_image(departures, width=width, height=height)
    image.save(output_path, format="PNG")
