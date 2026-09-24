"""
Compute a deal score (0-100) for each listing based on available signals.

Components:
  50 pts — effective price per m² (lower is better, percentile-ranked)
           Unrepaired houses get +200 AZN/m² renovation cost added to price
           before ranking so repaired vs unrepaired are compared fairly.
  30 pts — transit (20 pts for walk time + 10 pts for bus line count)
  15 pts — land efficiency: sot per 100k AZN (higher is better, percentile-ranked)
   5 pts — price drop bonus (price went down since first observation)
"""

RENOVATION_COST_PER_M2 = 200  # AZN — estimated renovation cost for unrepaired house


def compute_land_scores(listings: list[dict]) -> list[dict]:
    """
    Score land plots 0-100.
      70 pts — price per sot (lower is better, percentile-ranked)
      25 pts — transit (15 pts walk time + 10 pts bus line count)
       5 pts — price drop bonus
    """
    pps: list[float | None] = []
    for l in listings:
        sot = l.get("land_area_sot")
        price = l.get("price")
        pps.append(price / sot if sot and price else None)

    valid_idx = [i for i, v in enumerate(pps) if v is not None]
    pps_scores_valid = _pct_scores([pps[i] for i in valid_idx], lower_is_better=True)
    pps_scores: list[float | None] = [None] * len(listings)
    for rank_i, list_i in enumerate(valid_idx):
        pps_scores[list_i] = pps_scores_valid[rank_i]

    for i, l in enumerate(listings):
        score = 0.0

        if pps_scores[i] is not None:
            score += 70 * pps_scores[i]

        walk = l.get("walk_min")
        if walk is not None:
            score += max(0.0, 15.0 * (1 - walk / 30))
        score += min(10, len(l.get("bus_lines") or []) * 2)

        history = l.get("price_history") or []
        if len(history) >= 2 and history[-1]["price"] < history[0]["price"]:
            score += 5

        l["deal_score"] = round(score)

    return listings


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

    # --- effective price per m² (renovation-adjusted) ---
    # has_repair=False → add RENOVATION_COST_PER_M2 per m² to make costs comparable
    ppm2: list[float | None] = []
    for l in listings:
        area = _parse_area(l.get("area_m2"))
        price = l.get("price")
        if area and price:
            reno = RENOVATION_COST_PER_M2 * area if l.get("has_repair") is False else 0
            ppm2.append((price + reno) / area)
        else:
            ppm2.append(None)

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
