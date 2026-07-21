"""Stage 3a of the AI Stock Stack pipeline: analyst briefing layer.

For each candidate ticker coming out of the screener, this assembles a
domain-organized *research briefing* — the raw facts each of the six debate
specialists (Technical, Fundamentals, Estimates, News, Options, Macro) needs to
argue a bull/bear case. All data comes from yfinance (no API key, no MCP), so
this layer stays testable and consistent with the screener's philosophy.

The reasoning itself happens one layer up: live Claude subagents read these
briefings and produce the actual bull/bear arguments. This module only gathers
and structures facts; it deliberately draws no conclusions.

Design notes:
- Every domain fails soft. A thinly-covered ticker missing options or estimates
  yields a briefing with that section marked unavailable, not a crash — the
  debate agent is told what's missing and reasons around it.
- Macro context is pulled once per run and shared across all tickers, since it
  isn't stock-specific.
"""

import datetime
import glob
import json
import os

import pandas as pd
import yfinance as yf

from . import config


def _round(value, digits=2):
    """Round a possibly-None/NaN numeric to `digits`, else return None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _pct(value, digits=2):
    """Format a fraction (0.153) as a percent number (15.3)."""
    r = _round(value, 6)
    return None if r is None else round(r * 100, digits)


# --- Technical ---------------------------------------------------------------

def _rsi(close, period):
    """Wilder's RSI on a close-price series. Returns the latest value or None."""
    if len(close) <= period:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing via exponential moving average with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return _round(rsi.iloc[-1], 1)


def _macd(close):
    """Standard 12/26/9 MACD. Returns latest line, signal, and histogram."""
    if len(close) < 35:
        return {"macd": None, "signal": None, "histogram": None}
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return {
        "macd": _round(macd_line.iloc[-1], 3),
        "signal": _round(signal.iloc[-1], 3),
        "histogram": _round(hist.iloc[-1], 3),
    }


def technical_briefing(ticker):
    """Price-action / momentum facts computed from OHLCV history."""
    hist = ticker.history(period=config.TECH_HISTORY_PERIOD)
    if hist.empty or "Close" not in hist:
        return {"available": False, "reason": "no price history"}

    close = hist["Close"].dropna()
    volume = hist["Volume"].dropna()
    last = close.iloc[-1]

    smas = {}
    for window in config.TECH_MA_WINDOWS:
        if len(close) >= window:
            ma = close.rolling(window).mean().iloc[-1]
            smas[f"sma_{window}"] = _round(ma)
            smas[f"pct_vs_sma_{window}"] = _pct((last - ma) / ma)
        else:
            smas[f"sma_{window}"] = None
            smas[f"pct_vs_sma_{window}"] = None

    def ret_over(days):
        if len(close) > days:
            return _pct((last - close.iloc[-1 - days]) / close.iloc[-1 - days])
        return None

    high = close.max()
    low = close.min()
    recent_avg_vol = volume.tail(5).mean() if len(volume) >= 5 else None
    base_avg_vol = volume.tail(60).mean() if len(volume) >= 20 else None

    return {
        "available": True,
        "last_close": _round(last),
        "rsi_14": _rsi(close, config.TECH_RSI_PERIOD),
        "macd": _macd(close),
        **smas,
        "return_5d_pct": ret_over(5),
        "return_1m_pct": ret_over(21),
        "return_3m_pct": ret_over(63),
        "period_high": _round(high),
        "period_low": _round(low),
        "pct_off_period_high": _pct((last - high) / high),
        "recent_vs_base_volume": _round(recent_avg_vol / base_avg_vol)
        if recent_avg_vol and base_avg_vol else None,
        "history_period": config.TECH_HISTORY_PERIOD,
    }


# --- Fundamentals ------------------------------------------------------------

