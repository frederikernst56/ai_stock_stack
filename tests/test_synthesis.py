"""Unit tests for stage 4 scoring (pipeline/synthesis.py).

Pure arithmetic over synthetic verdicts — no network, no debate file. Covers the
headline formulas and the edge cases that would otherwise divide by zero
(all-neutral panel, empty panel).

Run: python3 -m pytest tests/test_synthesis.py   (or: python3 tests/test_synthesis.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.synthesis import score_verdicts, synthesize_debate  # noqa: E402


def _v(domain, lean, conviction, confidence):
    return {"domain": domain, "lean": lean, "conviction": conviction,
            "confidence": confidence, "one_line": f"{domain} says {lean}"}


def _approx(a, b, tol=1e-4):
    return abs(a - b) < tol


def test_unanimous_high_confidence_bull():
    """Six high-confidence bulls at conviction 0.8 → S=0.8, full agreement."""
    verdicts = [_v(d, "bull", 0.8, "high") for d in
                ["technical", "fundamentals", "estimates", "news", "options", "macro"]]
    r = score_verdicts(verdicts)
    assert r["direction"] == "bull"
    assert _approx(r["directional_score"], 0.8)
    assert _approx(r["agreement"], 1.0)
    assert _approx(r["agreement_weighted_score"], 0.8)
    assert r["dissenters"] == []


def test_clean_split_scores_near_flat():
    """3 bulls vs 3 bears at equal conviction/confidence → S≈0, direction neutral."""
    verdicts = (
        [_v(f"b{i}", "bull", 0.6, "high") for i in range(3)] +
        [_v(f"x{i}", "bear", 0.6, "high") for i in range(3)]
    )
    r = score_verdicts(verdicts)
    assert _approx(r["directional_score"], 0.0)
    assert r["direction"] == "neutral"
    assert r["lean_counts"] == {"bull": 3, "bear": 3, "neutral": 0}


def test_confidence_weighting_shrinks_low_conf_voices():
    """One high-conf bull vs one low-conf bear: bull wins on data-quality weight."""
    verdicts = [_v("t", "bull", 0.6, "high"), _v("n", "bear", 0.6, "low")]
    r = score_verdicts(verdicts)
    # signed_sum = 1.0*0.6 - 0.3*0.6 = 0.42 ; total_weight = 1.3
    assert _approx(r["directional_score"], 0.42 / 1.3)
    assert r["direction"] == "bull"


def test_narrow_call_penalized_by_agreement():
    """One loud bull + five neutrals: S is muted AND agreement (breadth) is low."""
    verdicts = [_v("t", "bull", 0.9, "high")] + \
               [_v(f"n{i}", "neutral", 0.2, "high") for i in range(5)]
    r = score_verdicts(verdicts)
    # Only one of six weight-units leans → agreement is 1/6 of total weight.
    assert _approx(r["agreement"], 1.0 / 6.0)
    # Agreement-weighted score sits well below the raw directional score.
    assert abs(r["agreement_weighted_score"]) < abs(r["directional_score"])


def test_dissenters_surface_opposite_leans():
    verdicts = [_v(f"b{i}", "bear", 0.7, "high") for i in range(4)] + \
               [_v("f", "bull", 0.5, "high"), _v("m", "neutral", 0.3, "medium")]
    r = score_verdicts(verdicts)
    assert r["direction"] == "bear"
    assert [d["domain"] for d in r["dissenters"]] == ["f"]  # only the bull dissents


def test_all_neutral_panel_no_divide_by_zero():
    verdicts = [_v(d, "neutral", 0.0, "low") for d in ["a", "b", "c"]]
    r = score_verdicts(verdicts)
    assert r["direction"] == "neutral"
    assert r["directional_score"] == 0.0
    assert r["agreement"] == 1.0  # all weight sits on neutral → no dissent


def test_empty_panel_no_divide_by_zero():
    r = score_verdicts([])
    assert r["direction"] == "neutral"
    assert r["directional_score"] == 0.0
    assert r["agreement"] == 0.0


def test_malformed_fields_treated_as_neutral_zero():
    verdicts = [
        {"domain": "x", "lean": "up", "conviction": "n/a", "confidence": "great"},
        {"domain": "y"},  # missing everything
    ]
    r = score_verdicts(verdicts)
    assert r["direction"] == "neutral"
    assert r["directional_score"] == 0.0


def test_agreement_exponent_zero_ignores_breadth():
    """k=0 → A⁰=1, so the score is the raw directional strength S (agreement drops out)."""
    verdicts = [_v("t", "bull", 0.9, "high")] + \
               [_v(f"n{i}", "neutral", 0.2, "high") for i in range(5)]
    contested = score_verdicts(verdicts, agreement_exponent=0.0)
    consensus = score_verdicts(verdicts, agreement_exponent=1.0)
    # With k=0 the score equals S exactly; with k=1 breadth shrinks it.
    assert _approx(contested["agreement_weighted_score"], contested["directional_score"])
    assert abs(consensus["agreement_weighted_score"]) < abs(contested["agreement_weighted_score"])


def test_agreement_exponent_can_flip_ranking():
    """Broad-but-mild vs strong-but-contested flip depending on k."""
    broad_mild = [_v(f"a{i}", "bull", 0.30, "high") for i in range(6)]
    strong_contested = [_v(f"b{i}", "bull", 0.90, "high") for i in range(4)] + \
                       [_v(f"c{i}", "bear", 0.75, "high") for i in range(2)]
    debate = {"debates": [
        {"symbol": "BROAD", "agent_verdicts": broad_mild},
        {"symbol": "CONTESTED", "agent_verdicts": strong_contested},
    ]}
    # k=1 (consensus): broad-but-mild wins.
    assert [r["symbol"] for r in synthesize_debate(debate, 1.0)][0] == "BROAD"
    # k=0 (conviction): strong-but-contested wins on raw strength.
    assert [r["symbol"] for r in synthesize_debate(debate, 0.0)][0] == "CONTESTED"


def test_synthesize_ranks_by_agreement_weighted_score_desc():
    debate = {"debates": [
        {"symbol": "AAA", "spot_price": 10,
         "agent_verdicts": [_v(d, "bear", 0.8, "high") for d in ["a", "b", "c"]]},
        {"symbol": "BBB", "spot_price": 20,
         "agent_verdicts": [_v(d, "bull", 0.8, "high") for d in ["a", "b", "c"]]},
    ]}
    ranked = synthesize_debate(debate)
    assert [r["symbol"] for r in ranked] == ["BBB", "AAA"]  # most bullish first
    assert [r["rank"] for r in ranked] == [1, 2]


if __name__ == "__main__":
    fns = [g for name, g in sorted(globals().items()) if name.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
