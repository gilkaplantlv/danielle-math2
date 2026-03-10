"""
Utility functions – formatting, signal detection, sentiment analysis.
"""

from datetime import datetime


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def fmt_number(value, prefix: str = "", suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{prefix}{value:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def fmt_large_number(value) -> str:
    """Format large numbers (market cap, revenue) into human-readable form."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.1f}K"
    return f"${v:,.0f}"


def fmt_pct(value, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{value:+.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Sentiment analysis (keyword-based)
# ---------------------------------------------------------------------------

POSITIVE_KEYWORDS = [
    "beat", "beats", "surge", "surges", "record", "upgrade", "upgrades",
    "raises", "raise", "buy", "outperform", "bullish", "growth", "strong",
    "profit", "gains", "soars", "rally", "positive", "exceed", "exceeds",
    "tops", "boost", "jumps",
]

NEGATIVE_KEYWORDS = [
    "miss", "misses", "downgrade", "downgrades", "cut", "cuts", "warns",
    "decline", "declines", "sell", "bearish", "loss", "losses", "drops",
    "falls", "crash", "plunge", "weak", "slump", "disappoints", "below",
    "negative", "underperform", "layoffs",
]


def headline_sentiment(headline: str) -> str:
    """Return 'positive', 'negative', or 'neutral' based on keyword matching."""
    lower = headline.lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in lower)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in lower)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def sentiment_dot(sentiment: str) -> str:
    """Return a colored circle emoji for sentiment."""
    if sentiment == "positive":
        return "🟢"
    if sentiment == "negative":
        return "🔴"
    return "⚪"


# ---------------------------------------------------------------------------
# Watchlist signals
# ---------------------------------------------------------------------------

def compute_signals(stock_infos: list[dict]) -> list[str]:
    """Generate alert strings from stock info dicts."""
    signals = []
    for info in stock_infos:
        if info.get("error"):
            continue
        ticker = info.get("ticker", "?")
        price = info.get("price")
        ma20 = info.get("ma20")
        ma50 = info.get("ma50")
        high52 = info.get("high52")
        low52 = info.get("low52")
        countdown = info.get("earnings_countdown")

        # Earnings within 14 days
        if countdown is not None and 0 <= countdown <= 14:
            signals.append(f"📅 **{ticker}** earnings in **{countdown} day(s)**")

        # Near 52-week high (within 2%)
        if price and high52 and high52 != 0:
            pct = ((price - high52) / high52) * 100
            if pct >= -2 and pct <= 0:
                signals.append(f"📈 **{ticker}** near 52-week high (${high52:.2f})")
            elif pct > 0:
                signals.append(f"🚀 **{ticker}** hit new 52-week high!")

        # Near 52-week low (within 2%)
        if price and low52 and low52 != 0:
            pct = ((price - low52) / low52) * 100
            if pct <= 2:
                signals.append(f"📉 **{ticker}** near 52-week low (${low52:.2f})")

        # MA crossovers
        if price and ma20:
            if 0 < (price - ma20) / ma20 * 100 < 1:
                signals.append(f"↗️ **{ticker}** just crossed above 20-day MA")
            elif -1 < (price - ma20) / ma20 * 100 < 0:
                signals.append(f"↘️ **{ticker}** just crossed below 20-day MA")

    return signals
