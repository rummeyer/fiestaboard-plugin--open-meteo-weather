"""Tests for the Wetter plugin."""

import pytest
import requests
from src.devices import BoardContext

from plugins import wetter
from plugins.wetter import (
    BAD,
    GOOD,
    MIXED,
    View,
    WetterError,
    WetterPlugin,
    compose,
    condition_label,
    degree_sign,
    fetch_forecast_body,
    layout,
    parse_coordinates,
    parse_forecast,
    range_text,
    rate_day,
    request_params,
    temperature,
    to_board_text,
    week_columns,
    week_row,
)

from .conftest import MANIFEST, forecast_body

FLAGSHIP = BoardContext.from_device_type("flagship")
NOTE = BoardContext.from_device_type("note")

GREEN, YELLOW, RED = "{66}", "{65}", "{63}"


def count_tiles(row: str) -> int:
    """Flaps used by a row. A color marker like ``{66}`` is one tile, not four."""
    return len(row) - 3 * row.count("{")


class FakeResponse:
    """Just enough of ``requests.Response`` for the one call the plugin makes."""

    def __init__(self, status_code=200, payload=None, raw=False):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._raw:
            raise ValueError("no json")
        return self._payload


class TestCoordinates:
    @pytest.mark.parametrize(
        "text",
        ["52.52, 13.405", "52.52,13.405", "52.52 13.405", "52.52; 13.405", "  52.52 ,  13.405 "],
    )
    def test_the_formats_a_map_app_copies_are_understood(self, text):
        assert parse_coordinates(text) == (52.52, 13.405)

    def test_the_southern_and_western_hemispheres_are_negative(self):
        assert parse_coordinates("-33.87, -151.21") == (-33.87, -151.21)

    @pytest.mark.parametrize("text", ["", "Berlin", "52.52", "1, 2, 3", "91, 0", "0, 181", "nan, 0", None, 52.5])
    def test_anything_that_is_not_a_place_on_earth_is_rejected(self, text):
        assert parse_coordinates(text) is None


class TestOpenMeteo:
    def test_the_query_asks_for_the_locations_own_timezone(self):
        params = request_params(52.52, 13.405, "metric", 7)
        assert params["timezone"] == "auto"
        assert params["forecast_days"] == 7
        assert "temperature_unit" not in params

    def test_imperial_is_converted_by_open_meteo(self):
        params = request_params(52.52, 13.405, "imperial", 7)
        assert params["temperature_unit"] == "fahrenheit"
        assert params["wind_speed_unit"] == "mph"
        assert params["precipitation_unit"] == "inch"

    def test_coordinates_are_rounded_so_boards_share_a_cache_key(self):
        params = request_params(52.520001, 13.4049999, "metric", 7)
        assert (params["latitude"], params["longitude"]) == (52.52, 13.405)

    def test_the_forecast_is_parsed_today_first(self):
        forecast = parse_forecast(forecast_body())
        assert forecast.temperature == 12.4
        assert forecast.code == 2
        assert forecast.is_day
        assert [day.day.isoformat() for day in forecast.days[:2]] == ["2026-10-24", "2026-10-25"]
        assert forecast.days[2].code == 61
        assert forecast.days[2].rain == 5.2

    def test_a_null_value_stays_empty_rather_than_becoming_zero(self):
        body = forecast_body()
        body["current"]["temperature_2m"] = None
        body["daily"]["temperature_2m_max"] = [None]
        forecast = parse_forecast(body)
        assert forecast.temperature is None
        assert forecast.days[0].high is None
        assert forecast.days[1].high is None

    def test_a_missing_current_block_still_gives_the_week(self):
        body = forecast_body()
        del body["current"]
        forecast = parse_forecast(body)
        assert forecast.temperature is None
        assert len(forecast.days) == 8

    def test_no_daily_forecast_is_an_error(self):
        with pytest.raises(WetterError):
            parse_forecast({"current": {}})

    def test_an_unreadable_date_is_an_error(self):
        body = forecast_body()
        body["daily"]["time"][0] = "Saturday"
        with pytest.raises(WetterError):
            parse_forecast(body)


