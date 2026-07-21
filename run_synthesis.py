#!/usr/bin/env python3
"""CLI entrypoint for the synthesis stage (stage 4).

Reads the latest debate output, collapses each ticker's six analyst verdicts
into one directional call with an agreement-weighted score, ranks the tickers,
and writes debate_output/<date>_synthesis.json.

Usage:
    python3 run_synthesis.py           # uses config.SYNTHESIS_AGREEMENT_EXPONENT
    python3 run_synthesis.py 0.0       # override: ignore agreement (rank by strength)
    python3 run_synthesis.py 1.0       # override: full consensus-weighting
"""

import sys

from pipeline.synthesis import run_synthesis


def _fmt(x):
    return f"{x:+.3f}" if isinstance(x, (int, float)) else str(x)


if __name__ == "__main__":
    exponent = float(sys.argv[1]) if len(sys.argv) > 1 else None
    path, output = run_synthesis(agreement_exponent=exponent)
    print(f"Wrote synthesis for {output['ticker_count']} tickers to {path}  "
          f"(agreement_exponent={output['agreement_exponent']})\n")
    print(f"  {'#':>2}  {'TICKER':6} {'CALL':8} {'SCORE':>7} {'DIR':>7} {'AGREE':>6}  leans")
    for r in output["rankings"]:
        c = r["lean_counts"]
        leans = f"{c['bull']}B/{c['bear']}Be/{c['neutral']}N"
        print(f"  {r['rank']:>2}  {r['symbol']:6} {r['direction']:8} "
              f"{_fmt(r['agreement_weighted_score']):>7} "
              f"{_fmt(r['directional_score']):>7} {r['agreement']:>6.2f}  {leans}")
