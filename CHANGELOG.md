# Changelog

All notable changes to this plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version here is the source of truth for `manifest.json` — a test fails if
the two drift apart.

## [Unreleased]

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
