#!/usr/bin/env python3
"""CLI entrypoint for the analyst briefing stage (stage 3a).

Reads the latest screener output, builds a six-domain research briefing for the
top candidates, and writes them to debate_output/ for the debate agents to read.

Usage:
    python3 run_briefings.py            # top-N from latest screener output
    python3 run_briefings.py IBM GS C   # explicit tickers instead
"""

import sys

from pipeline.analysts import run_briefings

if __name__ == "__main__":
    symbols = sys.argv[1:] or None
    path, output = run_briefings(symbols=symbols)
    print(f"Wrote {output['briefing_count']} briefings to {path}")
    for b in output["briefings"]:
        avail = [d for d, v in b["domains"].items()
                 if d == "macro" or v.get("available")]
        print(f"  {b['symbol']:6} {b['name'] or ''}  domains ok: {', '.join(avail)}")
