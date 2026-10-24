"""Guards that keep manifest, code, docs and changelog from drifting apart.

The manifest is not just metadata — FiestaBoard renders the plugin directory
from it and the template editor offers whatever variables it declares. A field
that no longer matches the code is a broken listing, not a cosmetic slip.
"""

import json
import pathlib
import re

import pytest
from src.devices import BoardContext

from plugins.open_meteo_weather import (
    COLOR_TILES,
    DEFAULT_COLORS,
    DEFAULT_DEGREE,
    DEFAULT_LANGUAGE,
    DEFAULT_RAIN_THRESHOLD_MM,
    DEFAULT_UNITS,
    DEGREE_CHOICES,
    LANGUAGES,
    UNITS,
    OpenMeteoWeatherPlugin,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOARD_SHAPES = {"flagship": (6, 22), "note": (3, 15)}


def preview_board(preview: dict) -> BoardContext:
    """The board a preview entry describes; a note array's shape comes from the entry."""
    if preview["device_type"] == "note_array":
        return BoardContext(device_type="note_array", rows=preview["notes_tall"] * 3, cols=preview["notes_wide"] * 15)
    return BoardContext.from_device_type(preview["device_type"])
COLOR_MARKER = re.compile(r"\{(?:6[3-9]|7[01])\}")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "manifest.json").read_text())


def count_tiles(row: str) -> int:
    """Flaps used by a row. A color marker like ``{66}`` is one tile, not four."""
    return len(COLOR_MARKER.sub("X", row))


class TestIdentity:
    def test_id_matches_the_plugin_class(self, manifest):
        assert manifest["id"] == OpenMeteoWeatherPlugin(manifest).plugin_id

    def test_version_is_semver(self, manifest):
        assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])

    def test_version_matches_the_changelog(self, manifest):
        """The changelog is the source of truth; a release without an entry is a lie."""
        changelog = (ROOT / "CHANGELOG.md").read_text()
        released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)
        assert released, "CHANGELOG.md has no released versions"
        assert manifest["version"] == released[0]


class TestSettingsSchema:
    def test_enum_options_match_the_code(self, manifest):
        properties = manifest["settings_schema"]["properties"]
        assert tuple(properties["language"]["enum"]) == LANGUAGES
        assert tuple(properties["units"]["enum"]) == UNITS
        assert tuple(properties["degree_sign"]["enum"]) == DEGREE_CHOICES
        for rating in DEFAULT_COLORS:
            assert set(properties[f"color_{rating}"]["enum"]) <= set(COLOR_TILES)

    def test_schema_defaults_match_the_code_fallbacks(self, manifest):
        """A board configured purely from defaults must render what the form shows."""
        properties = manifest["settings_schema"]["properties"]
        assert properties["language"]["default"] == DEFAULT_LANGUAGE
        assert properties["units"]["default"] == DEFAULT_UNITS
        assert properties["degree_sign"]["default"] == DEFAULT_DEGREE
        assert properties["rain_threshold"]["default"] == DEFAULT_RAIN_THRESHOLD_MM
        for rating, color in DEFAULT_COLORS.items():
            assert properties[f"color_{rating}"]["default"] == color

    def test_every_enum_has_a_label(self, manifest):
        for name, prop in manifest["settings_schema"]["properties"].items():
            if "enum" in prop:
                assert len(prop.get("enumNames", [])) == len(prop["enum"]), f"{name} labels do not line up"

    def test_every_enum_default_is_one_of_its_options(self, manifest):
        for name, prop in manifest["settings_schema"]["properties"].items():
            if "enum" in prop and "default" in prop:
                assert prop["default"] in prop["enum"], f"{name} default is not an option"

    def test_the_refresh_floor_respects_open_meteos_update_cycle(self, manifest):
        assert manifest["min_refresh_seconds"] >= 300
        assert manifest["settings_schema"]["properties"]["refresh_seconds"]["minimum"] >= 300


class TestVariables:
    def test_declared_variables_are_the_ones_the_plugin_produces(self, manifest, make_plugin):
        """A declared variable that never materialises renders as blank on the board."""
        produced = set(make_plugin().get_data(BoardContext.from_device_type("flagship")).data)
        declared = set(manifest["variables"]["simple"]) | set(manifest["variables"]["arrays"])
        assert produced == declared

    def test_the_day_array_declares_the_fields_it_produces(self, manifest, make_plugin):
        days = make_plugin().get_data(BoardContext.from_device_type("flagship")).data["days"]
        assert len(days) == 7
        assert set(days[0]) == set(manifest["variables"]["arrays"]["days"]["item_fields"])

    def test_the_array_label_field_is_one_of_its_own_fields(self, manifest):
        array = manifest["variables"]["arrays"]["days"]
        assert array["label_field"] in array["item_fields"]

    def test_every_variable_names_a_group_that_exists(self, manifest):
        groups = set(manifest["variables"]["groups"])
        for name, spec in manifest["variables"]["simple"].items():
            assert spec["group"] in groups, f"{name} points at an unknown group"

    def test_every_simple_variable_has_a_max_length(self, manifest):
        simple = manifest["variables"]["simple"]
        assert set(manifest["max_lengths"]) == set(simple)
        for name, declared in manifest["max_lengths"].items():
            assert simple[name]["max_length"] == declared

    def test_produced_values_stay_within_their_max_length(self, manifest, make_plugin):
        for device_type in BOARD_SHAPES:
            data = make_plugin().get_data(BoardContext.from_device_type(device_type)).data
            for name, limit in manifest["max_lengths"].items():
                assert len(data[name]) <= limit, f"{name} on a {device_type} is {len(data[name])} long"


class TestBoardPreviews:
    def test_teaser_fits_the_narrowest_board(self, manifest):
        assert count_tiles(manifest["teaser"]) <= 15

    def test_preview_rows_fit_their_board(self, manifest):
        for preview in manifest["previews"]:
            board = preview_board(preview)
            assert len(preview["rows"]) <= board.rows
            for row in preview["rows"]:
                assert count_tiles(row) <= board.cols, f"{preview['device_type']} row is too wide"

    def test_both_board_shapes_are_covered(self, manifest):
        assert {p["device_type"] for p in manifest["previews"]} == {*BOARD_SHAPES, "note_array"}

    @pytest.mark.parametrize("device_type", [*sorted(BOARD_SHAPES), "note_array"])
    def test_previews_match_what_the_plugin_actually_renders(self, manifest, device_type, make_plugin):
        """A hand-edited preview that no longer matches the code misleads the directory."""
        preview = next(p for p in manifest["previews"] if p["device_type"] == device_type)
        rendered = make_plugin().get_data(preview_board(preview)).formatted_lines
        assert preview["rows"] == rendered

    def test_the_teaser_is_the_note_previews_first_row(self, manifest):
        note = next(p["rows"] for p in manifest["previews"] if p["device_type"] == "note")
        assert manifest["teaser"] == note[0]
