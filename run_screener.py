#!/usr/bin/env python3
"""CLI entrypoint for the screener stage. Usage: python3 run_screener.py"""

from pipeline.screener import run_screener

if __name__ == "__main__":
    path, output = run_screener()
    print(f"Wrote {output['candidates_passed']} candidates to {path}")
    print(f"Universe pulled: {output['universe_pulled']}")
