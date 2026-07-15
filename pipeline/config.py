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
