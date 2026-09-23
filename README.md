# binaaz

Scrapes [bina.az](https://bina.az) real estate listings in Maştağa / Nardaran / Albalılıq / Buzovna and overlays them on an interactive bus routes map.

**[🗺️ Open Map](https://sinanbaymammadli.github.io/binaaz/houses_map.html)**

## What it does

- Scrapes heyet-evleri (houses) listings matching: 4+ rooms, ≤250,000 AZN, ≥3 sot land, çıxarış
- Fetches GPS coordinates and land area for each listing via bina.az GraphQL
- Calculates real walking distance to nearest AYNA bus stop (via OpenStreetMap routing)
- Sends Telegram alerts for new listings 3× a day (09:00, 15:00, 21:00 Baku time)
- Renders all listings on an interactive Google Maps overlay with AYNA bus routes 107, 150, 172, 177, 186, 189, M8

## Maps

| Map | Description |
|-----|-------------|
| [houses_map.html](https://sinanbaymammadli.github.io/binaaz/houses_map.html) | Heyet-evleri listings with walk times |
| [routes_map.html](https://sinanbaymammadli.github.io/binaaz/routes_map.html) | AYNA bus routes + torpaq listings |

## Deal Score

Each listing is scored 0–100 to indicate how good a deal it is relative to the current dataset. The score is recomputed every run across all listings so rankings stay accurate as new ones appear.

| Component | Max pts | Logic |
|---|---|---|
| Price per m² | 50 | Rank-normalized across all listings. Lowest price/m² = 50 pts, highest = 0 pts. |
| Walk to bus stop | 20 | `max(0, 20 × (1 − walk_min / 30))` — 0 min → 20 pts, 30+ min → 0 pts. |
| Bus line count | 10 | `min(10, lines × 2)` — 2 pts per line, capped at 5 lines. |
| Land efficiency | 15 | Sot per 100k AZN, rank-normalized. Most land per money = 15 pts. |
| Price drop bonus | 5 | +5 pts if current price < first recorded price. |

Score thresholds: 🟢 65+ · 🟡 40–64 · 🔴 <40

Map markers are colour-coded by score; the sidebar sorts by score by default. Telegram alerts include the score badge and price per m² / AZN per sot.

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
