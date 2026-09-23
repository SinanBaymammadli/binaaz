"""
Compute a deal score (0-100) for each listing based on available signals.

Components:
  50 pts — price per m² (lower is better, percentile-ranked)
  30 pts — transit (20 pts for walk time + 10 pts for bus line count)
  15 pts — land efficiency: sot per 100k AZN (higher is better, percentile-ranked)
   5 pts — price drop bonus (price went down since first observation)
"""


def _parse_area(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(" m²", "").replace(",", "."))
    except ValueError:
        return None


def _pct_scores(values: list[float], lower_is_better: bool = True) -> list[float]:
    """Rank-based percentile scores 0-1. Handles ties by averaging their ranks."""
    n = len(values)
    if n <= 1:
        return [0.5] * n
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    out = [0.0] * n
    for rank, (i, _) in enumerate(indexed):
        out[i] = rank / (n - 1)
    if lower_is_better:
        out = [1.0 - s for s in out]
    return out


def compute_deal_scores(listings: list[dict]) -> list[dict]:
    """Return listings with a `deal_score` (int 0-100) added to each dict."""

    # --- price per m² ---
    ppm2: list[float | None] = []
    for l in listings:
        area = _parse_area(l.get("area_m2"))
        price = l.get("price")
        ppm2.append(price / area if area and price else None)

    valid_idx = [i for i, v in enumerate(ppm2) if v is not None]
    valid_ppm2 = [ppm2[i] for i in valid_idx]
    ppm2_scores_valid = _pct_scores(valid_ppm2, lower_is_better=True)
    ppm2_scores: list[float | None] = [None] * len(listings)
    for rank_i, list_i in enumerate(valid_idx):
        ppm2_scores[list_i] = ppm2_scores_valid[rank_i]

    # --- land efficiency: sot per 100k AZN ---
    land_eff: list[float | None] = []
    for l in listings:
        sot = l.get("land_area_sot")
        price = l.get("price")
        land_eff.append(sot / price * 100_000 if sot and price else None)

    valid_land_idx = [i for i, v in enumerate(land_eff) if v is not None]
    valid_land = [land_eff[i] for i in valid_land_idx]
    land_scores_valid = _pct_scores(valid_land, lower_is_better=False)
    land_scores: list[float | None] = [None] * len(listings)
    for rank_i, list_i in enumerate(valid_land_idx):
        land_scores[list_i] = land_scores_valid[rank_i]

    # --- assemble scores ---
    for i, l in enumerate(listings):
        score = 0.0

        # Price per m² (50 pts)
        if ppm2_scores[i] is not None:
            score += 50 * ppm2_scores[i]

        # Transit: walk time (20 pts) + bus lines (10 pts)
        walk = l.get("walk_min")
        if walk is not None:
            score += max(0.0, 20.0 * (1 - walk / 30))
        score += min(10, len(l.get("bus_lines") or []) * 2)

        # Land efficiency (15 pts)
        if land_scores[i] is not None:
            score += 15 * land_scores[i]

        # Price drop bonus (5 pts)
        history = l.get("price_history") or []
        if len(history) >= 2 and history[-1]["price"] < history[0]["price"]:
            score += 5

        l["deal_score"] = round(score)

    return listings