class TestHttp:
    @pytest.fixture(autouse=True)
    def fresh_cache(self):
        wetter.clear_shared_cache()
        yield
        wetter.clear_shared_cache()

    def test_boards_asking_together_share_one_call(self, monkeypatch):
        sent = []

        def fake_get(url, params, timeout):
            sent.append(params)
            return FakeResponse(payload=forecast_body())

        monkeypatch.setattr(requests, "get", fake_get)
        params = request_params(52.52, 13.405, "metric", 7)
        assert fetch_forecast_body(params) == fetch_forecast_body(params)
        assert len(sent) == 1

    def test_a_different_location_is_a_different_call(self, monkeypatch):
        sent = []
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: sent.append(1) or FakeResponse(payload={}))
        fetch_forecast_body(request_params(52.52, 13.405, "metric", 7))
        fetch_forecast_body(request_params(48.14, 11.58, "metric", 7))
        assert len(sent) == 2

    def test_the_shared_answer_expires(self, monkeypatch):
        sent = []
        # Stored at 0, looked up again at 500 — long past the shared window.
        clock = iter([0.0, 500.0, 500.0])
        monkeypatch.setattr(wetter.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: sent.append(1) or FakeResponse(payload={}))
        params = request_params(52.52, 13.405, "metric", 7)
        fetch_forecast_body(params)
        fetch_forecast_body(params)
        assert len(sent) == 2

    def test_an_unreachable_api_is_reported(self, monkeypatch):
        def fail(url, params, timeout):
            raise requests.ConnectionError("no route")

        monkeypatch.setattr(requests, "get", fail)
        with pytest.raises(WetterError, match="unreachable"):
            fetch_forecast_body(request_params(52.52, 13.405, "metric", 7))

    def test_open_meteos_own_reason_is_passed_on(self, monkeypatch):
        payload = {"error": True, "reason": "Latitude must be in range of -90 to 90°."}
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(400, payload))
        with pytest.raises(WetterError, match="Latitude must be"):
            fetch_forecast_body(request_params(52.52, 13.405, "metric", 7))

    def test_a_server_error_without_a_reason_names_the_status(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(502, []))
        with pytest.raises(WetterError, match="HTTP 502"):
            fetch_forecast_body(request_params(52.52, 13.405, "metric", 7))

    def test_a_non_json_answer_is_reported(self, monkeypatch):
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: FakeResponse(503, raw=True))
        with pytest.raises(WetterError, match="without JSON"):
            fetch_forecast_body(request_params(52.52, 13.405, "metric", 7))

    def test_a_failed_call_is_not_cached(self, monkeypatch):
        answers = iter([FakeResponse(502, {}), FakeResponse(payload=forecast_body())])
        monkeypatch.setattr(requests, "get", lambda url, params, timeout: next(answers))
        params = request_params(52.52, 13.405, "metric", 7)
        with pytest.raises(WetterError):
            fetch_forecast_body(params)
        assert fetch_forecast_body(params)["daily"]


class TestText:
    def test_umlauts_are_expanded_or_stripped(self):
        assert to_board_text("Bewölkt") == "BEWOELKT"
        assert to_board_text("Bewölkt", "strip") == "BEWOLKT"

    def test_characters_the_board_cannot_flap_are_dropped(self):
        assert to_board_text("Köln ☀") == "KOELN "

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(12.4, "12"), (12.5, "13"), (-0.4, "0"), (-2.5, "-3"), (-12.6, "-13"), (0.0, "0"), (None, "")],
    )
    def test_temperatures_round_half_away_from_zero_and_never_show_minus_zero(self, value, expected):
        assert temperature(value) == expected

    def test_the_degree_sign_is_skipped_on_note_shaped_boards(self):
        assert degree_sign("auto", "flagship") == "°"
        assert degree_sign("auto", "note") == ""
        assert degree_sign("auto", "note_array") == ""
        assert degree_sign("on", "note") == "°"
        assert degree_sign("off", "flagship") == ""

    def test_every_condition_label_leaves_room_for_a_temperature_on_a_note(self):
        """15 tiles = label + space + "-12"/"104"; a longer label would be cut."""
        for language, labels in wetter.CONDITIONS.items():
            for code, label in labels.items():
                assert len(to_board_text(label)) <= 10, f"{language} {code} {label}"

    def test_a_clear_night_is_not_sunny(self):
        assert condition_label(0, True, "de") == "SONNIG"
        assert condition_label(0, False, "de") == "KLAR"
        assert condition_label(0, False, "en") == "CLEAR"

    def test_an_unknown_or_missing_code_has_no_label(self):
        assert condition_label(None, True, "de") == ""
        assert condition_label(42, True, "de") == ""


