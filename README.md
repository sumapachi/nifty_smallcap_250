# Nifty Smallcap Momentum Scanner

## Files

- `app.py` — Streamlit application
- `nift_smallcap_250.csv` — replace the sample symbols with your full 250-stock universe
- `requirements.txt` — Community Cloud dependencies

## CSV format

Your CSV must contain a `Symbol` column:

```csv
Symbol
RELIANCE
TCS
INFY
HDFCBANK
ICICIBANK
```

The app automatically converts NSE symbols such as `RELIANCE` to `RELIANCE.NS`.

## Strategy

1. SMA150 > EMA220
2. Close > SMA50
3. SMA50 > SMA150
4. Close > 1.25 × prior 252-session low
5. Low dipped below EMA220 at least once in the prior 90 sessions
6. Close > prior 252-session highest close

All six = confirmed signal.

Execution assumptions:
- Signal on daily close
- Entry next trading day's open
- Exit below EMA220 or 15% below entry
- Maximum ₹10,000 allocation per stock

The dashboard uses 3 years of Yahoo Finance daily history so the 220 EMA and 252-day calculations have sufficient warm-up.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open `http://localhost:8501`.

## Streamlit Community Cloud

Push all files to a GitHub repository, then create a Streamlit Cloud app using `app.py` as the main file.

No Yahoo Finance API key is required.

## Important

Yahoo Finance is a research/daily-data source and is not guaranteed to be a real-time exchange feed. For actual intraday trading, use a broker/exchange data API.
