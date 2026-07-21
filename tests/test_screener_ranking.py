"""Unit tests for the composite promise ranking (pipeline/screener.py).

Pure logic over synthetic candidates — no network. Covers the rank-percentile
helper and that the blended score orders candidates the way the weights intend.

Run: python3 -m pytest tests/test_screener_ranking.py  (or: python3 tests/test_screener_ranking.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.screener import _rank_percentile, rank_candidates  # noqa: E402


def _approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def _cand(symbol, volx, move, screens):
    return {"symbol": symbol, "volume_spike_ratio": volx,
            "change_percent": move, "source_screens": screens}


def test_rank_percentile_endpoints_and_midpoint():
    pct = _rank_percentile([10.0, 20.0, 30.0])
    assert _approx(pct[0], 0.0)   # lowest → 0
    assert _approx(pct[1], 0.5)   # middle → 0.5
    assert _approx(pct[2], 1.0)   # highest → 1


def test_rank_percentile_ties_share_average():
    pct = _rank_percentile([5.0, 5.0, 9.0])
    assert _approx(pct[0], pct[1])          # tied values get equal percentile
    assert _approx(pct[0], 0.25)            # average of ranks 0 and 1 → 0.5, /2 → 0.25
    assert _approx(pct[2], 1.0)


def test_rank_percentile_robust_to_outlier():
    # A 30x outlier must not compress the rest toward 0 (rank-based, not min-max).
    pct = _rank_percentile([1.3, 1.4, 1.5, 30.0])
    assert _approx(pct[1], 1 / 3)           # still evenly spaced by rank
    assert _approx(pct[2], 2 / 3)
    assert _approx(pct[3], 1.0)


def test_single_candidate_no_divide_by_zero():
    cands = rank_candidates([_cand("AAA", 2.0, 5.0, ["day_gainers"])])
    assert cands[0]["promise_score"] == round(0.5 * 1.0 + 0.3 * 1.0 + 0.2 * 0.0, 4)


def test_bigger_move_wins_when_volume_spike_tied():
    """When volume spikes are exactly tied, the larger price move breaks it.

    (In the full field, near-tied spikes land on adjacent ranks — a tiny
    percentile gap the move factor can overcome; this is the isolated version.)
    """
    cands = rank_candidates([
        _cand("SMALLMOVE", 1.52, 4.6, ["day_gainers"]),
        _cand("BIGMOVE", 1.52, 7.3, ["day_gainers"]),
    ])
    assert cands[0]["symbol"] == "BIGMOVE"  # tied spike → move decides


def test_multi_screen_corroboration_boosts_rank():
    """Same spike & move, but appearing in 3 screens beats appearing in 1."""
    cands = rank_candidates([
        _cand("SOLO", 2.0, 5.0, ["day_gainers"]),
        _cand("MULTI", 2.0, 5.0, ["day_gainers", "most_actives", "most_shorted_stocks"]),
    ])
    assert cands[0]["symbol"] == "MULTI"


def test_dominant_on_all_factors_ranks_first():
    cands = rank_candidates([
        _cand("WEAK", 1.3, 2.5, ["day_losers"]),
        _cand("MID", 2.0, 5.0, ["day_gainers"]),
        _cand("STRONG", 5.0, 12.0, ["day_gainers", "most_actives"]),
    ])
    assert [c["symbol"] for c in cands] == ["STRONG", "MID", "WEAK"]
    # Scores are in [0, 1] and descending.
    scores = [c["promise_score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


if __name__ == "__main__":
    fns = [g for name, g in sorted(globals().items()) if name.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
