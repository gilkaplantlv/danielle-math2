"""
Data fetcher module - handles all API calls, scraping, and caching.
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import feedparser
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
TRACKED_STOCKS_FILE = BASE_DIR / "tracked_stocks.json"
CACHE_DB = BASE_DIR / "cache.db"

# ---------------------------------------------------------------------------
# Tracked stocks persistence
# ---------------------------------------------------------------------------

def load_tracked_stocks() -> list[str]:
    if TRACKED_STOCKS_FILE.exists():
        return json.loads(TRACKED_STOCKS_FILE.read_text())
    return ["LITE", "COHR"]


def save_tracked_stocks(tickers: list[str]):
    TRACKED_STOCKS_FILE.write_text(json.dumps(tickers))


def validate_ticker(ticker: str) -> bool:
    """Check if a ticker is valid via yfinance."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Price & quote data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_stock_info(ticker: str) -> dict:
    """Return a dict of key quote fields for a single ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # Current price
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        change_pct = None
        if price and prev_close and prev_close != 0:
            change_pct = ((price - prev_close) / prev_close) * 100

        # Moving averages
        ma20 = info.get("fiftyDayAverage")  # yfinance doesn't always have 20d
        ma50 = info.get("fiftyDayAverage")
        ma200 = info.get("twoHundredDayAverage")

        # Compute 20-day MA from history if available
        try:
            hist = t.history(period="1mo")
            if len(hist) >= 20:
                ma20 = float(hist["Close"].tail(20).mean())
        except Exception:
            pass

        # 52-week
        high52 = info.get("fiftyTwoWeekHigh")
        low52 = info.get("fiftyTwoWeekLow")
        pct_from_high = None
        if price and high52 and high52 != 0:
            pct_from_high = ((price - high52) / high52) * 100

        # Earnings date
        next_earnings = None
        try:
            cal = t.calendar
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        next_earnings = ed[0] if isinstance(ed, list) else ed
                elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"].iloc[0]
                    next_earnings = val
        except Exception:
            pass

        earnings_countdown = None
        if next_earnings is not None:
            try:
                if hasattr(next_earnings, "date"):
                    ed = next_earnings.date() if callable(next_earnings.date) else next_earnings
                else:
                    ed = pd.Timestamp(next_earnings).date()
                earnings_countdown = (ed - datetime.now().date()).days
                next_earnings = str(ed)
            except Exception:
                next_earnings = str(next_earnings)

        # Analyst
        target_price = info.get("targetMeanPrice")
        recommendation = info.get("recommendationKey", "N/A")

        return {
            "ticker": ticker,
            "price": price,
            "change_pct": change_pct,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "high52": high52,
            "low52": low52,
            "pct_from_high": pct_from_high,
            "next_earnings": next_earnings,
            "earnings_countdown": earnings_countdown,
            "target_price": target_price,
            "recommendation": recommendation,
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector", "N/A"),
            "name": info.get("shortName", ticker),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ---------------------------------------------------------------------------
# Historical price data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_price_history(ticker: str, period: str = "3mo") -> pd.DataFrame:
    """Return OHLCV dataframe."""
    try:
        t = yf.Ticker(ticker)
        df = t.history(period=period)
        if df.empty:
            return pd.DataFrame()
        # Compute moving averages
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA50"] = df["Close"].rolling(50).mean()
        # Bollinger bands
        df["BB_mid"] = df["MA20"]
        std20 = df["Close"].rolling(20).std()
        df["BB_upper"] = df["MA20"] + 2 * std20
        df["BB_lower"] = df["MA20"] - 2 * std20
        return df
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Financials
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_quarterly_financials(ticker: str) -> dict:
    """Return quarterly revenue, EPS, margins, FCF."""
    try:
        t = yf.Ticker(ticker)
        result = {
            "revenue": [],
            "eps": [],
            "gross_margin": [],
            "operating_margin": [],
            "fcf": [],
        }

        # Quarterly income statement
        qf = t.quarterly_income_stmt
        if qf is not None and not qf.empty:
            # Columns are dates (most recent first)
            cols = qf.columns[:4]  # last 4 quarters
            for col in reversed(list(cols)):
                label = col.strftime("%Y-Q%q") if hasattr(col, "strftime") else str(col)
                try:
                    label = pd.Timestamp(col).strftime("%b %Y")
                except Exception:
                    label = str(col)[:10]

                rev = _safe_val(qf, "Total Revenue", col)
                gp = _safe_val(qf, "Gross Profit", col)
                oi = _safe_val(qf, "Operating Income", col)
                eps_val = _safe_val(qf, "Diluted EPS", col) or _safe_val(qf, "Basic EPS", col)

                gm = (gp / rev * 100) if (gp and rev and rev != 0) else None
                om = (oi / rev * 100) if (oi and rev and rev != 0) else None

                result["revenue"].append({"quarter": label, "value": rev})
                result["eps"].append({"quarter": label, "value": eps_val})
                result["gross_margin"].append({"quarter": label, "value": gm})
                result["operating_margin"].append({"quarter": label, "value": om})

        # Free cash flow from cash flow statement
        qcf = t.quarterly_cashflow
        if qcf is not None and not qcf.empty:
            cols = qcf.columns[:4]
            for col in reversed(list(cols)):
                try:
                    label = pd.Timestamp(col).strftime("%b %Y")
                except Exception:
                    label = str(col)[:10]
                ocf = _safe_val(qcf, "Operating Cash Flow", col) or _safe_val(qcf, "Total Cash From Operating Activities", col)
                capex = _safe_val(qcf, "Capital Expenditure", col) or _safe_val(qcf, "Capital Expenditures", col)
                fcf = None
                if ocf is not None:
                    capex = capex or 0
                    fcf = ocf + capex  # capex is typically negative
                result["fcf"].append({"quarter": label, "value": fcf})

        return result
    except Exception as e:
        return {"error": str(e)}


def _safe_val(df: pd.DataFrame, row_name: str, col):
    """Safely get a value from a dataframe."""
    try:
        if row_name in df.index:
            v = df.loc[row_name, col]
            if pd.notna(v):
                return float(v)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Earnings history (estimate vs actual)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_earnings_history(ticker: str) -> pd.DataFrame:
    """Return earnings history with estimate vs actual."""
    try:
        t = yf.Ticker(ticker)
        eh = t.earnings_history
        if eh is not None and not eh.empty:
            return eh.tail(4).reset_index(drop=True)
    except Exception:
        pass

    # Fallback: try .earnings_dates
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            # Filter to past dates only
            past = ed[ed.index <= pd.Timestamp.now(tz="America/New_York")]
            return past.head(4).reset_index()
    except Exception:
        pass

    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Analyst recommendations
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_recommendations(ticker: str) -> pd.DataFrame:
    """Return recent analyst recommendations."""
    try:
        t = yf.Ticker(ticker)
        rec = t.recommendations
        if rec is not None and not rec.empty:
            return rec.tail(20).reset_index()
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=86400, show_spinner=False)
def get_analyst_price_targets(ticker: str) -> dict:
    """Return analyst price target summary."""
    try:
        info = yf.Ticker(ticker).info or {}
        return {
            "current": info.get("currentPrice") or info.get("regularMarketPrice"),
            "target_low": info.get("targetLowPrice"),
            "target_mean": info.get("targetMeanPrice"),
            "target_median": info.get("targetMedianPrice"),
            "target_high": info.get("targetHighPrice"),
            "num_analysts": info.get("numberOfAnalystOpinions"),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Institutional holders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_institutional_holders(ticker: str) -> pd.DataFrame:
    try:
        t = yf.Ticker(ticker)
        ih = t.institutional_holders
        if ih is not None and not ih.empty:
            return ih.head(10)
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=86400, show_spinner=False)
def get_institution_pct(ticker: str) -> float | None:
    try:
        info = yf.Ticker(ticker).info or {}
        return info.get("heldPercentInstitutions")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# News via Google News RSS
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def get_news(ticker: str, max_items: int = 10) -> list[dict]:
    """Fetch news from Google News RSS."""
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", ""),
            })
        return items
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Earnings calendar for major stocks
# ---------------------------------------------------------------------------

MAJOR_TICKERS = ["NVDA", "MSFT", "GOOG", "META", "AMZN", "AMD", "AVGO", "MU"]


@st.cache_data(ttl=86400, show_spinner=False)
def get_earnings_calendar(tickers: list[str]) -> list[dict]:
    """Get earnings dates for a list of tickers."""
    results = []
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            ed = None
            if cal is not None:
                if isinstance(cal, dict):
                    raw = cal.get("Earnings Date")
                    if raw:
                        ed = raw[0] if isinstance(raw, list) else raw
                elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                    ed = cal.loc["Earnings Date"].iloc[0]
            if ed is not None:
                try:
                    d = pd.Timestamp(ed).date()
                    countdown = (d - datetime.now().date()).days
                    results.append({
                        "ticker": ticker,
                        "date": str(d),
                        "countdown": countdown,
                    })
                except Exception:
                    pass
        except Exception:
            pass
    results.sort(key=lambda x: x.get("date", "9999"))
    return results


# ---------------------------------------------------------------------------
# Comparison data (normalized prices)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def get_normalized_prices(tickers: list[str], period: str = "6mo") -> pd.DataFrame:
    """Return normalized (indexed to 100) closing prices for multiple tickers."""
    frames = {}
    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period=period)
            if not df.empty:
                series = df["Close"]
                frames[ticker] = (series / series.iloc[0]) * 100
        except Exception:
            pass
    if frames:
        return pd.DataFrame(frames)
    return pd.DataFrame()