class TestRating:
    @pytest.mark.parametrize("code", [0, 1])
    def test_dry_and_sunny_is_good(self, code):
        assert rate_day(code, 0.0, 1.0) == GOOD

    @pytest.mark.parametrize("code", [2, 3, 45, 48])
    def test_grey_and_foggy_is_mixed(self, code):
        assert rate_day(code, 0.0, 1.0) == MIXED

    @pytest.mark.parametrize("code", [51, 61, 65, 71, 80, 95, 99])
    def test_wet_or_stormy_is_bad(self, code):
        assert rate_day(code, 4.0, 1.0) == BAD

    def test_a_stray_shower_under_the_threshold_is_only_mixed(self):
        assert rate_day(80, 0.4, 1.0) == MIXED

    def test_a_threshold_of_zero_takes_every_wet_code_at_its_word(self):
        assert rate_day(51, 0.0, 0.0) == BAD

    def test_wet_with_no_precipitation_figure_is_bad(self):
        assert rate_day(61, None, 1.0) == BAD

    def test_a_day_without_a_code_is_mixed(self):
        assert rate_day(None, 0.0, 1.0) == MIXED


class TestLayoutPieces:
    def test_compose_puts_the_value_on_the_right(self):
        assert "".join(compose("REGEN", "12", 15)) == "REGEN        12"

    def test_compose_shortens_the_label_not_the_number(self):
        assert "".join(compose("STARKREGEN", "-12°", 13)) == "STARKREG -12°"

    def test_compose_without_a_value_is_just_the_label(self):
        assert "".join(compose("NEBEL", "", 8)) == "NEBEL   "

    def test_compose_on_a_board_too_narrow_for_both_keeps_the_value(self):
        assert "".join(compose("NEBEL", "12", 2)) == "12"

    def test_range_text_drops_detail_as_the_row_narrows(self):
        words = wetter.WORDS["de"]
        assert range_text("-12", "-3", "°", words, 22) == "MIN -12°  MAX -3°"
        assert range_text("-12", "-3", "", words, 14) == "MIN -12 MAX -3"
        assert range_text("-12", "-3", "", words, 10) == "-12/-3"

    def test_range_text_with_one_side_missing(self):
        assert range_text("", "14", "", wetter.WORDS["en"], 15) == "HIGH 14"
        assert range_text("", "", "", wetter.WORDS["en"], 15) == ""

    def test_week_row_uses_the_richest_form_that_fits(self):
        names = ["SA", "SO", "MO", "DI", "MI", "DO", "FR"]
        marks = [GREEN] * 7
        assert "".join(week_row(names, marks, 30)).startswith(f"SA{GREEN} SO{GREEN} ")
        assert "".join(week_row(names, marks, 15)) == "".join(f"{n[0]}{GREEN}" for n in names) + " "
        assert "".join(week_row(names, marks, 13)) == " ".join([GREEN] * 7)
        assert "".join(week_row(names, marks, 7)) == GREEN * 7

    def test_week_columns_line_up_names_bars_and_highs(self):
        names = ["SA", "SO", "MO", "DI", "MI", "DO", "FR"]
        rows = ["".join(row) for row in week_columns(names, [RED] * 7, ["9"] * 7, 22)]
        assert rows[0] == " SA SO MO DI MI DO FR "
        assert rows[1] == " " + " ".join([RED * 2] * 7) + " "
        assert rows[2] == "  9  9  9  9  9  9  9 "

    def test_highs_too_wide_for_their_column_are_left_out(self):
        rows = week_columns(["MO"] * 7, [RED] * 7, ["-12"] + ["3"] * 6, 22)
        assert "".join(rows[2]).strip() == ""


