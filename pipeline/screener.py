"""Stage 2 of the AI Stock Stack pipeline: screener.

Pulls candidate tickers from Yahoo Finance's predefined screens (via yfinance,
no API key required), filters them against the playbook's rule set (volume
spike, price move, market cap floor), and writes the surviving candidates to
a dated JSON file for the next pipeline stage (multi-agent debate) to consume.
"""

import datetime
import json
import os

import yfinance as yf

from . import config


def fetch_candidates(screens=None, count=None):
    """Pull raw candidates from the given Yahoo Finance screens, deduped by symbol.

    Returns a dict of {symbol: candidate_dict}. Each candidate records every
    screen it appeared in, since showing up in multiple screens is itself signal.
    """
    screens = screens or config.SCREENER_SCREENS
    count = count or config.SCREENER_PULL_COUNT

    candidates = {}
    pulled_counts = {}

    for screen_name in screens:
        result = yf.screen(screen_name, count=count)
        quotes = result.get("quotes", [])
        pulled_counts[screen_name] = len(quotes)

        for quote in quotes:
            symbol = quote.get("symbol")
            if not symbol:
                continue

            if symbol not in candidates:
                candidates[symbol] = {
                    "symbol": symbol,
                    "name": quote.get("longName") or quote.get("shortName"),
                    "price": quote.get("regularMarketPrice"),
                    "change_percent": quote.get("regularMarketChangePercent"),
                    "day_volume": quote.get("regularMarketVolume"),
                    "avg_volume_3m": quote.get("averageDailyVolume3Month"),
                    "market_cap": quote.get("marketCap"),
                    "sector": quote.get("sector"),
                    "exchange": quote.get("fullExchangeName"),
                    "source_screens": [],
                }
            candidates[symbol]["source_screens"].append(screen_name)

    return candidates, pulled_counts


def apply_filters(candidate):
    """Check a candidate against the configured rule thresholds.

    Returns (passed: bool, reasons: dict) where reasons records the computed
    metric and pass/fail per rule, for transparency in the output file.
    """
    market_cap = candidate.get("market_cap")
    change_percent = candidate.get("change_percent")
    day_volume = candidate.get("day_volume")
    avg_volume_3m = candidate.get("avg_volume_3m")

    # Missing data (common for thinly-covered tickers) fails closed, not open.
    if None in (market_cap, change_percent, day_volume, avg_volume_3m) or not avg_volume_3m:
        return False, {"error": "missing required fields"}

    volume_spike_ratio = day_volume / avg_volume_3m

    reasons = {
        "market_cap": {"value": market_cap, "min": config.MIN_MARKET_CAP,
                        "passed": market_cap >= config.MIN_MARKET_CAP},
        "change_percent": {"value": change_percent, "min": config.MIN_PRICE_CHANGE_PCT,
                            "passed": abs(change_percent) >= config.MIN_PRICE_CHANGE_PCT},
        "volume_spike_ratio": {"value": round(volume_spike_ratio, 2), "min": config.MIN_VOLUME_SPIKE_RATIO,
                                "passed": volume_spike_ratio >= config.MIN_VOLUME_SPIKE_RATIO},
    }
    passed = all(r["passed"] for r in reasons.values())

    candidate["volume_spike_ratio"] = round(volume_spike_ratio, 2)
    return passed, reasons


def _rank_percentile(values):
    """Map each value to its rank-percentile in [0, 1] (0 = lowest, 1 = highest).

    Ties share their average rank. Using ranks rather than raw magnitudes makes
    the blend robust to outliers — one 30x volume spike lifts that name to the
    top without swamping the price-move and corroboration factors for everyone
    else, which a raw-value normalization (min-max) would do.
    """
    n = len(values)
    if n <= 1:
        return [1.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0  # average rank for this tie-group
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return [r / (n - 1) for r in ranks]


def rank_candidates(candidates):
    """Sort passing candidates by a composite promise score (highest first).

    Annotates each candidate with `promise_score` and its `promise_components`
    so the ranking is inspectable, mirroring the screener's `filter_reasons`.
    """
    if not candidates:
        return candidates

    weights = config.PROMISE_WEIGHTS
    vspike_pct = _rank_percentile([c["volume_spike_ratio"] for c in candidates])
    move_pct = _rank_percentile([abs(c["change_percent"]) for c in candidates])
    screen_counts = [len(c["source_screens"]) for c in candidates]
    max_screens = max(screen_counts)

    for i, c in enumerate(candidates):
        # Corroboration: 0 for a single-screen name, 1 for the most-corroborated.
        corroboration = (screen_counts[i] - 1) / (max_screens - 1) if max_screens > 1 else 0.0
        score = (weights["volume_spike"] * vspike_pct[i]
                 + weights["price_move"] * move_pct[i]
                 + weights["corroboration"] * corroboration)
        c["promise_score"] = round(score, 4)
        c["promise_components"] = {
            "volume_spike_pct": round(vspike_pct[i], 3),
            "price_move_pct": round(move_pct[i], 3),
            "corroboration": round(corroboration, 3),
        }

    candidates.sort(key=lambda c: c["promise_score"], reverse=True)
    return candidates


def run_screener(output_dir=None):
    """Fetch, filter, and write today's screener output. Returns the output file path."""
    output_dir = output_dir or config.SCREENER_OUTPUT_DIR

    raw_candidates, pulled_counts = fetch_candidates()

    passed_candidates = []
    for candidate in raw_candidates.values():
        passed, reasons = apply_filters(candidate)
        candidate["filter_reasons"] = reasons
        if passed:
            passed_candidates.append(candidate)

    # Rank by composite promise score so the debate cap keeps the strongest
    # setups, not whoever happened to edge out a volume-spike near-tie.
    rank_candidates(passed_candidates)

    today = datetime.date.today().isoformat()
    output = {
        "run_date": today,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config": {
            "screens": config.SCREENER_SCREENS,
            "min_market_cap": config.MIN_MARKET_CAP,
            "min_price_change_pct": config.MIN_PRICE_CHANGE_PCT,
            "min_volume_spike_ratio": config.MIN_VOLUME_SPIKE_RATIO,
            "promise_weights": config.PROMISE_WEIGHTS,
        },
        "universe_pulled": {**pulled_counts, "total_unique": len(raw_candidates)},
        "candidates_passed": len(passed_candidates),
        "candidates": passed_candidates,
    }

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{today}.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output_path, output
