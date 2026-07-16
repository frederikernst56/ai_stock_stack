"""Shared configuration for the AI Stock Stack pipeline."""

# --- Screener ---

# Yahoo Finance predefined screens to pull candidates from (yfinance.screen names).
# day_gainers catches the biggest % movers; most_actives catches volume spikes that
# aren't necessarily top % gainers (e.g. a large-cap moving 2% on 5x normal volume).
SCREENER_SCREENS = ["day_gainers", "most_actives"]

# How many results to pull per screen before filtering.
SCREENER_PULL_COUNT = 100

# Filter rules applied to the combined candidate pool:

# Exclude micro/nano-caps and penny stocks - noisy, hard to trade at size, and prone
# to single-headline whipsaws that don't reflect the kind of thesis this pipeline debates.
MIN_MARKET_CAP = 300_000_000  # $300M

# Require a real intraday move, not noise.
MIN_PRICE_CHANGE_PCT = 3.0  # percent

# Require day volume meaningfully above the norm - signals unusual interest/catalyst.
MIN_VOLUME_SPIKE_RATIO = 1.5  # day volume / 3-month average daily volume

# --- Output ---

SCREENER_OUTPUT_DIR = "screener_output"


# --- Debate stage (analyst briefings + multi-agent debate) ---

# How many of the screener's passed candidates to run the full debate on.
# The screener can pass ~20+ tickers; debating all of them is expensive (six
# live subagents each). Debate the strongest movers first, ranked as the
# screener already sorts them (by volume-spike ratio).
DEBATE_TOP_N = 5

# Where per-run analyst briefings and debate results are written.
DEBATE_OUTPUT_DIR = "debate_output"

# Technical-analysis parameters for the briefing layer.
TECH_HISTORY_PERIOD = "1y"      # yfinance history window (needs ~1y for the 200-day MA)
TECH_RSI_PERIOD = 14
TECH_MA_WINDOWS = [20, 50, 200]  # simple moving averages to report

# Macro context tickers (index/rate proxies) pulled once per run, not per-stock.
# Kept light on purpose: the Macro analyst reads the regime, it doesn't model it.
MACRO_TICKERS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "vix": "^VIX",          # volatility / risk appetite
    "ten_year_yield": "^TNX",  # 10Y Treasury yield (x10)
    "dollar_index": "DX-Y.NYB",
    "oil_wti": "CL=F",
}

