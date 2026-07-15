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

    passed_candidates.sort(key=lambda c: c["volume_spike_ratio"], reverse=True)

    today = datetime.date.today().isoformat()
    output = {
        "run_date": today,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config": {
            "screens": config.SCREENER_SCREENS,
            "min_market_cap": config.MIN_MARKET_CAP,
            "min_price_change_pct": config.MIN_PRICE_CHANGE_PCT,
            "min_volume_spike_ratio": config.MIN_VOLUME_SPIKE_RATIO,
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
