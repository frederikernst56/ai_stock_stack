"""Stage 3b of the AI Stock Stack pipeline: debate persistence helpers.

The debate itself is run *interactively* — the orchestrator (a live Claude
session) reads each ticker's briefing, spawns the six domain-specialist
subagents defined in `.claude/agents/analyst-*.md`, and collects their
structured bull/bear verdicts. This module only handles the deterministic I/O
around that: pulling a ticker's briefing slice for a given domain, and writing
the collected verdicts to disk in a stable shape for stage 4 (synthesis).

Keeping I/O here (not in the agents) means the debate record is reproducible
and diff-able even though the reasoning step is a live model call.
"""

import datetime
import glob
import json
import os

from . import config

DOMAINS = ["technical", "fundamentals", "estimates", "news", "options", "macro"]


def latest_briefings_file(briefings_dir=None):
    briefings_dir = briefings_dir or config.DEBATE_OUTPUT_DIR
    files = sorted(glob.glob(os.path.join(briefings_dir, "*_briefings.json")))
    return files[-1] if files else None


def load_briefings(briefings_dir=None):
    path = latest_briefings_file(briefings_dir)
    if not path:
        raise FileNotFoundError("No *_briefings.json found — run run_briefings.py first")
    with open(path) as f:
        return json.load(f), path


def get_briefing(symbol, briefings_dir=None):
    """Return the full briefing dict for one symbol from the latest briefings file."""
    data, _ = load_briefings(briefings_dir)
    for b in data["briefings"]:
        if b["symbol"] == symbol:
            return b
    raise KeyError(f"{symbol} not in latest briefings file")


def domain_payload(symbol, domain, briefings_dir=None):
    """Build the exact JSON payload to hand a domain agent for one ticker.

    Macro is shared across tickers, so it's pulled from the run-level snapshot;
    every other domain comes from the ticker's own briefing slice.
    """
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain!r}")
    briefing = get_briefing(symbol, briefings_dir)
    payload = {
        "symbol": symbol,
        "name": briefing.get("name"),
        "spot_price": briefing.get("spot_price"),
    }
    if domain == "macro":
        payload["sector"] = briefing["domains"]["fundamentals"].get("profile", {}).get("sector")
        payload["industry"] = briefing["domains"]["fundamentals"].get("profile", {}).get("industry")
        payload["macro"] = briefing["domains"]["macro"]
    else:
        payload[domain] = briefing["domains"][domain]
    return payload


def save_debate(symbol, agent_verdicts, spot_price=None, output_dir=None):
    """Append (or replace) one ticker's debate verdicts in today's debate file.

    `agent_verdicts` is the list of the six domain JSON objects the subagents
    returned. Re-running a symbol overwrites its prior entry so the file stays
    idempotent within a run.
    """
    output_dir = output_dir or config.DEBATE_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    path = os.path.join(output_dir, f"{today}_debate.json")

    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
    else:
        data = {"run_date": today, "debates": []}

    entry = {
        "symbol": symbol,
        "spot_price": spot_price,
        "debated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "agent_verdicts": agent_verdicts,
    }
    data["debates"] = [d for d in data["debates"] if d["symbol"] != symbol]
    data["debates"].append(entry)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path