def view(**overrides):
    defaults = {
        "condition": "BEWOELKT",
        "temperature": "12",
        "low": "7",
        "high": "14",
        "rain_chance": "20",
        "wind": "14",
        "names": ["SA", "SO", "MO", "DI", "MI", "DO", "FR"],
        "marks": [YELLOW, GREEN, RED, YELLOW, GREEN, YELLOW, RED],
        "highs": ["14", "16", "12", "13", "15", "14", "10"],
        "sign": "",
        "words": wetter.WORDS["de"],
        "wind_unit": "KMH",
    }
    return View(**{**defaults, **overrides})


class TestLayout:
    @pytest.mark.parametrize(("width", "height"), [(15, 3), (22, 6), (30, 3), (15, 6), (45, 9), (15, 1)])
    def test_every_row_is_exactly_as_wide_as_the_board(self, width, height):
        rows = layout(view(), width, height)
        assert len(rows) == height
        assert all(count_tiles(row) == width for row in rows)

    def test_a_note_gets_now_today_and_the_week(self):
        rows = layout(view(), 15, 3)
        assert rows[0] == "BEWOELKT     12"
        assert rows[1] == "MIN 7  MAX 14  "
        assert rows[2].startswith(f"S{YELLOW}S{GREEN}M{RED}")

    def test_a_flagship_gets_bars_with_the_highs_underneath(self):
        rows = layout(view(sign="°"), 22, 6)
        assert rows[2] == "REGEN 20%   WIND 14KMH"
        assert rows[3] == " SA SO MO DI MI DO FR "
        assert rows[5] == " 14 16 12 13 15 14 10 "

    def test_a_tall_narrow_board_keeps_the_compact_layout(self):
        rows = layout(view(), 15, 6)
        assert rows[3:] == [" " * 15] * 3

    def test_a_single_row_board_shows_now(self):
        assert layout(view(), 15, 1) == ["BEWOELKT     12"]

    def test_missing_rain_chance_leaves_wind_alone(self):
        assert layout(view(rain_chance=""), 22, 6)[2] == "WIND 14KMH".ljust(22)

    def test_missing_current_temperature_shows_the_condition_only(self):
        assert layout(view(temperature=""), 15, 3)[0] == "BEWOELKT       "


