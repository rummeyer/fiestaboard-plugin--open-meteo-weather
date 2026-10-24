"""Wetter plugin for FiestaBoard.

Puts the weather for one set of coordinates on the board: the current
condition and temperature, today's low and high, and a week at a glance as one
colored tile per day — green for a dry, sunny day, yellow for a grey one, red
for rain, snow or thunder. Laid out for the board it is rendering on, so the
same plugin fits a Note (15x3) and a Flagship (22x6).

Forecasts come from Open-Meteo (https://open-meteo.com): free, no API key, and
addressed by latitude and longitude, which is exactly what the settings ask
for. Open-Meteo also resolves the location's own timezone (``timezone=auto``),
so "today" and the weekday names are the location's, not the server's.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import requests
from src.plugins.base import PluginBase, PluginResult

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 10

# fetch_data runs once per board in a thread pool, so a Note and a Flagship
# showing the same location would otherwise ask Open-Meteo twice in the same
# second. Long enough to cover one render pass, short enough never to stand in
# for the platform's own refresh interval.
SHARED_CACHE_SECONDS = 120

# Board geometry assumed outside a board-scoped render (unit tests, the
# /plugins/{id}/data endpoint). Flagship is the larger shape, so a layout built
# for it never silently loses a row.
FALLBACK_WIDTH = 22
FALLBACK_HEIGHT = 6

# The full layout — weekday names over two-tile bars over the daily highs —
# needs seven two-tile columns with a gap between them, and six rows.
WIDE_MIN_WIDTH = 20
WIDE_MIN_HEIGHT = 6

WEEK_DAYS = 7

# Where the week overview starts. "monday" is the calendar week, Monday to
# Sunday, with the days already past filled in from Open-Meteo's own record of
# them (``past_days``); "today" and "tomorrow" are rolling seven-day windows.
WEEK_STARTS = ("monday", "today", "tomorrow")
DEFAULT_WEEK_START = "monday"
# Six past days cover every Monday this week could have started on. The
# location's weekday is only known once Open-Meteo has answered with its
# timezone, so the window is cut afterwards, in `week_window`.
PAST_DAYS = WEEK_DAYS - 1

# Characters the board can flap. Anything else is dropped rather than sent as a
# wrong tile. Reference: src/board_chars.py in FiestaBoard.
BOARD_CHARSET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 !@#$()-+&=;:'\"%,./?°")

UMLAUT_EXPAND = {"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS"}
UMLAUT_STRIP = {"Ä": "A", "Ö": "O", "Ü": "U", "ß": "SS"}

# Tile 62 is ° on a Flagship and a heart (or nothing) on a Note — the same
# code, different print. "auto" therefore drops the sign on note-shaped boards.
DEGREE = "°"
NOTE_DEVICE_TYPES = ("note", "note_array")

COLOR_TILES = {
    "red": "{63}",
    "orange": "{64}",
    "yellow": "{65}",
    "green": "{66}",
    "blue": "{67}",
    "violet": "{68}",
    # Tile 69 contrasts with the board: white on a black board, black on a
    # white one. Tile 70 is the board's own color, so it reads as a gap.
    "contrast": "{69}",
    "background": "{70}",
    # Saved by 1.2.x, before the two were named for what they show.
    "white": "{69}",
}

LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"
UNITS = ("metric", "imperial")
DEFAULT_UNITS = "metric"
DEGREE_CHOICES = ("on", "auto", "off")
DEFAULT_DEGREE = "on"

# What a day is rated as, and the color each rating gets unless the user picks
# another one.
GOOD = "good"
MIXED = "mixed"
BAD = "bad"
# The contrast tile is the most neutral one the board has, and reads as
# "nothing special" between the green and the red.
DEFAULT_COLORS = {GOOD: "green", MIXED: "contrast", BAD: "red"}

# Today's low and high are marked cold and hot instead of being labelled.
COLD_TILE = COLOR_TILES["blue"]
HOT_TILE = COLOR_TILES["red"]

# Below this much precipitation a "rain" day is rated grey, not wet. Open-Meteo
# reports the most severe code of the day, so a single drizzle hour at 6am
# turns the whole day into code 51 with 0.1 mm to show for it.
DEFAULT_RAIN_THRESHOLD_MM = 1.0

# WMO weather interpretation codes, as Open-Meteo documents them.
DRY_CODES = frozenset({0, 1})
GREY_CODES = frozenset({2, 3, 45, 48})

# Board labels per WMO code. Kept at ten tiles or fewer so that the label and
# a temperature like "-12" share a Note's 15-tile row without truncation.
CONDITIONS = {
    "de": {
        0: "SONNIG",
        1: "HEITER",
        2: "BEWÖLKT",
        3: "BEDECKT",
        45: "NEBEL",
        48: "NEBEL",
        51: "NIESEL",
        53: "NIESEL",
        55: "NIESEL",
        56: "EISREGEN",
        57: "EISREGEN",
        61: "REGEN",
        63: "REGEN",
        65: "STARKREGEN",
        66: "EISREGEN",
        67: "EISREGEN",
        71: "SCHNEE",
        73: "SCHNEE",
        75: "SCHNEE",
        77: "SCHNEE",
        80: "SCHAUER",
        81: "SCHAUER",
        82: "STARKREGEN",
        85: "SCHNEE",
        86: "SCHNEE",
        95: "GEWITTER",
        96: "GEWITTER",
        99: "GEWITTER",
    },
    "en": {
        0: "SUNNY",
        1: "FAIR",
        2: "CLOUDY",
        3: "OVERCAST",
        45: "FOG",
        48: "FOG",
        51: "DRIZZLE",
        53: "DRIZZLE",
        55: "DRIZZLE",
        56: "ICY RAIN",
        57: "ICY RAIN",
        61: "RAIN",
        63: "RAIN",
        65: "HEAVY RAIN",
        66: "ICY RAIN",
        67: "ICY RAIN",
        71: "SNOW",
        73: "SNOW",
        75: "SNOW",
        77: "SNOW",
        80: "SHOWERS",
        81: "SHOWERS",
        82: "HEAVY RAIN",
        85: "SNOW",
        86: "SNOW",
        95: "THUNDER",
        96: "THUNDER",
        99: "THUNDER",
    },
}
# A clear sky at night is not sunny.
CLEAR_NIGHT = {"de": "KLAR", "en": "CLEAR"}

# Six tiles or fewer, for when the full word does not fit next to the
# temperature and humidity: a Note's 15 tiles minus " 12°C 71%" leave six.
# Only the labels longer than that need an entry.
SHORT_CONDITIONS = {
    "de": {
        "BEWÖLKT": "WOLKIG",
        "BEDECKT": "TRÜB",
        "EISREGEN": "GLATT",
        "STARKREGEN": "GUSS",
        "SCHAUER": "REGEN",
        "GEWITTER": "BLITZ",
    },
    "en": {
        "OVERCAST": "GREY",
        "DRIZZLE": "RAIN",
        "ICY RAIN": "ICE",
        "HEAVY RAIN": "POUR",
        "SHOWERS": "SHOWER",
        "THUNDER": "STORM",
    },
}

WEEKDAYS = {
    "de": ("MO", "DI", "MI", "DO", "FR", "SA", "SO"),
    "en": ("MO", "TU", "WE", "TH", "FR", "SA", "SU"),
}

WORDS = {
    "de": {"rain": "REGEN", "wind": "WIND"},
    "en": {"rain": "RAIN", "wind": "WIND"},
}


class WetterError(Exception):
    """Open-Meteo could not be reached or answered with something unusable."""


@dataclass(frozen=True)
class Day:
    """One day of the forecast, in the units it was requested in."""

    day: date
    code: int | None = None
    high: float | None = None
    low: float | None = None
    rain: float | None = None
    rain_chance: int | None = None


@dataclass(frozen=True)
class Forecast:
    """Current conditions plus the daily series, oldest day first.

    The series starts with whatever past days were asked for; today sits at
    that index (see `days_requested`).
    """

    temperature: float | None = None
    feels_like: float | None = None
    humidity: int | None = None
    wind: float | None = None
    code: int | None = None
    is_day: bool = True
    days: list[Day] = field(default_factory=list)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def parse_coordinates(value: Any) -> tuple[float, float] | None:
    """Read ``"52.52, 13.405"`` — the format a map app copies — as (lat, lon).

    Also takes a semicolon or plain whitespace as the separator. ``None`` when
    the text is not two numbers or either is outside the globe.
    """
    if not isinstance(value, str):
        return None
    parts = value.replace(";", ",").replace(",", " ").split()
    if len(parts) != 2:
        return None
    try:
        latitude, longitude = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    """*value* if it is one of *choices*, otherwise *default*."""
    return value if value in choices else default


# --------------------------------------------------------------------------
# Open-Meteo
# --------------------------------------------------------------------------


def request_params(latitude: float, longitude: float, units: str, week_start: str) -> dict[str, Any]:
    """Query string for one forecast call.

    Open-Meteo converts units itself, so imperial is asked for rather than
    computed here.
    """
    past, ahead = days_requested(week_start)
    params: dict[str, Any] = {
        "latitude": round(latitude, 4),
        "longitude": round(longitude, 4),
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
        "timezone": "auto",
        "forecast_days": ahead,
    }
    if past:
        params["past_days"] = past
    if units == "imperial":
        params.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
    return params


def days_requested(week_start: str) -> tuple[int, int]:
    """(past days, forecast days) a week start needs. Today counts as a forecast day."""
    if week_start == "monday":
        return PAST_DAYS, WEEK_DAYS
    if week_start == "tomorrow":
        return 0, WEEK_DAYS + 1
    return 0, WEEK_DAYS


def week_window(days: list[Day], today_index: int, week_start: str) -> list[Day]:
    """The seven days the overview shows, cut from what Open-Meteo returned.

    *today_index* is where today sits in *days* — the number of past days that
    were asked for. A Monday week reaches back ``weekday()`` days from there.
    """
    if week_start == "monday":
        start = today_index - days[today_index].day.weekday()
    elif week_start == "tomorrow":
        start = today_index + 1
    else:
        start = today_index
    return days[max(start, 0) :][:WEEK_DAYS]


def _at(values: Any, index: int) -> Any:
    """``values[index]``, or ``None`` when the series is missing or too short."""
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def parse_forecast(body: dict[str, Any]) -> Forecast:
    """Turn an Open-Meteo response into a :class:`Forecast`.

    A model that has no value for some hour sends ``null`` for it; those stay
    ``None`` and the board leaves the spot blank rather than showing a zero.
    """
    daily = body.get("daily") or {}
    dates = daily.get("time")
    if not isinstance(dates, list) or not dates:
        raise WetterError("Open-Meteo returned no daily forecast")

    days = []
    for index, raw in enumerate(dates):
        try:
            day = date.fromisoformat(str(raw))
        except ValueError as error:
            raise WetterError(f"Open-Meteo returned an unreadable date: {raw!r}") from error
        days.append(
            Day(
                day=day,
                code=_int(_at(daily.get("weather_code"), index)),
                high=_float(_at(daily.get("temperature_2m_max"), index)),
                low=_float(_at(daily.get("temperature_2m_min"), index)),
                rain=_float(_at(daily.get("precipitation_sum"), index)),
                rain_chance=_int(_at(daily.get("precipitation_probability_max"), index)),
            )
        )

    current = body.get("current") or {}
    return Forecast(
        temperature=_float(current.get("temperature_2m")),
        feels_like=_float(current.get("apparent_temperature")),
        humidity=_int(current.get("relative_humidity_2m")),
        wind=_float(current.get("wind_speed_10m")),
        code=_int(current.get("weather_code")),
        is_day=current.get("is_day", 1) != 0,
        days=days,
    )


_shared_lock = threading.Lock()
_shared_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


def fetch_forecast_body(params: dict[str, Any]) -> dict[str, Any]:
    """Call Open-Meteo, sharing one answer between boards that ask together."""
    key = tuple(sorted(params.items()))
    with _shared_lock:
        cached = _shared_cache.get(key)
        if cached and time.monotonic() - cached[0] < SHARED_CACHE_SECONDS:
            return cached[1]

        try:
            response = requests.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
        except requests.RequestException as error:
            raise WetterError(f"Open-Meteo is unreachable: {error}") from error
        try:
            body = response.json()
        except ValueError as error:
            raise WetterError(f"Open-Meteo answered HTTP {response.status_code} without JSON") from error
        if response.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            reason = body.get("reason") if isinstance(body, dict) else None
            raise WetterError(f"Open-Meteo refused the request: {reason or f'HTTP {response.status_code}'}")

        _shared_cache[key] = (time.monotonic(), body)
        return body


def clear_shared_cache() -> None:
    """Forget every shared answer — for tests and config changes."""
    with _shared_lock:
        _shared_cache.clear()


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


def to_board_text(text: str, umlauts: str = "expand") -> str:
    """Uppercase *text* and reduce it to characters the board can display."""
    table = UMLAUT_STRIP if umlauts == "strip" else UMLAUT_EXPAND
    text = str(text).upper()
    for source, replacement in table.items():
        text = text.replace(source, replacement)
    return "".join(char for char in text if char in BOARD_CHARSET)


def degree_sign(degree: str, device_type: str | None) -> str:
    """The degree sign, unless the board would print something else for it."""
    if degree == "off":
        return ""
    if degree == "on":
        return DEGREE
    return "" if (device_type or "").startswith(NOTE_DEVICE_TYPES) else DEGREE


def temperature(value: float | None) -> str:
    """Whole degrees for the board, "" when the model had no value.

    Rounds half away from zero, and never shows "-0".
    """
    if value is None:
        return ""
    rounded = int(math.copysign(math.floor(abs(value) + 0.5), value))
    return str(rounded) if rounded else "0"


def number(value: float | None, decimals: int = 0) -> str:
    """A measurement with fixed decimals, "" when there is none."""
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def condition_label(code: int | None, is_day: bool, language: str, *, short: bool = False) -> str:
    """The board word for a WMO code, "" for a code Open-Meteo never sends.

    *short* gives the six-tile form used when the full word does not fit.
    """
    if code is None:
        return ""
    label = CLEAR_NIGHT[language] if code == 0 and not is_day else CONDITIONS[language].get(code, "")
    return SHORT_CONDITIONS[language].get(label, label) if short else label


def rate_day(code: int | None, rain: float | None, threshold: float) -> str:
    """Rate a day as good, mixed or bad for the week overview.

    Dry and sunny is good, grey or foggy is mixed, anything wet or stormy is
    bad — unless the day's precipitation stays under *threshold*, in which case
    the wet code came from a stray shower and the day is only mixed.
    """
    if code is None or code in GREY_CODES:
        return MIXED
    if code in DRY_CODES:
        return GOOD
    if rain is not None and rain < threshold:
        return MIXED
    return BAD


# --------------------------------------------------------------------------
# Layout
#
# Rows are built as lists of tiles, not strings: a color marker like "{66}" is
# four characters but one flap, so padding by ``len`` would be wrong as soon as
# a row carries color.
# --------------------------------------------------------------------------


def tiles(text: str) -> list[str]:
    return list(text)


def fit(row: list[str], width: int, alignment: str = "left") -> list[str]:
    """Cut or pad *row* to exactly *width* tiles."""
    row = row[:width]
    padding = width - len(row)
    if alignment == "center":
        left = padding // 2
        return [" "] * left + row + [" "] * (padding - left)
    return row + [" "] * padding


def follow(text: str, value: str, width: int) -> list[str]:
    """*value* right after *text*, left-aligned: "BEWOELKT 12C".

    Only the text is shortened when the row is too narrow for both.
    """
    if not value:
        return fit(tiles(text), width)
    if not text:
        return fit(tiles(value), width)
    room = max(width - len(value) - 1, 0)
    if not room:
        return fit(tiles(value), width)
    return fit(tiles(text[:room]) + [" "] + tiles(value), width)


def compose(left: str, right: str, width: int) -> list[str]:
    """Left text and right text on one row, the left one shortened first.

    A cut "STARKRE" still reads as rain; a cut temperature is a wrong number.
    """
    if not right:
        return fit(tiles(left), width)
    room = max(width - len(right) - 1, 0)
    if not room:
        return fit(tiles(right), width)
    return tiles(left[:room].ljust(room)) + [" "] + tiles(right)


def range_row(low: str, high: str, unit: str, width: int) -> list[str]:
    """Today's low after a blue tile and the high after a red one.

    ``■ 7°C  ■ 14°C`` when it fits, then without the space after each tile,
    then with no gap at all — the colors keep the two apart either way.
    """
    parts = [(tile, f"{value}{unit}") for tile, value in ((COLD_TILE, low), (HOT_TILE, high)) if value]
    row: list[str] = []
    for inner, gap in ((" ", "  "), ("", " "), ("", "")):
        row = []
        for index, (tile, text) in enumerate(parts):
            if index:
                row += tiles(gap)
            row += [tile, *tiles(inner), *tiles(text)]
        if len(row) <= width:
            break
    return fit(row, width)


def week_row(names: list[str], marks: list[str], width: int) -> list[str]:
    """The week on a single row, as rich as the width allows.

    ``MO■ DI■ MI■ …`` (27 tiles), else ``M■D■M■…`` (14), else the tiles alone,
    spaced if there is room. Seven days in a row read left to right from
    today, so even the single letters are unambiguous in context.
    """
    count = len(marks)
    if count * 3 + (count - 1) <= width:
        row: list[str] = []
        for index, (name, mark) in enumerate(zip(names, marks, strict=True)):
            if index:
                row.append(" ")
            row += tiles(name) + [mark]
        return fit(row, width)
    if count * 2 <= width:
        row = []
        for name, mark in zip(names, marks, strict=True):
            row += [name[:1], mark]
        return fit(row, width)
    if count * 2 - 1 <= width:
        row = []
        for index, mark in enumerate(marks):
            if index:
                row.append(" ")
            row.append(mark)
        return fit(row, width)
    return fit(marks, width)


def week_columns(names: list[str], marks: list[str], highs: list[str], width: int) -> list[list[str]]:
    """The week as three rows: weekday names, two-tile bars, daily highs.

    Every day is a two-tile column with one blank between columns. The highs
    row is left blank when a value needs more than two tiles (-10 and colder,
    100°F and hotter) — misaligned numbers under the bars would read as the
    wrong day's.
    """
    name_row: list[str] = []
    bar_row: list[str] = []
    high_row: list[str] = []
    fits = all(len(high) <= 2 for high in highs)
    for index, (name, mark, high) in enumerate(zip(names, marks, highs, strict=True)):
        if index:
            name_row.append(" ")
            bar_row.append(" ")
            high_row.append(" ")
        name_row += tiles(name[:2].ljust(2))
        bar_row += [mark, mark]
        high_row += tiles(high.rjust(2)) if fits else [" ", " "]
    return [fit(name_row, width, "center"), fit(bar_row, width, "center"), fit(high_row, width, "center")]


@dataclass(frozen=True)
class View:
    """Everything the layout needs, already turned into board text."""

    condition: str
    condition_short: str
    temperature: str
    humidity: str
    low: str
    high: str
    rain_chance: str
    wind: str
    names: list[str]
    marks: list[str]
    highs: list[str]
    # Temperature suffix: "°C" on a Flagship, "C" where the degree sign is off.
    unit: str
    words: dict[str, str]
    wind_unit: str


def now_row(view: View, width: int) -> list[str]:
    """Condition, temperature and humidity: "BEWOELKT 12°C 71%".

    The numbers always stay. When the full word leaves them no room it gives
    way to its short form ("WOLKIG 12°C 71%" on a Note), and only if even that
    is too long is the word cut.
    """
    temperature = f"{view.temperature}{view.unit}" if view.temperature else ""
    humidity = f"{view.humidity}%" if view.humidity else ""
    value = " ".join(part for part in (temperature, humidity) if part)
    gap = 1 if value else 0
    label = view.condition
    if len(label) + gap + len(value) > width:
        label = view.condition_short
    return follow(label, value, width)


def layout(view: View, width: int, height: int) -> list[str]:
    """Lay the weather out as *height* rows of *width* tiles.

    A board of at least 20x6 gets the full layout: now, today's range, rain and
    wind, then the week as labelled bars with the highs underneath. Anything
    smaller gets the compact one — now, today's range, the week on one row —
    trimmed from the bottom on a board with fewer than three rows.
    """
    now = now_row(view, width)
    today = range_row(view.low, view.high, view.unit, width)

    if width >= WIDE_MIN_WIDTH and height >= WIDE_MIN_HEIGHT:
        rain = f"{view.words['rain']} {view.rain_chance}%" if view.rain_chance else ""
        wind = f"{view.words['wind']} {view.wind}{view.wind_unit}" if view.wind else ""
        details = compose(rain, wind, width) if rain else fit(tiles(wind), width)
        rows = [now, today, details, *week_columns(view.names, view.marks, view.highs, width)]
    else:
        rows = [now, today, week_row(view.names, view.marks, width)]

    rows = rows[:height]
    rows += [[" "] * width for _ in range(height - len(rows))]
    return ["".join(row) for row in rows]


# --------------------------------------------------------------------------
# Plugin
# --------------------------------------------------------------------------


class WetterPlugin(PluginBase):
    """Current weather and a colored week overview for one location."""

    @property
    def plugin_id(self) -> str:
        return "wetter"

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """Reject coordinates the plugin could not ask Open-Meteo about."""
        errors = self._validate_refresh_seconds(config)
        coordinates = config.get("coordinates", "")
        if coordinates and parse_coordinates(coordinates) is None:
            errors.append(f"Coordinates must look like '52.52, 13.405' (latitude, longitude), got {coordinates!r}")
        threshold = config.get("rain_threshold")
        if threshold is not None and (not isinstance(threshold, int | float) or threshold < 0):
            errors.append("Rain threshold must be a number of at least 0")
        return errors

    def on_config_change(self, old_config: dict[str, Any], new_config: dict[str, Any]) -> None:
        """New coordinates or units are a new question; never answer from the old one."""
        clear_shared_cache()
        self.clear_cache()

    def _options(self) -> tuple[str, str, str]:
        """Language, units and week start, clamped to what the code handles."""
        language = _choice(self.config.get("language"), LANGUAGES, DEFAULT_LANGUAGE)
        units = _choice(self.config.get("units"), UNITS, DEFAULT_UNITS)
        week_start = _choice(self.config.get("week_start"), WEEK_STARTS, DEFAULT_WEEK_START)
        return language, units, week_start

    def fetch_data(self) -> PluginResult:
        """Ask Open-Meteo for the configured location and lay it out for this board."""
        coordinates = parse_coordinates(self.config.get("coordinates", ""))
        if coordinates is None:
            return PluginResult(available=False, error="Coordinates are not configured")

        language, units, week_start = self._options()
        today_index, _ = days_requested(week_start)
        try:
            forecast = parse_forecast(fetch_forecast_body(request_params(*coordinates, units, week_start)))
            if today_index >= len(forecast.days):
                raise WetterError("Open-Meteo returned fewer days than were asked for")
        except WetterError as error:
            logger.warning("Open-Meteo fetch failed: %s", error)
            return PluginResult(available=False, error=str(error))
        except Exception as error:  # noqa: BLE001 — a bad payload must not break the render loop
            logger.exception("Unexpected error reading the Open-Meteo forecast")
            return PluginResult(available=False, error=str(error))

        view, data = self._build(forecast, language, units, week_start, today_index)
        board = self.board
        width = board.width if board else FALLBACK_WIDTH
        height = board.height if board else FALLBACK_HEIGHT
        lines = layout(view, width, height)

        # One variable that fills the whole board. FiestaBoard's template engine
        # splits a value on "\n" across board rows, so `{{wetter.block}}` on the
        # first template line reproduces the layout without needing |wrap.
        data["block"] = "\n".join(lines)
        # line1..line6 mirror the same rows individually. They keep their full
        # board width on purpose: the engine pads *around* what it is given, so
        # an rstripped row would be indented twice on a centered line.
        for index in range(FALLBACK_HEIGHT):
            data[f"line{index + 1}"] = lines[index] if index < len(lines) else ""

        return PluginResult(available=True, data=data, formatted_lines=lines)

    def _build(
        self, forecast: Forecast, language: str, units: str, week_start: str, today_index: int
    ) -> tuple[View, dict[str, Any]]:
        """The layout's input and the template variables, from one forecast."""
        umlauts = "strip" if self.config.get("umlauts") == "strip" else "expand"
        degree = _choice(self.config.get("degree_sign"), DEGREE_CHOICES, DEFAULT_DEGREE)
        board = self.board
        sign = degree_sign(degree, board.device_type if board else "flagship")
        unit = f"{sign}{'F' if units == 'imperial' else 'C'}"

        threshold = self.config.get("rain_threshold", DEFAULT_RAIN_THRESHOLD_MM)
        if not isinstance(threshold, int | float) or threshold < 0:
            threshold = DEFAULT_RAIN_THRESHOLD_MM
        if units == "imperial":
            # The setting is in millimetres; Open-Meteo now answers in inches.
            threshold = threshold / 25.4

        colors = {
            rating: COLOR_TILES.get(self.config.get(f"color_{rating}"), COLOR_TILES[default])
            for rating, default in DEFAULT_COLORS.items()
        }

        today = forecast.days[today_index]
        week = week_window(forecast.days, today_index, week_start)
        ratings = [rate_day(day.code, day.rain, threshold) for day in week]
        names = [WEEKDAYS[language][day.day.weekday()] for day in week]
        marks = [colors[rating] for rating in ratings]
        highs = [temperature(day.high) for day in week]

        words = WORDS[language]
        wind_unit = "MPH" if units == "imperial" else "KMH"
        condition = to_board_text(condition_label(forecast.code, forecast.is_day, language), umlauts)
        condition_short = to_board_text(condition_label(forecast.code, forecast.is_day, language, short=True), umlauts)
        now_rating = rate_day(forecast.code, today.rain, threshold)

        view = View(
            condition=condition,
            condition_short=condition_short,
            temperature=temperature(forecast.temperature),
            humidity=_whole(forecast.humidity),
            low=temperature(today.low),
            high=temperature(today.high),
            rain_chance=_whole(today.rain_chance),
            wind=number(forecast.wind),
            names=names,
            marks=marks,
            highs=highs,
            unit=unit,
            words=words,
            wind_unit=wind_unit,
        )

        data: dict[str, Any] = {
            "location": to_board_text(self.config.get("location_name") or "", umlauts),
            "condition": condition,
            "condition_short": condition_short,
            "temp": view.temperature,
            "feels_like": temperature(forecast.feels_like),
            "temp_unit": unit,
            "low": view.low,
            "high": view.high,
            "humidity": view.humidity,
            "wind": view.wind,
            "wind_unit": wind_unit,
            "rain_chance": view.rain_chance,
            "rain": number(today.rain, 1),
            "color": colors[now_rating],
            "week_tiles": "".join(marks),
            "week": "".join(week_row(names, marks, len(marks) * 2)),
            "days": [
                {
                    "name": name,
                    "date": day.day.isoformat(),
                    "condition": to_board_text(condition_label(day.code, True, language), umlauts),
                    "high": temperature(day.high),
                    "low": temperature(day.low),
                    "rain": number(day.rain, 1),
                    "rain_chance": _whole(day.rain_chance),
                    "rating": rating,
                    "color": colors[rating],
                }
                for name, day, rating in zip(names, week, ratings, strict=True)
            ],
        }
        return view, data


def _whole(value: int | None) -> str:
    """Whole-number reading as board text, empty when unreported."""
    return "" if value is None else str(int(value))


# Export the plugin class
Plugin = WetterPlugin