def fundamentals_briefing(info):
    """Valuation, profitability, growth, and balance-sheet health from .info."""
    if not info:
        return {"available": False, "reason": "no company info"}
    return {
        "available": True,
        "valuation": {
            "trailing_pe": _round(info.get("trailingPE")),
            "forward_pe": _round(info.get("forwardPE")),
            "price_to_book": _round(info.get("priceToBook")),
            "price_to_sales": _round(info.get("priceToSalesTrailing12Months")),
            "ev_to_ebitda": _round(info.get("enterpriseToEbitda")),
        },
        "profitability": {
            "profit_margin_pct": _pct(info.get("profitMargins")),
            "operating_margin_pct": _pct(info.get("operatingMargins")),
            "return_on_equity_pct": _pct(info.get("returnOnEquity")),
            "return_on_assets_pct": _pct(info.get("returnOnAssets")),
        },
        "growth": {
            "revenue_growth_pct": _pct(info.get("revenueGrowth")),
            "earnings_growth_pct": _pct(info.get("earningsGrowth")),
        },
        "health": {
            "debt_to_equity": _round(info.get("debtToEquity")),
            "current_ratio": _round(info.get("currentRatio")),
            "total_cash": info.get("totalCash"),
            "free_cashflow": info.get("freeCashflow"),
        },
        "profile": {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "beta": _round(info.get("beta")),
        },
    }


# --- Estimates ---------------------------------------------------------------

def estimates_briefing(ticker, info):
    """Sell-side targets, ratings, and the next earnings date."""
    if not info:
        return {"available": False, "reason": "no company info"}

    last = info.get("currentPrice") or info.get("regularMarketPrice")
    target = info.get("targetMeanPrice")
    implied_upside = _pct((target - last) / last) if (target and last) else None

    next_earnings = None
    try:
        dates = ticker.earnings_dates
        if dates is not None and not dates.empty:
            future = dates[dates.index > pd.Timestamp.now(tz=dates.index.tz)]
            if not future.empty:
                next_earnings = future.index.min().date().isoformat()
    except Exception:
        pass

    return {
        "available": True,
        "recommendation_key": info.get("recommendationKey"),
        "recommendation_mean": _round(info.get("recommendationMean")),  # 1=strong buy, 5=sell
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "target_mean": _round(target),
        "target_high": _round(info.get("targetHighPrice")),
        "target_low": _round(info.get("targetLowPrice")),
        "implied_upside_pct": implied_upside,
        "forward_pe": _round(info.get("forwardPE")),
        "next_earnings_date": next_earnings,
    }


# --- News --------------------------------------------------------------------

def _normalize_news_item(item):
    """yfinance has shipped two news shapes; normalize both to title/publisher/url/time."""
    content = item.get("content", item)  # newer yfinance nests under "content"
    title = content.get("title")
    publisher = None
    provider = content.get("provider")
    if isinstance(provider, dict):
        publisher = provider.get("displayName")
    publisher = publisher or content.get("publisher")

    url = None
    canonical = content.get("canonicalUrl") or content.get("clickThroughUrl")
    if isinstance(canonical, dict):
        url = canonical.get("url")
    url = url or content.get("link")

    published = content.get("pubDate") or content.get("providerPublishTime")
    if isinstance(published, (int, float)):
        published = datetime.datetime.utcfromtimestamp(published).isoformat() + "Z"

    return {"title": title, "publisher": publisher, "url": url, "published": published}


def news_briefing(ticker, limit=8):
    """Recent headlines. Titles only — the News agent reads sentiment from these."""
    try:
        items = ticker.news or []
    except Exception:
        items = []
    if not items:
        return {"available": False, "reason": "no recent news"}
    normalized = [_normalize_news_item(i) for i in items[:limit]]
    normalized = [n for n in normalized if n["title"]]
    if not normalized:
        return {"available": False, "reason": "no parseable headlines"}
    return {"available": True, "headline_count": len(normalized), "headlines": normalized}


# --- Options -----------------------------------------------------------------