class TestPlugin:
    def test_unconfigured_coordinates_are_reported(self):
        plugin = WetterPlugin(MANIFEST)
        plugin.config = {}
        result = plugin.fetch_data()
        assert not result.available
        assert "Coordinates" in result.error

    def test_the_note_preview(self, make_plugin):
        rows = make_plugin().get_data(NOTE).formatted_lines
        assert rows[0] == "BEWOELKT     12"
        assert rows[2] == f"S{YELLOW}S{GREEN}M{RED}D{YELLOW}M{GREEN}D{YELLOW}F{RED} "

    def test_the_week_can_start_tomorrow(self, make_plugin, calls):
        result = make_plugin(include_today=False).get_data(NOTE)
        assert calls[-1]["forecast_days"] == 8
        assert result.formatted_lines[2].startswith(f"S{GREEN}M{RED}")
        assert [day["name"] for day in result.data["days"]] == ["SO", "MO", "DI", "MI", "DO", "FR", "SA"]
        # Today's range is still today's.
        assert (result.data["low"], result.data["high"]) == ("7", "14")

    def test_english_names_the_days_and_weather_in_english(self, make_plugin):
        rows = make_plugin(language="en").get_data(FLAGSHIP).formatted_lines
        assert rows[0].startswith("CLOUDY")
        assert rows[1].startswith("LOW 7°  HIGH 14°")
        assert rows[3] == " SA SU MO TU WE TH FR "

    def test_imperial_asks_for_imperial_and_converts_the_threshold(self, make_plugin, calls):
        # 0.4 in of Thursday showers is 10 mm — well over the 1 mm threshold.
        result = make_plugin(units="imperial").get_data(FLAGSHIP)
        assert calls[-1]["temperature_unit"] == "fahrenheit"
        assert result.data["wind_unit"] == "MPH"
        assert result.data["temp_unit"] == "°F"
        assert result.data["days"][5]["rating"] == BAD

    def test_custom_colors_replace_the_defaults(self, make_plugin):
        data = make_plugin(color_good="blue", color_bad="violet").get_data(NOTE).data
        assert data["week_tiles"] == "{65}{67}{68}{65}{67}{65}{68}"

    def test_an_unknown_color_falls_back_to_the_default(self, make_plugin):
        data = make_plugin(color_good="pink").get_data(NOTE).data
        assert data["days"][1]["color"] == GREEN

    def test_a_higher_threshold_downgrades_more_days(self, make_plugin):
        data = make_plugin(rain_threshold=6).get_data(NOTE).data
        assert [day["rating"] for day in data["days"]] == [MIXED, GOOD, MIXED, MIXED, GOOD, MIXED, BAD]

    def test_a_broken_threshold_uses_the_default(self, make_plugin):
        data = make_plugin(rain_threshold="viel").get_data(NOTE).data
        assert data["days"][2]["rating"] == BAD

    def test_strip_umlauts(self, make_plugin):
        assert make_plugin(umlauts="strip").get_data(NOTE).data["condition"] == "BEWOLKT"

    def test_variables(self, make_plugin):
        data = make_plugin(location_name="Köln").get_data(FLAGSHIP).data
        assert data["location"] == "KOELN"
        assert (data["temp"], data["feels_like"], data["humidity"], data["wind"]) == ("12", "10", "71", "14")
        assert (data["rain_chance"], data["rain"], data["color"]) == ("20", "0.0", YELLOW)
        assert data["week"] == f"S{YELLOW}S{GREEN}M{RED}D{YELLOW}M{GREEN}D{YELLOW}F{RED}"
        assert data["block"].split("\n") == [data[f"line{i}"] for i in range(1, 7)]

    def test_a_note_leaves_lines_four_to_six_empty(self, make_plugin):
        data = make_plugin().get_data(NOTE).data
        assert (data["line4"], data["line5"], data["line6"]) == ("", "", "")

    def test_outside_a_board_render_the_flagship_layout_is_used(self, make_plugin):
        assert len(make_plugin().fetch_data().formatted_lines) == 6

    def test_an_api_failure_makes_the_plugin_unavailable(self, make_plugin, monkeypatch):
        def fail(params):
            raise WetterError("Open-Meteo is unreachable")

        monkeypatch.setattr(wetter, "fetch_forecast_body", fail)
        result = make_plugin().fetch_data()
        assert not result.available
        assert result.error == "Open-Meteo is unreachable"

    def test_an_unexpected_payload_does_not_break_the_render_loop(self, make_plugin, monkeypatch):
        monkeypatch.setattr(
            wetter, "fetch_forecast_body", lambda params: {"daily": {"time": ["2026-10-24"]}, "current": "x"}
        )
        result = make_plugin().fetch_data()
        assert not result.available

    def test_a_config_change_forgets_the_old_answer(self, make_plugin, monkeypatch):
        cleared = []
        monkeypatch.setattr(wetter, "clear_shared_cache", lambda: cleared.append(1))
        plugin = make_plugin()
        plugin.on_config_change({}, {"coordinates": "48.14, 11.58"})
        assert cleared


class TestValidation:
    def test_valid_settings_pass(self):
        assert WetterPlugin(MANIFEST).validate_config({"coordinates": "52.52, 13.405", "rain_threshold": 2}) == []

    def test_empty_coordinates_are_allowed_until_the_user_fills_them_in(self):
        assert WetterPlugin(MANIFEST).validate_config({"coordinates": ""}) == []

    def test_bad_coordinates_are_rejected(self):
        errors = WetterPlugin(MANIFEST).validate_config({"coordinates": "Berlin"})
        assert errors and "52.52, 13.405" in errors[0]

    @pytest.mark.parametrize("threshold", [-1, "viel"])
    def test_a_bad_threshold_is_rejected(self, threshold):
        assert WetterPlugin(MANIFEST).validate_config({"rain_threshold": threshold})
