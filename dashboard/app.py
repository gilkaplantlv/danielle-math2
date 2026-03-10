"""
Stock & Earnings Dashboard — Main Streamlit Application.

Run:  streamlit run dashboard/app.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

from data_fetcher import (
    load_tracked_stocks,
    save_tracked_stocks,
    validate_ticker,
    get_stock_info,
    get_price_history,
    get_quarterly_financials,
    get_earnings_history,
    get_recommendations,
    get_analyst_price_targets,
    get_institutional_holders,
    get_institution_pct,
    get_news,
    get_earnings_calendar,
    get_normalized_prices,
    MAJOR_TICKERS,
)
from utils import (
    fmt_number,
    fmt_large_number,
    fmt_pct,
    headline_sentiment,
    sentiment_dot,
    compute_signals,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Stock & Earnings Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
if "tracked" not in st.session_state:
    st.session_state.tracked = load_tracked_stocks()
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None

# ---------------------------------------------------------------------------
# Sidebar — stock management & navigation
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 Dashboard")
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # Navigation
    page = st.radio(
        "Navigate",
        ["Overview", "Deep Dive", "Compare", "Earnings Calendar"],
        label_visibility="collapsed",
    )

    st.divider()
    st.subheader("Tracked Stocks")

    # Add stock
    col_add, col_btn = st.columns([3, 1])
    with col_add:
        new_ticker = st.text_input("Add ticker", placeholder="e.g. NVDA", label_visibility="collapsed")
    with col_btn:
        add_clicked = st.button("➕", use_container_width=True)

    if add_clicked and new_ticker:
        ticker_upper = new_ticker.strip().upper()
        if ticker_upper in st.session_state.tracked:
            st.warning(f"{ticker_upper} already tracked")
        else:
            with st.spinner(f"Validating {ticker_upper}..."):
                if validate_ticker(ticker_upper):
                    st.session_state.tracked.append(ticker_upper)
                    save_tracked_stocks(st.session_state.tracked)
                    st.success(f"Added {ticker_upper}")
                    st.rerun()
                else:
                    st.error(f"Invalid ticker: {ticker_upper}")

    # List tracked stocks with remove & select
    for t in st.session_state.tracked:
        col_name, col_sel, col_rm = st.columns([3, 1, 1])
        with col_name:
            st.markdown(f"**{t}**")
        with col_sel:
            if st.button("👁", key=f"sel_{t}", help=f"Deep dive {t}"):
                st.session_state.selected_stock = t
                page = "Deep Dive"
                st.rerun()
        with col_rm:
            if st.button("✕", key=f"rm_{t}", help=f"Remove {t}"):
                st.session_state.tracked.remove(t)
                save_tracked_stocks(st.session_state.tracked)
                st.rerun()

# ---------------------------------------------------------------------------
# Fetch data for all tracked stocks
# ---------------------------------------------------------------------------
all_infos = []
for t in st.session_state.tracked:
    all_infos.append(get_stock_info(t))

# ---------------------------------------------------------------------------
# Alerts / signals
# ---------------------------------------------------------------------------
signals = compute_signals(all_infos)
if signals:
    with st.expander(f"🔔 Alerts ({len(signals)})", expanded=True):
        for sig in signals:
            st.markdown(f"- {sig}")


# =========================================================================
# PAGE: Overview
# =========================================================================
if page == "Overview":
    st.header("Market Overview")

    if not st.session_state.tracked:
        st.info("Add stocks using the sidebar to get started.")
    else:
        # Build summary table
        rows = []
        for info in all_infos:
            if info.get("error"):
                rows.append({"Ticker": info["ticker"], "Error": info["error"]})
                continue
            rows.append({
                "Ticker": info["ticker"],
                "Price": info.get("price"),
                "Change %": info.get("change_pct"),
                "vs 20d MA": _ma_delta(info.get("price"), info.get("ma20")),
                "vs 50d MA": _ma_delta(info.get("price"), info.get("ma50")),
                "52w High": info.get("high52"),
                "52w Low": info.get("low52"),
                "% from High": info.get("pct_from_high"),
                "Next Earnings": info.get("next_earnings", "N/A"),
                "Days to Earn.": info.get("earnings_countdown"),
                "Consensus": info.get("recommendation", "N/A"),
                "Target $": info.get("target_price"),
                "Mkt Cap": info.get("market_cap"),
                "Sector": info.get("sector", "N/A"),
            })

        df = pd.DataFrame(rows)

        # KPI cards row
        cols = st.columns(min(len(all_infos), 5))
        for i, info in enumerate(all_infos):
            if info.get("error"):
                continue
            with cols[i % len(cols)]:
                delta_str = f"{info.get('change_pct', 0):.2f}%" if info.get("change_pct") is not None else None
                st.metric(
                    label=f"{info['ticker']}",
                    value=f"${info.get('price', 0):.2f}" if info.get("price") else "N/A",
                    delta=delta_str,
                )

        st.divider()

        # Format display columns
        display_df = df.copy()
        if "Mkt Cap" in display_df.columns:
            display_df["Mkt Cap"] = display_df["Mkt Cap"].apply(fmt_large_number)
        if "Price" in display_df.columns:
            display_df["Price"] = display_df["Price"].apply(lambda x: f"${x:.2f}" if x else "N/A")
        if "Change %" in display_df.columns:
            display_df["Change %"] = display_df["Change %"].apply(lambda x: fmt_pct(x) if x is not None else "N/A")
        if "% from High" in display_df.columns:
            display_df["% from High"] = display_df["% from High"].apply(lambda x: fmt_pct(x) if x is not None else "N/A")
        if "Target $" in display_df.columns:
            display_df["Target $"] = display_df["Target $"].apply(lambda x: f"${x:.2f}" if x else "N/A")

        st.dataframe(display_df, use_container_width=True, hide_index=True)


# =========================================================================
# PAGE: Deep Dive
# =========================================================================
elif page == "Deep Dive":
    sel = st.session_state.selected_stock
    if not sel:
        sel = st.selectbox("Select a stock", st.session_state.tracked)
        st.session_state.selected_stock = sel

    if sel:
        info = get_stock_info(sel)
        st.header(f"{info.get('name', sel)} ({sel})")

        # Quick metrics row
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("Price", f"${info.get('price', 0):.2f}" if info.get("price") else "N/A",
                       f"{info.get('change_pct', 0):.2f}%" if info.get("change_pct") is not None else None)
        with c2:
            st.metric("52w High", f"${info.get('high52', 0):.2f}" if info.get("high52") else "N/A")
        with c3:
            st.metric("52w Low", f"${info.get('low52', 0):.2f}" if info.get("low52") else "N/A")
        with c4:
            st.metric("Mkt Cap", fmt_large_number(info.get("market_cap")))
        with c5:
            st.metric("Next Earnings", info.get("next_earnings", "N/A"),
                       f"{info.get('earnings_countdown')}d" if info.get("earnings_countdown") is not None else None)

        # Tabs
        tab_price, tab_fin, tab_earn, tab_analyst, tab_news, tab_holders = st.tabs(
            ["📈 Price", "💰 Financials", "📊 Earnings", "🎯 Analysts", "📰 News", "🏦 Holders"]
        )

        # ----- Price Tab -----
        with tab_price:
            period_map = {"90D": "3mo", "6M": "6mo", "YTD": "ytd", "1Y": "1y"}
            period_label = st.radio("Period", list(period_map.keys()), horizontal=True, label_visibility="collapsed")
            show_bb = st.checkbox("Show Bollinger Bands")

            hist = get_price_history(sel, period_map[period_label])
            if not hist.empty:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    row_heights=[0.75, 0.25], vertical_spacing=0.03)

                # Candlestick / line
                fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], name="Close",
                                         line=dict(color="#2196F3", width=2)), row=1, col=1)
                if "MA20" in hist.columns:
                    fig.add_trace(go.Scatter(x=hist.index, y=hist["MA20"], name="20d MA",
                                             line=dict(color="#FF9800", width=1, dash="dash")), row=1, col=1)
                if "MA50" in hist.columns:
                    fig.add_trace(go.Scatter(x=hist.index, y=hist["MA50"], name="50d MA",
                                             line=dict(color="#4CAF50", width=1, dash="dash")), row=1, col=1)
                if show_bb and "BB_upper" in hist.columns:
                    fig.add_trace(go.Scatter(x=hist.index, y=hist["BB_upper"], name="BB Upper",
                                             line=dict(color="rgba(150,150,150,0.5)", width=1)), row=1, col=1)
                    fig.add_trace(go.Scatter(x=hist.index, y=hist["BB_lower"], name="BB Lower",
                                             fill="tonexty", fillcolor="rgba(150,150,150,0.1)",
                                             line=dict(color="rgba(150,150,150,0.5)", width=1)), row=1, col=1)

                # Volume
                colors = ["#4CAF50" if c >= o else "#F44336"
                          for o, c in zip(hist["Open"], hist["Close"])]
                fig.add_trace(go.Bar(x=hist.index, y=hist["Volume"], name="Volume",
                                     marker_color=colors, opacity=0.5), row=2, col=1)

                fig.update_layout(height=550, xaxis_rangeslider_visible=False,
                                  legend=dict(orientation="h", y=1.02), margin=dict(t=30, b=30))
                fig.update_yaxes(title_text="Price ($)", row=1, col=1)
                fig.update_yaxes(title_text="Volume", row=2, col=1)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("No price data available.")

        # ----- Financials Tab -----
        with tab_fin:
            fin = get_quarterly_financials(sel)
            if fin.get("error"):
                st.warning(f"Could not load financials: {fin['error']}")
            else:
                col_a, col_b = st.columns(2)

                with col_a:
                    _mini_bar_chart("Revenue", fin.get("revenue", []), dollar=True)
                    _mini_bar_chart("Gross Margin %", fin.get("gross_margin", []), pct=True)
                    _mini_bar_chart("Free Cash Flow", fin.get("fcf", []), dollar=True)

                with col_b:
                    _mini_bar_chart("EPS", fin.get("eps", []))
                    _mini_bar_chart("Operating Margin %", fin.get("operating_margin", []), pct=True)

        # ----- Earnings Tab -----
        with tab_earn:
            eh = get_earnings_history(sel)
            if eh.empty:
                st.info("No earnings history available.")
            else:
                st.subheader("Recent Earnings (Estimate vs Actual)")
                st.dataframe(eh, use_container_width=True, hide_index=True)

        # ----- Analyst Tab -----
        with tab_analyst:
            targets = get_analyst_price_targets(sel)
            if targets:
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Target Low", f"${targets.get('target_low', 0):.2f}" if targets.get("target_low") else "N/A")
                with c2:
                    st.metric("Target Mean", f"${targets.get('target_mean', 0):.2f}" if targets.get("target_mean") else "N/A")
                with c3:
                    st.metric("Target High", f"${targets.get('target_high', 0):.2f}" if targets.get("target_high") else "N/A")
                with c4:
                    curr = targets.get("current")
                    mean = targets.get("target_mean")
                    if curr and mean and curr != 0:
                        upside = ((mean - curr) / curr) * 100
                        st.metric("Upside", f"{upside:+.1f}%")
                    else:
                        st.metric("Upside", "N/A")

            recs = get_recommendations(sel)
            if not recs.empty:
                st.subheader("Recent Analyst Actions")
                st.dataframe(recs.tail(10), use_container_width=True, hide_index=True)
            else:
                st.info("No analyst recommendations available.")

        # ----- News Tab -----
        with tab_news:
            news_items = get_news(sel)
            if news_items:
                for item in news_items:
                    sent = headline_sentiment(item["title"])
                    dot = sentiment_dot(sent)
                    source = f" — *{item['source']}*" if item.get("source") else ""
                    st.markdown(f"{dot} [{item['title']}]({item['link']}){source}")
            else:
                st.info("No news found.")

        # ----- Holders Tab -----
        with tab_holders:
            inst_pct = get_institution_pct(sel)
            if inst_pct is not None:
                st.metric("Institutional Ownership", f"{inst_pct * 100:.1f}%")

            holders = get_institutional_holders(sel)
            if not holders.empty:
                st.subheader("Top Institutional Holders")
                st.dataframe(holders, use_container_width=True, hide_index=True)
            else:
                st.info("No institutional holder data available.")


# =========================================================================
# PAGE: Compare
# =========================================================================
elif page == "Compare":
    st.header("Stock Comparison")

    if len(st.session_state.tracked) < 2:
        st.info("Track at least 2 stocks to compare them.")
    else:
        compare_tickers = st.multiselect(
            "Select stocks to compare (2-3)",
            st.session_state.tracked,
            default=st.session_state.tracked[:min(3, len(st.session_state.tracked))],
            max_selections=3,
        )

        if len(compare_tickers) >= 2:
            period_cmp = st.radio("Period", ["3M", "6M", "1Y"], horizontal=True, label_visibility="collapsed")
            period_map_cmp = {"3M": "3mo", "6M": "6mo", "1Y": "1y"}

            norm = get_normalized_prices(compare_tickers, period_map_cmp[period_cmp])
            if not norm.empty:
                fig = go.Figure()
                colors = ["#2196F3", "#FF9800", "#4CAF50", "#E91E63"]
                for i, ticker in enumerate(compare_tickers):
                    if ticker in norm.columns:
                        fig.add_trace(go.Scatter(
                            x=norm.index, y=norm[ticker],
                            name=ticker,
                            line=dict(color=colors[i % len(colors)], width=2),
                        ))
                fig.update_layout(
                    yaxis_title="Normalized Price (100 = start)",
                    height=450,
                    legend=dict(orientation="h", y=1.02),
                    margin=dict(t=30, b=30),
                )
                fig.add_hline(y=100, line_dash="dot", line_color="gray", opacity=0.5)
                st.plotly_chart(fig, use_container_width=True)

            # Comparison metrics table
            st.subheader("Key Metrics")
            cmp_rows = []
            for t in compare_tickers:
                info = get_stock_info(t)
                if info.get("error"):
                    continue
                cmp_rows.append({
                    "Ticker": t,
                    "Price": f"${info.get('price', 0):.2f}" if info.get("price") else "N/A",
                    "Change %": fmt_pct(info.get("change_pct")),
                    "Mkt Cap": fmt_large_number(info.get("market_cap")),
                    "52w High": f"${info.get('high52', 0):.2f}" if info.get("high52") else "N/A",
                    "% from High": fmt_pct(info.get("pct_from_high")),
                    "Consensus": info.get("recommendation", "N/A"),
                    "Target $": f"${info.get('target_price', 0):.2f}" if info.get("target_price") else "N/A",
                    "Next Earnings": info.get("next_earnings", "N/A"),
                })
            if cmp_rows:
                st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)


# =========================================================================
# PAGE: Earnings Calendar
# =========================================================================
elif page == "Earnings Calendar":
    st.header("Earnings Calendar")

    # Combine tracked stocks with major tickers (deduplicate)
    all_cal_tickers = list(dict.fromkeys(st.session_state.tracked + MAJOR_TICKERS))

    with st.spinner("Loading earnings dates..."):
        cal = get_earnings_calendar(all_cal_tickers)

    if cal:
        tracked_set = set(st.session_state.tracked)

        for entry in cal:
            ticker = entry["ticker"]
            date_str = entry["date"]
            countdown = entry["countdown"]
            is_tracked = ticker in tracked_set

            # Color coding
            if countdown < 0:
                icon = "⬜"
                status = "Past"
            elif countdown <= 7:
                icon = "🔴"
                status = f"In {countdown}d"
            elif countdown <= 14:
                icon = "🟡"
                status = f"In {countdown}d"
            else:
                icon = "🟢"
                status = f"In {countdown}d"

            tracked_badge = " ⭐" if is_tracked else ""
            st.markdown(f"{icon} **{ticker}**{tracked_badge} — {date_str} ({status})")
    else:
        st.info("No earnings dates found.")


# =========================================================================
# Helper functions (used within app.py)
# =========================================================================

def _ma_delta(price, ma):
    """Return % delta between price and a moving average."""
    if price is None or ma is None or ma == 0:
        return None
    return ((price - ma) / ma) * 100


def _mini_bar_chart(title: str, data: list[dict], dollar: bool = False, pct: bool = False):
    """Render a small plotly bar chart for financial data."""
    if not data:
        st.caption(f"{title}: No data")
        return
    quarters = [d["quarter"] for d in data]
    values = [d["value"] for d in data]
    if all(v is None for v in values):
        st.caption(f"{title}: No data")
        return

    clean_vals = [v if v is not None else 0 for v in values]
    colors = ["#4CAF50" if v >= 0 else "#F44336" for v in clean_vals]

    fig = go.Figure(go.Bar(x=quarters, y=clean_vals, marker_color=colors))
    if dollar:
        fig.update_yaxes(tickformat="$,.0f")
    elif pct:
        fig.update_yaxes(tickformat=".1f", ticksuffix="%")
    fig.update_layout(title=title, height=220, margin=dict(t=30, b=20, l=40, r=10),
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