def options_briefing(ticker, spot):
    """Nearest-expiry positioning: put/call OI skew and the implied move."""
    try:
        expiries = ticker.options or []
    except Exception:
        expiries = []
    if not expiries:
        return {"available": False, "reason": "no listed options"}

    # The very nearest weekly expiry is often illiquid (zero call OI → a
    # meaningless ratio). Scan the first few expiries and use the most liquid,
    # so put/call skew and IV reflect real positioning.
    best = None
    for expiry in expiries[:4]:
        try:
            chain = ticker.option_chain(expiry)
        except Exception:
            continue
        total_oi = float(chain.calls["openInterest"].fillna(0).sum()
                         + chain.puts["openInterest"].fillna(0).sum())
        if best is None or total_oi > best[2]:
            best = (expiry, chain, total_oi)
    if best is None:
        return {"available": False, "reason": "chain fetch failed for all expiries"}

    expiry, chain, _ = best
    calls, puts = chain.calls, chain.puts
    call_oi = float(calls["openInterest"].fillna(0).sum())
    put_oi = float(puts["openInterest"].fillna(0).sum())
    put_call_oi = _round(put_oi / call_oi) if call_oi else None

    # ATM implied vol + straddle-implied move, if we know the spot price.
    atm_iv = None
    implied_move_pct = None
    if spot:
        call_atm = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
        put_atm = puts.iloc[(puts["strike"] - spot).abs().argsort()[:1]]
        ivs = [v for v in [call_atm["impliedVolatility"].iloc[0] if not call_atm.empty else None,
                           put_atm["impliedVolatility"].iloc[0] if not put_atm.empty else None]
               if v is not None and not pd.isna(v)]
        if ivs:
            atm_iv = _pct(sum(ivs) / len(ivs))
        straddle = 0.0
        if not call_atm.empty:
            straddle += float(call_atm["lastPrice"].iloc[0] or 0)
        if not put_atm.empty:
            straddle += float(put_atm["lastPrice"].iloc[0] or 0)
        if straddle and spot:
            implied_move_pct = _pct(straddle / spot)

    return {
        "available": True,
        "expiry": expiry,
        "call_open_interest": int(call_oi),
        "put_open_interest": int(put_oi),
        "put_call_oi_ratio": put_call_oi,
        "atm_implied_vol_pct": atm_iv,
        "implied_move_pct": implied_move_pct,
    }


# --- Macro (shared across tickers) -------------------------------------------

def macro_context():
    """Regime snapshot: index levels, vol, rates, dollar, oil — pulled once per run."""
    context = {}
    for label, symbol in config.MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="1mo")
            close = hist["Close"].dropna()
            if close.empty:
                context[label] = {"available": False}
                continue
            last = close.iloc[-1]
            prev = close.iloc[-2] if len(close) > 1 else last
            month_ago = close.iloc[0]
            context[label] = {
                "available": True,
                "last": _round(last),
                "change_1d_pct": _pct((last - prev) / prev),
                "change_1m_pct": _pct((last - month_ago) / month_ago),
            }
        except Exception:
            context[label] = {"available": False}
    return context


# --- Assembly ----------------------------------------------------------------

def build_briefing(symbol, macro=None):
    """Assemble the full six-domain briefing for one ticker."""
    ticker = yf.Ticker(symbol)
    try:
        info = ticker.info or {}
    except Exception:
        info = {}
    spot = info.get("currentPrice") or info.get("regularMarketPrice")

    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName"),
        "spot_price": _round(spot),
        "briefed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "domains": {
            "technical": technical_briefing(ticker),
            "fundamentals": fundamentals_briefing(info),
            "estimates": estimates_briefing(ticker, info),
            "news": news_briefing(ticker),
            "options": options_briefing(ticker, spot),
            "macro": macro if macro is not None else macro_context(),
        },
    }


def _latest_screener_file(screener_dir):
    files = sorted(glob.glob(os.path.join(screener_dir, "*.json")))
    return files[-1] if files else None


def run_briefings(screener_dir=None, output_dir=None, max_candidates=None, symbols=None):
    """Build briefings for the screener candidates (or an explicit symbol list).

    Briefs every candidate the screener passed, up to `max_candidates`
    (defaults to config.DEBATE_MAX_CANDIDATES). Returns (output_path,
    output_dict). Reuses one macro snapshot for all tickers.
    """
    screener_dir = screener_dir or config.SCREENER_OUTPUT_DIR
    output_dir = output_dir or config.DEBATE_OUTPUT_DIR
    max_candidates = max_candidates or config.DEBATE_MAX_CANDIDATES

    source_file = None
    if symbols is None:
        source_file = _latest_screener_file(screener_dir)
        if not source_file:
            raise FileNotFoundError(f"No screener output found in {screener_dir}/")
        with open(source_file) as f:
            screener = json.load(f)
        # Screener already ranks by composite promise score, strongest first, so
        # the cap (if it bites) keeps the most promising setups.
        symbols = [c["symbol"] for c in screener["candidates"][:max_candidates]]

    macro = macro_context()
    briefings = [build_briefing(sym, macro=macro) for sym in symbols]

    today = datetime.date.today().isoformat()
    output = {
        "run_date": today,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_screener_file": source_file,
        "macro_context": macro,
        "briefing_count": len(briefings),
        "briefings": briefings,
    }

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{today}_briefings.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    return output_path, output
