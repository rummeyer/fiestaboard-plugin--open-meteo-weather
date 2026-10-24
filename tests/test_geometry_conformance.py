"""Board-geometry conformance for the Open Meteo Weather plugin.

Runs the shared FiestaBoard conformance suite (``src/plugins/
geometry_conformance.py`` in core -- importable here because core is on
``PYTHONPATH`` in plugin CI) across every board shape the platform supports,
including note arrays up to 120x24 and FiestaPanel grids. The forecast comes
from the test fixture; nothing touches the network.

``strict_growth`` is intentionally omitted: the layout shows one location's
weather, not a list, so a taller board is not expected to carry more of it.
"""

from unittest.mock import patch

import pytest

from plugins import open_meteo_weather
from plugins.open_meteo_weather import OpenMeteoWeatherPlugin
from src.plugins.geometry_conformance import assert_board_conformance

from .conftest import COORDINATES, MANIFEST, answer


@pytest.mark.parametrize("language", ["de", "en"])
def test_renders_on_every_board_shape(language):
    def make_plugin() -> OpenMeteoWeatherPlugin:
        plugin = OpenMeteoWeatherPlugin(MANIFEST)
        plugin.config = {"coordinates": COORDINATES, "language": language, "location_name": "Berlin Mitte"}
        return plugin

    open_meteo_weather.clear_shared_cache()
    with patch.object(open_meteo_weather, "fetch_forecast_body", answer):
        assert_board_conformance(make_plugin, manifest=MANIFEST, require_note_array_preview=True)
