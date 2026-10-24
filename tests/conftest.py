"""Shared fixtures for the Open-Meteo plugin tests.

Nothing here touches the network: the forecast is a hand-built copy of what
Open-Meteo returns, and the plugin fixture stubs the one function that speaks
HTTP.
"""

import json
import pathlib

import pytest

from plugins import open_meteo
from plugins.open_meteo import OpenMeteoPlugin

MANIFEST = json.loads((pathlib.Path(__file__).resolve().parent.parent / "manifest.json").read_text())

# Berlin, the location the committed previews were rendered for.
COORDINATES = "52.52, 13.405"

# Where Saturday 2026-10-24, "today", sits in the full fixture series: after
# six past days, the most the plugin ever asks for.
TODAY = 6


def forecast_body():
    """Sunday 2026-10-18 to Saturday 2026-10-31, today being Saturday the 24th.

    The calendar week (Mon 19 – Sun 25) has two rainy days behind it. Ahead,
    Monday the 26th is real rain (bad), Thursday's showers come to 0.4 mm and
    stay under the default threshold (mixed), Friday is a thunderstorm (bad).
    """
    return {
        "latitude": 52.52,
        "longitude": 13.42,
        "timezone": "Europe/Berlin",
        "current": {
            "time": "2026-10-24T14:30",
            "temperature_2m": 12.4,
            "apparent_temperature": 10.1,
            "relative_humidity_2m": 71,
            "weather_code": 2,
            "is_day": 1,
            "wind_speed_10m": 14.3,
        },
        "daily": {
            "time": [
                "2026-10-18",
                "2026-10-19",
                "2026-10-20",
                "2026-10-21",
                "2026-10-22",
                "2026-10-23",
                "2026-10-24",
                "2026-10-25",
                "2026-10-26",
                "2026-10-27",
                "2026-10-28",
                "2026-10-29",
                "2026-10-30",
                "2026-10-31",
            ],
            "weather_code": [3, 61, 1, 3, 63, 0] + [2, 0, 61, 3, 1, 80, 95, 3],
            "temperature_2m_max": [11.0, 10.2, 13.1, 12.0, 9.8, 15.4] + [14.2, 16.0, 11.5, 12.8, 15.3, 13.9, 9.6, 10.0],
            "temperature_2m_min": [5.0, 6.1, 4.2, 6.6, 7.0, 5.5] + [6.8, 5.1, 7.4, 8.0, 6.2, 7.7, 4.9, 3.0],
            "precipitation_sum": [0.0, 3.0, 0.0, 0.0, 6.0, 0.0] + [0.0, 0.0, 5.2, 0.0, 0.0, 0.4, 8.1, 0.0],
            "precipitation_probability_max": [10, 70, 5, 20, 85, 0] + [20, 5, 90, 15, 10, 45, 80, 10],
        },
    }


def answer(params):
    """The slice of the fixture Open-Meteo would return for *params*."""
    body = forecast_body()
    start = TODAY - params.get("past_days", 0)
    end = TODAY + params["forecast_days"]
    body["daily"] = {key: values[start:end] for key, values in body["daily"].items()}
    return body


@pytest.fixture
def manifest():
    return MANIFEST


@pytest.fixture
def calls(monkeypatch):
    """Stub Open-Meteo and record every query the plugin sends it."""
    sent: list[dict] = []

    def fake_fetch(params):
        sent.append(params)
        return answer(params)

    monkeypatch.setattr(open_meteo, "fetch_forecast_body", fake_fetch)
    return sent


@pytest.fixture
def make_plugin(calls):
    """Build a configured plugin instance whose forecast comes from the fixture."""

    def _make(**config):
        plugin = OpenMeteoPlugin(MANIFEST)
        plugin.config = {"coordinates": COORDINATES, **config}
        return plugin

    return _make
