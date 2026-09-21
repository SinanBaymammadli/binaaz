# binaaz

Scrapes [bina.az](https://bina.az) real estate listings in Maştağa / Nardaran / Albalılıq / Buzovna and overlays them on an interactive bus routes map.

**[🗺️ Open Map](https://sinanbaymammadli.github.io/binaaz/houses_map.html)**

## What it does

- Scrapes heyet-evleri (houses) listings matching: 4+ rooms, ≤300,000 AZN, ≥4 sot land, çıxarış
- Fetches GPS coordinates and land area for each listing via bina.az GraphQL
- Calculates real walking distance to nearest AYNA bus stop (via OpenStreetMap routing)
- Sends Telegram alerts for new listings 3× a day (09:00, 15:00, 21:00 Baku time)
- Renders all listings on an interactive Google Maps overlay with AYNA bus routes 107, 150, 172, 177, 186, 189, M8

## Maps

| Map | Description |
|-----|-------------|
| [houses_map.html](https://sinanbaymammadli.github.io/binaaz/houses_map.html) | Heyet-evleri listings with walk times |
| [routes_map.html](https://sinanbaymammadli.github.io/binaaz/routes_map.html) | AYNA bus routes + torpaq listings |

## Setup

Add these secrets to the GitHub repo (Settings → Secrets → Actions):

| Secret | Value |
|--------|-------|
| `TELEGRAM_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Channel or chat ID |

## Local usage

```bash
pip install camoufox && python -m camoufox fetch

# Scrape and update map
python scrape_houses.py

# Recalculate real walking distances
python calc_walk.py

# Regenerate map from saved data
python scrape_houses.py --map-only

# Run alert check manually
python notify.py
```
