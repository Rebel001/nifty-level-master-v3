# NIFTY LEVEL MASTER V3 — Android dashboard

This is a mobile-friendly Streamlit dashboard. Open its URL in Chrome on Android.
It is separate from Kite; use Kite for execution.

## Important limitation
The standard Zerodha Kite app does not accept arbitrary custom indicators. This dashboard runs separately. Live Zerodha data requires a Kite Connect developer app/API access. A normal Kite login does not automatically include API access. No orders are placed.

## Deploy it (recommended: Streamlit Community Cloud)
1. Create a GitHub repository and upload `app.py` and `requirements.txt`.
2. Create a Streamlit Community Cloud app from that repository, with `app.py` as the main file.
3. In the app's Settings → Secrets, add:
   ```toml
   KITE_API_KEY = "your_kite_connect_api_key"
   KITE_API_SECRET = "your_kite_connect_api_secret"
   ```
4. Restart/redeploy the app.
5. On Android, open the deployed app URL in Chrome. You can add it to your home screen using Chrome menu → Add to Home screen.

## Connect Zerodha each trading day
1. In the dashboard sidebar, tap **Login to Zerodha**.
2. Sign in and approve the Kite Connect app.
3. Zerodha redirects to your configured redirect URL. Copy the `request_token` query parameter from that URL.
4. Return to the dashboard, paste the request token, and tap **Create today's access token**.
5. The token is held in the app's current session only. Repeat the login flow when it expires (normally daily).

Configure the redirect URL in your Kite Connect developer console to the deployed Streamlit app URL. If the redirect URL cannot be configured to match the app URL, use the exact redirect URL you registered and copy the request_token from it.

## Get API access
Create a Kite Connect app from Zerodha's developer portal and review current plan/pricing there. Keep the API secret private. Never paste API secrets or access tokens into chats, screenshots, GitHub, or public files.

## What the indicator displays
- 15-minute completed candles (aggregated from 1-minute historical candles)
- EMA 20 / EMA 50 filter (default ON)
- Previous day high / low and CPR
- First 15-minute opening range
- Confirmed swing levels
- Direct breakout signals: BUY CE / BUY PE
- Index reference entry, ATR stop, T1 and T2

## V3 logic notes / limitations
- Signals are evaluated only on completed 15-minute candles; the live forming candle is ignored to reduce repainting.
- This is a practical implementation of the previously discussed V3 rules, not a byte-for-byte port of a TradingView strategy. The breakout reference is the nearest relevant PDH/PDL, ORH/ORL, CPR and confirmed swing level.
- Entry/SL/T1/T2 are NIFTY index reference points, not option premium estimates. Option premium depends on strike, expiry, IV, delta, theta and spread.
- Historical candle fetch uses NSE:NIFTY 50 instrument token 256265 and a recent rolling data window. Check the current Kite Connect docs and instrument master if Zerodha changes instrument metadata or API behaviour.
- This is not a backtester, broker recommendation, or automated trading system. Test in paper mode first.

## CSV testing
CSV must contain `date` (or `timestamp`), `open`, `high`, `low`, `close`; `volume` is optional. The dashboard aggregates one-minute data into 15-minute bars. Timestamps should be India market local time or timezone-aware timestamps.
