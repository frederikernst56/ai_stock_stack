"""Shared configuration for the AI Stock Stack pipeline."""

# --- Screener ---

# Yahoo Finance predefined screens to pull candidates from (yfinance.screen names).
# The debate is direction-agnostic (it argues bull AND bear), so we cast a wide net
# over movers in both directions and across cap tiers:
#   day_gainers       — biggest % up-movers
#   day_losers        — biggest % down-movers (short setups / oversold bounces)
#   most_actives      — volume spikes that aren't top % movers (large-cap on 5x volume)
#   small_cap_gainers — smaller names that the large-cap-tilted screens miss
#   most_shorted_stocks — high short interest (squeeze potential vs. weak fundamentals)
SCREENER_SCREENS = [
    "day_gainers",
    "day_losers",
    "most_actives",
    "small_cap_gainers",
    "most_shorted_stocks",
]

# How many results to pull per screen before filtering.
SCREENER_PULL_COUNT = 100

# Filter rules applied to the combined candidate pool:

# Exclude micro/nano-caps and penny stocks - noisy, hard to trade at size, and prone
# to single-headline whipsaws that don't reflect the kind of thesis this pipeline debates.
MIN_MARKET_CAP = 300_000_000  # $300M

# Require a real intraday move, not noise. Widened from 3.0 → 2.5 to surface more
# candidates for the weekly run; the debate stage does the deeper vetting.
MIN_PRICE_CHANGE_PCT = 2.5  # percent

# Require day volume meaningfully above the norm - signals unusual interest/catalyst.
# Widened from 1.5 → 1.3 for broader weekly coverage.
MIN_VOLUME_SPIKE_RATIO = 1.3  # day volume / 3-month average daily volume

# --- Output ---

SCREENER_OUTPUT_DIR = "screener_output"


# --- Debate stage (analyst briefings + multi-agent debate) ---

# Debate ALL candidates the screener passes, up to this safety cap. Each ticker
# costs six live subagents, so the cap bounds a wild market week (when the wider
# net can pass many names) rather than throttling a normal one. Candidates are
# taken in the screener's own order (strongest volume spike first), so if the cap
# bites, the most unusual movers still make the cut.
DEBATE_MAX_CANDIDATES = 25

# Where per-run analyst briefings and debate results are written.
DEBATE_OUTPUT_DIR = "debate_output"

# Technical-analysis parameters for the briefing layer.
TECH_HISTORY_PERIOD = "1y"      # yfinance history window (needs ~1y for the 200-day MA)
TECH_RSI_PERIOD = 14
TECH_MA_WINDOWS = [20, 50, 200]  # simple moving averages to report

# --- Synthesis stage (stage 4) ---

# How hard the final ranking rewards analyst *agreement* (breadth of consensus).
# The per-ticker score is  directional_score S × agreement A ** SYNTHESIS_AGREEMENT_EXPONENT.
#   1.0 = consensus-seeking (default): a name the whole panel mildly likes can
#         outrank one that's more strongly liked on average but hotly contested.
#   0.0 = conviction-seeking: agreement is ignored, ranking by net directional
#         strength alone — treats analyst disagreement as edge, not risk.
#   between = dial from one philosophy toward the other.
SYNTHESIS_AGREEMENT_EXPONENT = 1.0

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

