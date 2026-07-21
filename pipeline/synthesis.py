"""Stage 4 of the AI Stock Stack pipeline: synthesis.

Stage 3 leaves us, per ticker, six independent analyst verdicts — each a
`lean` (bull/bear/neutral), a `conviction` (0–1), a `confidence`
(high/medium/low), and supporting bull/bear cases. This stage collapses those
six voices into a single directional call with a defensible, diff-able score,
then ranks the debated tickers.

The scoring is deliberately deterministic (no model call here): the debate
already did the reasoning, so synthesis is pure arithmetic over its output. That
keeps the ranking reproducible and lets us explain *why* a ticker scored where
it did — nothing is a black box.

Scoring, per ticker
-------------------
Each analyst i contributes:
  sign(lean_i)   ∈ {+1 bull, 0 neutral, -1 bear}
  conviction_i   ∈ [0, 1]                          how hard they lean
  w_i            ∈ {1.0, 0.6, 0.3}                 a data-quality weight from
                                                   `confidence` (high/med/low)

Two headline numbers come out:

  directional_score  S = Σ wᵢ·signᵢ·convictionᵢ / Σ wᵢ          ∈ [-1, +1]
      Net strength. Positive = the panel leans bullish. Opposing analysts
      cancel here, and (high-confidence) neutrals dilute toward zero, so a
      split panel already scores near flat.

  agreement          A = winning-side weight / total weight        ∈ [0, 1]
      Breadth of consensus. "Winning side" is whichever direction S points.
      Six unanimous bulls → 1.0; four bulls + two neutrals → 0.67; a clean
      3-bull/3-bear split → ~0.5. Neutrals sit in the denominator, so they
      cost breadth too.

  agreement_weighted_score = S · Aᵏ                                ∈ [-1, +1]
      The ranking number. S captures how hard the panel leans; A captures how
      many lean that way. Multiplying penalizes a call that's strong but narrow
      (one loud analyst, everyone else quiet) versus one that's broad.

      The exponent k (config.SYNTHESIS_AGREEMENT_EXPONENT) sets *how much*
      breadth matters — it's the consensus-vs-conviction knob:
        k=1  consensus-seeking (default): a broadly-but-mildly liked name can
             outrank a stronger-but-contested one.
        k=0  conviction-seeking: A⁰=1, so agreement drops out and ranking is by
             net directional strength S alone — disagreement is edge, not risk.
        0<k<1  dials between the two.
"""

import datetime
import glob
import json
import os

from . import config

# confidence → data-quality weight. A low-confidence analyst (thin/stale data)
# still counts, but at ~a third of a high-confidence one.
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3}
DEFAULT_CONFIDENCE_WEIGHT = CONFIDENCE_WEIGHTS["low"]

LEAN_SIGN = {"bull": 1, "bear": -1, "neutral": 0}

# |S| below this reads as "no net direction" — label the call neutral rather
# than forcing a bull/bear tag onto noise.
NEUTRAL_BAND = 0.05


def _confidence_weight(confidence):
    if not isinstance(confidence, str):
        return DEFAULT_CONFIDENCE_WEIGHT
    return CONFIDENCE_WEIGHTS.get(confidence.strip().lower(), DEFAULT_CONFIDENCE_WEIGHT)


def _lean_sign(lean):
    if not isinstance(lean, str):
        return 0
    return LEAN_SIGN.get(lean.strip().lower(), 0)


