# Wetter Plugin

The weather for any coordinates on a Vestaboard Note: what it is doing outside right now, today's low and high, and the coming week as one colored tile per day.

```
BEWOELKT     12
MIN 7  MAX 14
S🟨S🟩M🟥D🟨M🟩D🟨F🟥
```

## Overview

Forecasts come from [Open-Meteo](https://open-meteo.com): free, no account, no API key, and addressed by latitude and longitude. Open-Meteo also works out the location's timezone, so "today" and the weekday names belong to the place you are showing, not to the machine FiestaBoard runs on.

Each day of the week overview is rated and gets a color tile:

| Tile | Rating | Weather |
|------|--------|---------|
| 🟩 green | good | sunny or mostly sunny (WMO 0–1) |
| 🟨 yellow | mixed | cloudy, overcast or fog (WMO 2–3, 45, 48) — or a wet day with less precipitation than the **rain threshold** |
| 🟥 red | bad | drizzle, rain, snow, showers or thunder (WMO 51 and up) |

The rain threshold (default 1 mm) is there because Open-Meteo reports the most severe weather of the day: one drizzly hour at 6 a.m. makes a day "drizzle" with 0.1 mm to show for it. The three colors can be changed in the settings.

### On a Note (15×3)

```
BEWOELKT     12      ← now: condition and temperature
MIN 7  MAX 14        ← today's low and high
S🟨S🟩M🟥D🟨M🟩D🟨F🟥    ← the week: weekday initial + tile, today first
```

Seven days in a row from today make the initials unambiguous: `S S M` on a Saturday can only be Saturday, Sunday, Monday.

### On a Flagship (22×6)

```
BEWOELKT           12°
MIN 7°  MAX 14°
REGEN 20%   WIND 14KMH
 SA SO MO DI MI DO FR
 🟨🟨 🟩🟩 🟥🟥 🟨🟨 🟩🟩 🟨🟨 🟥🟥
 14 16 12 13 15 14 10
```

The layout is picked from the board's size, not its type: anything at least 20×6 gets the Flagship layout, anything smaller the compact one. A board wider than 27 tiles writes the weekday names out in full on the compact layout (`SA🟨 SO🟩 …`).

The degree sign is left off on a Note by default — tile 62 is a degree sign on a Flagship but a heart, or nothing, on a Note.

## Setup

1. Install the plugin from its repository URL in FiestaBoard.
2. Open **Integrations → Wetter** and enter the **Coordinates**, e.g. `52.52, 13.405`. In Google Maps, right-click a spot and click the numbers at the top of the menu to copy them; OpenStreetMap shows them in the URL and under "Show address".
3. Enable the plugin and put `{{wetter.block}}` on the first line of a page, with the line set to left alignment and no wrap.

## Settings

| Setting | Default | |
|---------|---------|---|
| Coordinates | — | `latitude, longitude`. Comma, semicolon or space between them. |
| Location name | — | Only for `{{wetter.location}}`. |
| Language | Deutsch | Condition words and weekday names, `de` or `en`. |
| Units | Metric | Imperial asks Open-Meteo for °F, mph and inches. |
| Week starts today | on | Off shows the seven days after today. |
| Rain threshold (mm) | 1.0 | Wet days with less precipitation than this are yellow, not red. |
| Colors | green / yellow / red | One per rating. |
| Degree sign | Auto | Auto skips it on note-shaped boards. |
| Umlauts | Expand | `BEWOELKT` or `BEWOLKT`. |
| Refresh interval | 900 s | Minimum 300 s. Open-Meteo updates current conditions every 15 minutes. |

## Template Variables

### Now

| Variable | Description | Example |
|----------|-------------|---------|
| `{{wetter.condition}}` | Current condition | `BEWOELKT` |
| `{{wetter.temp}}` | Current temperature, whole degrees, no unit | `12` |
| `{{wetter.feels_like}}` | Apparent temperature | `10` |
| `{{wetter.temp_unit}}` | Unit suffix, board-aware | `°C` |
| `{{wetter.humidity}}` | Relative humidity in % | `71` |
| `{{wetter.wind}}` / `{{wetter.wind_unit}}` | Wind speed and unit | `14` / `KMH` |
| `{{wetter.color}}` | Today's color tile | `{65}` |
| `{{wetter.location}}` | Location name from the settings | `BERLIN` |

### Today

| Variable | Description | Example |
|----------|-------------|---------|
| `{{wetter.low}}` / `{{wetter.high}}` | Today's low and high | `7` / `14` |
| `{{wetter.rain_chance}}` | Highest chance of precipitation today, % | `20` |
| `{{wetter.rain}}` | Precipitation total today, mm or in | `0.0` |

### Week

| Variable | Description | Example |
|----------|-------------|---------|
| `{{wetter.week}}` | Initial + tile per day, 14 tiles | `S{65}S{66}M{63}…` |
| `{{wetter.week_tiles}}` | Just the seven tiles | `{65}{66}{63}…` |
| `{{wetter.days.N.name}}` | Weekday, N = 0…6 | `SA` |
| `{{wetter.days.N.condition}}` | The day's weather | `REGEN` |
| `{{wetter.days.N.high}}` / `.low` | High and low | `12` / `7` |
| `{{wetter.days.N.rain}}` / `.rain_chance` | Precipitation total and chance | `5.2` / `90` |
| `{{wetter.days.N.rating}}` / `.color` | `good`, `mixed` or `bad`, and its tile | `bad` / `{63}` |
| `{{wetter.days.N.date}}` | ISO date | `2026-10-26` |

### Board Lines

| Variable | Description |
|----------|-------------|
| `{{wetter.block}}` | The whole layout, rows separated by newlines — put it on the first template line |
| `{{wetter.line1}}` … `{{wetter.line6}}` | The same rows one by one, full board width; empty past the board's height |

### A page of your own

```
{{wetter.condition}} {{wetter.temp}}
{{wetter.low}}/{{wetter.high}} {{wetter.rain_chance}}%
{{wetter.week}}
```

## Development

The plugin imports `src.plugins.base` from the FiestaBoard core, so tests need the core repo checked out next to this one:

```bash
git clone https://github.com/Fiestaboard/FiestaBoard.git ../FiestaBoard

# Import paths matching how FiestaBoard loads the plugin
mkdir -p plugins && touch plugins/__init__.py
ln -sfn .. plugins/wetter

python -m venv .venv && .venv/bin/pip install pytest pytest-cov requests
PYTHONPATH=".:../FiestaBoard" .venv/bin/pytest tests/ --cov=. --cov-report=term-missing
```

No test touches the network: the forecast is a fixture, and the one function that speaks HTTP is stubbed. The board previews in `manifest.json` are rendered from that fixture, and a test fails if they drift from what the code produces.

## License

MIT
