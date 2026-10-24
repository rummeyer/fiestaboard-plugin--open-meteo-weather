# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version here is the source of truth for `manifest.json` — a test fails if
the two drift apart.

## [Unreleased]

## [3.1.0] — 2026-10-24

### Added

- `docs/SETUP.md`, screenshots (`docs/board-display.png` and friends, listed
  in the manifest) and a README in FiestaBoard's standard section order — what
  the plugin registry asks for.
- A note-array preview and a Flagship demo page next to the Note one, so
  FiestaBoard offers the demo that fits the board you own.
- FiestaBoard's geometry conformance suite runs in the tests, on every board
  shape the platform supports.

### Fixed

- `line1`…`line6` and `block` declared lengths too short for wide boards: a
  row is up to 128 tiles on the widest FiestaPanel grid, and `block` up to
  12383. The template editor sizes its fit warnings from these numbers.

## [3.0.0] — 2026-10-24

### Changed

- **Renamed again, to Open Meteo Weather** (no hyphen in the plugin name;
  the forecast service keeps its own spelling, Open-Meteo). The plugin id is
  now `open_meteo_weather`, so template variables move from
  `{{open_meteo.*}}` to `{{open_meteo_weather.*}}`, and the repository to
  `fiestaboard-plugin--open-meteo-weather` (GitHub redirects both older
  URLs). FiestaBoard treats it as a new plugin, as with 2.0.0.

## [2.0.0] — 2026-10-24

### Changed

- **Renamed from Wetter to Open-Meteo**, after the forecast service it reads.
  The plugin id is now `open_meteo`, so template variables move from
  `{{wetter.*}}` to `{{open_meteo.*}}`, and the repository from
  `fiestaboard-plugin--wetter` to `fiestaboard-plugin--open-meteo` (GitHub
  redirects the old URL). FiestaBoard treats it as a new plugin: install it
  from the new URL, copy the settings over, update templates, and uninstall
  Wetter.

## [1.4.0] — 2026-10-24

### Added

- **Blank space** for the degree sign setting: `12 C` instead of `12°C`, for
  boards that print a heart at tile 62.

## [1.3.0] — 2026-10-24

### Changed

- The color settings offer **Contrast** and **Background** instead of *White*.
  Contrast (tile 69) is white on a black board and black on a white one;
  Background (tile 70) is the board's own color. A saved *White* keeps working
  as Contrast.

## [1.2.0] — 2026-10-24

### Added

- **Humidity** on the first row: `BEWOELKT 12°C 71%`. On a Note, where that
  is two tiles too many, the condition switches to a short form of six tiles
  or fewer (`WOLKIG 12°C 71%`) — the numbers always stay.
- `{{wetter.condition_short}}`, the short form on its own.

### Changed

- Cloudy and foggy days are **white** instead of yellow. The board has no grey
  tile; white is its most neutral one. *Color: cloudy or foggy* brings yellow
  back.

## [1.1.0] — 2026-10-24

### Changed

- The week overview is now the **calendar week, Monday to Sunday**. Days
  already past come from Open-Meteo's record of the actual weather. The
  setting **Week overview** replaces *Week starts today* and still offers the
  next seven days from today or tomorrow.
- The temperature follows the condition directly (`BEWOELKT 12°C`) instead of
  sitting at the right edge, and carries its unit.
- Today's low and high are marked with a **blue and a red tile** instead of
  the words MIN and MAX.
- The degree sign is shown on every board by default, the Note included.
  *Auto* still leaves it off on note-shaped boards.

## [1.0.0] — 2026-10-24

### Added

- Current condition and temperature, today's low and high, and a seven-day
  overview as one color tile per day, for any coordinates.
- Forecasts from Open-Meteo — no account or API key — in the location's own
  timezone.
- Day ratings: green for sunny, yellow for cloudy or foggy, red for rain, snow
  or thunder. Wet days under a configurable rain threshold (default 1 mm) are
  yellow, and all three colors can be changed.
- A compact layout for the Note (15×3) and a full one for boards of 20×6 and
  up, with weekday names, two-tile bars and the daily highs.
- German and English, metric and imperial, a week that starts today or
  tomorrow.
- Boards rendering the same location at the same time share one Open-Meteo
  call.
