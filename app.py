import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from datetime import datetime, timezone

st.set_page_config(page_title="Smallcap Momentum Scanner", page_icon="📈", layout="wide")

CSV_FILE = "nift_smallcap_250.csv"
MAX_ALLOCATION = 10_000
STOP_PCT = 0.15

def yahoo_ticker(s):
    s = str(s).strip().upper()
    if not s or s in {"NAN", "NONE"}:
        return ""
    return s if s.endswith((".NS", ".BO")) else s + ".NS"

def validate_universe(df):
    cols = {str(c).strip().lower(): c for c in df.columns}
    col = next((cols[x] for x in ["symbol", "ticker", "scrip", "stock", "yahoo_ticker"] if x in cols), None)
    if col is None:
        raise ValueError("CSV must contain a 'Symbol' column.")
    out = pd.DataFrame({"Symbol": df[col].astype(str).str.strip().str.upper()})
    out = out[~out["Symbol"].isin(["", "NAN", "NONE"])].drop_duplicates()
    out["YahooTicker"] = out["Symbol"].map(yahoo_ticker)
    return out.reset_index(drop=True)

@st.cache_data(ttl=3600)
def load_csv(path):
    return validate_universe(pd.read_csv(path))

@st.cache_data(ttl=900, show_spinner=False)
def get_data(tickers):
    raw = yf.download(
        tickers=list(tickers), period="3y", interval="1d",
        auto_adjust=False, progress=False, threads=True,
        group_by="ticker", actions=False
    )
    if raw is None or raw.empty:
        raise RuntimeError("Yahoo Finance returned no data. Try again later.")
    return raw

def ticker_frame(raw, ticker):
    if isinstance(raw.columns, pd.MultiIndex):
        l0 = set(map(str, raw.columns.get_level_values(0)))
        l1 = set(map(str, raw.columns.get_level_values(1)))
        if ticker in l0:
            x = raw[ticker].copy()
        elif ticker in l1:
            x = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return None
    else:
        x = raw.copy()
    need = ["Open", "High", "Low", "Close", "Volume"]
    if any(c not in x.columns for c in need):
        return None
    x = x[need].copy()
    x.index = pd.to_datetime(x.index).tz_localize(None) if getattr(pd.to_datetime(x.index), "tz", None) is not None else pd.to_datetime(x.index)
    for c in need:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    return x.dropna(subset=["Close"])

def calculate(x):
    x = x.copy()
    x["SMA50"] = x.Close.rolling(50).mean()
    x["SMA150"] = x.Close.rolling(150).mean()
    x["EMA220"] = x.Close.ewm(span=220, adjust=False, min_periods=220).mean()
    x["Prev52WLow"] = x.Low.rolling(252).min().shift(1)
    x["Prev52WHighClose"] = x.Close.rolling(252).max().shift(1)
    dip = (x.Low < x.EMA220).astype(int)
    x["Dip90"] = dip.shift(1).rolling(90).sum().fillna(0)

    x["C1"] = x.SMA150 > x.EMA220
    x["C2"] = x.Close > x.SMA50
    x["C3"] = x.SMA50 > x.SMA150
    x["C4"] = x.Close > 1.25 * x.Prev52WLow
    x["C5"] = x.Dip90 > 0
    x["Breakout"] = x.Close > x.Prev52WHighClose
    x["ConditionsMet"] = x[["C1","C2","C3","C4","C5","Breakout"]].sum(axis=1)
    x["ConfirmedSignal"] = x.ConditionsMet == 6
    x["PctAboveEMA220"] = (x.Close / x.EMA220 - 1) * 100
    x["PctAbove52WLow"] = (x.Close / x.Prev52WLow - 1) * 100
    return x

def scan(universe, raw):
    rows, failed = [], []
    for _, r in universe.iterrows():
        x = ticker_frame(raw, r.YahooTicker)
        if x is None or len(x) < 260:
            failed.append(r.Symbol)
            continue
        x = calculate(x)
        a = x.iloc[-1]
        if pd.isna(a.EMA220) or pd.isna(a.Prev52WLow):
            failed.append(r.Symbol)
            continue
        rows.append({
            "Symbol": r.Symbol, "Date": x.index[-1].date(),
            "Close": a.Close, "SMA50": a.SMA50, "SMA150": a.SMA150, "EMA220": a.EMA220,
            "Prev52WLow": a.Prev52WLow, "Prev52WHighClose": a.Prev52WHighClose,
            "ConditionsMet": int(a.ConditionsMet),
            "C1_150SMA>220EMA": bool(a.C1), "C2_Close>50SMA": bool(a.C2),
            "C3_50SMA>150SMA": bool(a.C3), "C4_Close>1.25x52WLow": bool(a.C4),
            "C5_DippedBelowEMA220_90D": bool(a.C5), "Breakout": bool(a.Breakout),
            "ConfirmedSignal": bool(a.ConfirmedSignal),
            "PctAboveEMA220": a.PctAboveEMA220, "PctAbove52WLow": a.PctAbove52WLow
        })
    return pd.DataFrame(rows), failed