def _conviction(value):
    """Clamp a verdict's conviction into [0, 1]; treat garbage as 0."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, c))


def score_verdicts(agent_verdicts, agreement_exponent=None):
    """Turn one ticker's six analyst verdicts into a synthesized call.

    `agreement_exponent` (k) is the consensus-vs-conviction knob applied as
    S·Aᵏ; defaults to config.SYNTHESIS_AGREEMENT_EXPONENT. See module docstring.

    Returns a dict with the two headline numbers, the ranking score, and the
    per-analyst breakdown that produced them (so the math is inspectable).
    """
    if agreement_exponent is None:
        agreement_exponent = config.SYNTHESIS_AGREEMENT_EXPONENT
    contributions = []
    total_weight = 0.0
    signed_sum = 0.0
    bull_weight = 0.0
    bear_weight = 0.0

    for v in agent_verdicts:
        sign = _lean_sign(v.get("lean"))
        conviction = _conviction(v.get("conviction"))
        weight = _confidence_weight(v.get("confidence"))

        total_weight += weight
        signed_sum += weight * sign * conviction
        if sign > 0:
            bull_weight += weight
        elif sign < 0:
            bear_weight += weight

        contributions.append({
            "domain": v.get("domain"),
            "lean": v.get("lean"),
            "conviction": round(conviction, 3),
            "confidence": v.get("confidence"),
            "weight": weight,
            # Signed strength this analyst pushes into S, before normalizing.
            "contribution": round(weight * sign * conviction, 4),
            "one_line": v.get("one_line"),
        })

    directional_score = signed_sum / total_weight if total_weight else 0.0

    if directional_score > NEUTRAL_BAND:
        direction = "bull"
        agreement = bull_weight / total_weight if total_weight else 0.0
    elif directional_score < -NEUTRAL_BAND:
        direction = "bear"
        agreement = bear_weight / total_weight if total_weight else 0.0
    else:
        direction = "neutral"
        # No net direction: agreement measures how *little* dissent there is,
        # i.e. how much weight sat on neutral rather than either pole.
        agreement = (total_weight - bull_weight - bear_weight) / total_weight if total_weight else 0.0

    agreement_weighted_score = directional_score * (agreement ** agreement_exponent)

    # Analysts leaning opposite the net call — the disagreement worth reading.
    consensus_sign = _lean_sign(direction)
    dissenters = [
        {"domain": c["domain"], "lean": c["lean"],
         "conviction": c["conviction"], "one_line": c["one_line"]}
        for c in contributions
        if consensus_sign != 0 and _lean_sign(c["lean"]) == -consensus_sign
    ]

    return {
        "direction": direction,
        "directional_score": round(directional_score, 4),
        "agreement": round(agreement, 4),
        "agreement_exponent": agreement_exponent,
        "agreement_weighted_score": round(agreement_weighted_score, 4),
        "lean_counts": {
            "bull": sum(1 for c in contributions if _lean_sign(c["lean"]) > 0),
            "bear": sum(1 for c in contributions if _lean_sign(c["lean"]) < 0),
            "neutral": sum(1 for c in contributions if _lean_sign(c["lean"]) == 0),
        },
        "dissenters": dissenters,
        "contributions": contributions,
    }


def synthesize_debate(debate_data, agreement_exponent=None):
    """Score every ticker in a loaded debate file and rank them.

    Ranking is by `agreement_weighted_score`, most bullish first — so the top of
    the list is where the panel most broadly and strongly wants to be long.
    `agreement_exponent` overrides config.SYNTHESIS_AGREEMENT_EXPONENT if given.
    """
    results = []
    for entry in debate_data.get("debates", []):
        synthesis = score_verdicts(entry.get("agent_verdicts", []), agreement_exponent)
        results.append({
            "symbol": entry.get("symbol"),
            "spot_price": entry.get("spot_price"),
            **synthesis,
        })

    results.sort(key=lambda r: r["agreement_weighted_score"], reverse=True)
    for rank, r in enumerate(results, start=1):
        r["rank"] = rank
    return results


def latest_debate_file(debate_dir=None):
    debate_dir = debate_dir or config.DEBATE_OUTPUT_DIR
    files = sorted(glob.glob(os.path.join(debate_dir, "*_debate.json")))
    return files[-1] if files else None


def run_synthesis(debate_dir=None, output_dir=None, agreement_exponent=None):
    """Load the latest debate file, score + rank it, and write the synthesis.

    `agreement_exponent` overrides config.SYNTHESIS_AGREEMENT_EXPONENT if given.
    Returns (output_path, output_dict).
    """
    debate_dir = debate_dir or config.DEBATE_OUTPUT_DIR
    output_dir = output_dir or config.DEBATE_OUTPUT_DIR
    if agreement_exponent is None:
        agreement_exponent = config.SYNTHESIS_AGREEMENT_EXPONENT

    source_file = latest_debate_file(debate_dir)
    if not source_file:
        raise FileNotFoundError(f"No *_debate.json found in {debate_dir}/ — run the debate stage first")
    with open(source_file) as f:
        debate_data = json.load(f)

    rankings = synthesize_debate(debate_data, agreement_exponent)

    run_date = debate_data.get("run_date") or datetime.date.today().isoformat()
    output = {
        "run_date": run_date,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_debate_file": source_file,
        "confidence_weights": CONFIDENCE_WEIGHTS,
        "agreement_exponent": agreement_exponent,
        "ranking_metric": "agreement_weighted_score",
        "ticker_count": len(rankings),
        "rankings": rankings,
    }

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{run_date}_synthesis.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output_path, output