st.title("📈 Nifty Smallcap Momentum Scanner")
st.caption("Daily Yahoo Finance implementation of your 50/150/220 + 52-week breakout strategy.")

uploaded = st.sidebar.file_uploader("Upload universe CSV", type="csv")
if uploaded:
    try:
        universe = validate_universe(pd.read_csv(uploaded))
    except Exception as e:
        st.error(f"CSV error: {e}"); st.stop()
else:
    try:
        universe = load_csv(CSV_FILE)
    except Exception as e:
        st.error(f"Cannot load {CSV_FILE}: {e}"); st.stop()

st.sidebar.metric("Universe", len(universe))
if st.sidebar.button("🔄 Refresh Yahoo data"):
    get_data.clear()
    st.rerun()

st.sidebar.markdown("""### Strategy
1. SMA150 > EMA220
2. Close > SMA50
3. SMA50 > SMA150
4. Close > 1.25 × prior 252-day low
5. Low < EMA220 at least once in prior 90 sessions
6. Close > prior 252-day highest close

Signal = all 6 conditions.
Entry = next trading day's open.
Exit = close below EMA220 or -15% from entry.
Max allocation = ₹10,000/stock.
""")

with st.spinner(f"Downloading {len(universe)} stocks..."):
    try:
        raw = get_data(tuple(universe.YahooTicker))
        scanner, failed = scan(universe, raw)
    except Exception as e:
        st.error(f"Yahoo download failed: {e}")
        st.info("Yahoo can temporarily rate-limit cloud requests. Wait and refresh.")
        st.stop()

if scanner.empty:
    st.warning("No valid stocks were returned.")
    st.stop()

scanner["PlannedEntry"] = scanner.Close
scanner["15pctStop"] = scanner.PlannedEntry * (1 - STOP_PCT)
scanner["Shares"] = np.floor(MAX_ALLOCATION / scanner.PlannedEntry).astype(int)
scanner["CapitalRequired"] = scanner.Shares * scanner.PlannedEntry
scanner["RiskTo15pctStop"] = scanner.Shares * (scanner.PlannedEntry - scanner["15pctStop"])

confirmed = scanner[scanner.ConfirmedSignal].copy()
near = scanner[scanner.ConditionsMet >= 5].copy()
watch = scanner[scanner.ConditionsMet >= 4].copy()

c = st.columns(5)
c[0].metric("Scanned", len(scanner))
c[1].metric("6/6 Signals", len(confirmed))
c[2].metric("≥5/6", len(near))
c[3].metric("≥4/6", len(watch))
c[4].metric("Data date", str(scanner.Date.max()))

st.info("Yahoo daily data is not guaranteed real-time. A breakout is treated as confirmed only by the latest available daily close.")

def show(df):
    cols = ["Symbol","Date","Close","SMA50","SMA150","EMA220","Prev52WLow","Prev52WHighClose",
            "ConditionsMet","Breakout","PctAboveEMA220","Shares","CapitalRequired","15pctStop","RiskTo15pctStop"]
    st.dataframe(df[cols].sort_values(["ConditionsMet","PctAboveEMA220"], ascending=False).round(2),
                 use_container_width=True, hide_index=True)

t1,t2,t3,t4 = st.tabs(["🟢 Confirmed Signals","🟡 5/6+","🔵 Watchlist","📋 Full Scanner"])
with t1:
    st.subheader("Confirmed 6/6")
    show(confirmed)
with t2:
    st.subheader("Near-signal stocks")
    show(near)
with t3:
    st.subheader("4/6 or better")
    show(watch)
with t4:
    st.subheader("All scanned stocks")
    show(scanner)

st.subheader("Condition Matrix")
matrix_cols = ["Symbol","ConditionsMet","C1_150SMA>220EMA","C2_Close>50SMA","C3_50SMA>150SMA",
               "C4_Close>1.25x52WLow","C5_DippedBelowEMA220_90D","Breakout","ConfirmedSignal"]
st.dataframe(scanner[matrix_cols].sort_values(["ConditionsMet","Symbol"], ascending=[False,True]),
             use_container_width=True, hide_index=True)

st.download_button("⬇️ Download scanner CSV", scanner.to_csv(index=False),
                   file_name=f"scanner_{scanner.Date.max()}.csv", mime="text/csv")

if failed:
    st.caption(f"{len(failed)} symbols could not be calculated (missing/insufficient Yahoo data).")

st.caption(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | 3-year warm-up history")
