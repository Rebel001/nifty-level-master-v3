import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from kiteconnect import KiteConnect
from streamlit_autorefresh import st_autorefresh

IST = ZoneInfo("Asia/Kolkata")
NIFTY_TOKEN = 256265  # NSE:NIFTY 50 index
st.set_page_config(page_title="NIFTY LEVEL MASTER V3", layout="wide")
st.title("NIFTY LEVEL MASTER V3")
st.caption("15-minute direct-breakout indicator • EMA 20/50 filter • India market hours")

# --- credentials / login ---
def get_secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

api_key = get_secret("KITE_API_KEY")
api_secret = get_secret("KITE_API_SECRET")

with st.sidebar:
    st.header("Kite Connect")
    if not api_key or not api_secret:
        st.warning("Add KITE_API_KEY and KITE_API_SECRET to Streamlit secrets first.")
        st.code('[secrets]\nKITE_API_KEY = "your_api_key"\nKITE_API_SECRET = "your_api_secret"', language="toml")
    else:
        st.link_button("Login to Zerodha", KiteConnect(api_key=api_key).login_url(), use_container_width=True)
        request_token = st.text_input("Paste request_token from the redirected URL", type="password")
        if st.button("Create today's access token", use_container_width=True):
            try:
                k = KiteConnect(api_key=api_key)
                data = k.generate_session(request_token.strip(), api_secret=api_secret)
                st.session_state["kite_access_token"] = data["access_token"]
                st.success("Kite session created for today.")
            except Exception as e:
                st.error(f"Login failed: {e}")
        st.caption("For security, never share your API secret or access token.")

    st.divider()
    st.header("Indicator settings")
    ema_filter = st.toggle("EMA 20/50 trend filter", value=True)
    atr_period = st.number_input("ATR period", min_value=5, max_value=50, value=14)
    pivot_len = st.number_input("Confirmed swing pivot length", min_value=2, max_value=10, value=5)
    rr1 = st.number_input("Target 1 (R)", min_value=0.5, max_value=5.0, value=1.0, step=0.25)
    rr2 = st.number_input("Target 2 (R)", min_value=1.0, max_value=8.0, value=2.0, step=0.25)
    refresh = st.selectbox("Refresh", ["30 seconds", "60 seconds", "2 minutes"], index=1)
    refresh_ms = {"30 seconds": 30000, "60 seconds": 60000, "2 minutes": 120000}[refresh]

st_autorefresh(interval=refresh_ms, key="v3_refresh")

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def atr(df, n=14):
    prev = df.close.shift(1)
    tr = pd.concat([(df.high-df.low), (df.high-prev).abs(), (df.low-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def make_15m(raw):
    x = raw.copy()
    x["date"] = pd.to_datetime(x["date"])
    if x["date"].dt.tz is None:
        x["date"] = x["date"].dt.tz_localize(IST)
    else:
        x["date"] = x["date"].dt.tz_convert(IST)
    x = x.set_index("date").sort_index()
    # Keep regular NSE session candles; resample from 09:15 into 15-minute buckets.
    x = x.between_time("09:15", "15:30")
    out = x.resample("15min", origin="start_day", offset="9h15min", label="left", closed="left").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), volume=("volume","sum")
    ).dropna(subset=["open","high","low","close"])
    out = out.between_time("09:15", "15:15")
    # Ignore the currently forming candle.
    now = datetime.now(IST)
    if len(out) and out.index[-1] + timedelta(minutes=15) > now:
        out = out.iloc[:-1]
    return out

def build_levels(df, pivot_len):
    z = df.copy()
    z["ema20"] = ema(z.close,20)
    z["ema50"] = ema(z.close,50)
    z["atr"] = atr(z, int(atr_period))
    z["day"] = z.index.date
    z["pdh"] = np.nan; z["pdl"] = np.nan; z["pdc"] = np.nan
    z["cpr_pivot"] = np.nan; z["cpr_tc"] = np.nan; z["cpr_bc"] = np.nan
    z["orh"] = np.nan; z["orl"] = np.nan
    z["swing_high"] = np.nan; z["swing_low"] = np.nan
    days = list(pd.unique(z.day))
    prev_levels = {}
    for i, day in enumerate(days):
        idx = z.index[z.day == day]
        day_df = z.loc[idx]
        if i > 0:
            pday = days[i-1]
            p = z[z.day == pday]
            ph, pl, pc = p.high.max(), p.low.min(), p.close.iloc[-1]
            pp = (ph+pl+pc)/3
            bc = (ph+pl)/2
            tc = 2*pp-bc
            z.loc[idx, ["pdh","pdl","pdc","cpr_pivot","cpr_tc","cpr_bc"]] = [ph,pl,pc,pp,max(tc,bc),min(tc,bc)]
        first = day_df.between_time("09:15","09:15")
        if len(first):
            z.loc[idx, "orh"] = first.high.iloc[0]
            z.loc[idx, "orl"] = first.low.iloc[0]
        # Latest confirmed pivot levels only; pivot is known after pivot_len bars to the right.
    highs, lows = z.high.to_numpy(), z.low.to_numpy()
    sh = np.full(len(z), np.nan); sl = np.full(len(z), np.nan)
    n = int(pivot_len)
    for i in range(2*n, len(z)):
        p = i-n
        if highs[p] == np.max(highs[p-n:p+n+1]):
            sh[i] = highs[p]
        if lows[p] == np.min(lows[p-n:p+n+1]):
            sl[i] = lows[p]
    z["swing_high"] = pd.Series(sh,index=z.index).ffill()
    z["swing_low"] = pd.Series(sl,index=z.index).ffill()
    return z

def signals(z, ema_filter, rr1, rr2):
    z = z.copy()
    z["signal"] = ""
    z["entry"] = np.nan; z["stop"] = np.nan; z["t1"] = np.nan; z["t2"] = np.nan
    for i in range(1,len(z)):
        r, p = z.iloc[i], z.iloc[i-1]
        if pd.isna(r.atr) or pd.isna(r.pdh) or pd.isna(r.orh) or pd.isna(r.swing_high):
            continue
        # Resistance/support pool from previous-day, opening-range, CPR and confirmed swing levels.
        resist = [v for v in [r.pdh,r.orh,r.cpr_tc,r.swing_high] if pd.notna(v)]
        support = [v for v in [r.pdl,r.orl,r.cpr_bc,r.swing_low] if pd.notna(v)]
        # Direct breakout: close crosses the strongest nearby reference level.
        up_level = min([v for v in resist if v >= p.close], default=np.nan)
        dn_level = max([v for v in support if v <= p.close], default=np.nan)
        long_ok = (not ema_filter) or (r.ema20 > r.ema50 and r.close > r.ema20)
        short_ok = (not ema_filter) or (r.ema20 < r.ema50 and r.close < r.ema20)
        if pd.notna(up_level) and p.close <= up_level and r.close > up_level and long_ok:
            entry = r.close
            stop = min(r.low, entry - r.atr) - 0.10*r.atr
            risk = entry-stop
            if risk > 0:
                z.iloc[i,z.columns.get_loc("signal")] = "BUY CE"
                for c,v in [("entry",entry),("stop",stop),("t1",entry+rr1*risk),("t2",entry+rr2*risk)]:
                    z.iloc[i,z.columns.get_loc(c)] = v
        elif pd.notna(dn_level) and p.close >= dn_level and r.close < dn_level and short_ok:
            entry = r.close
            stop = max(r.high, entry + r.atr) + 0.10*r.atr
            risk = stop-entry
            if risk > 0:
                z.iloc[i,z.columns.get_loc("signal")] = "BUY PE"
                for c,v in [("entry",entry),("stop",stop),("t1",entry-rr1*risk),("t2",entry-rr2*risk)]:
                    z.iloc[i,z.columns.get_loc(c)] = v
    return z

def chart(z):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=z.index,open=z.open,high=z.high,low=z.low,close=z.close,name="NIFTY 50"))
    for col,name,color in [("ema20","EMA 20","#f5a623"),("ema50","EMA 50","#4da3ff"),
                           ("pdh","PDH","#ef5350"),("pdl","PDL","#26a69a"),
                           ("cpr_tc","CPR TC","#ab47bc"),("cpr_bc","CPR BC","#ab47bc"),
                           ("orh","OR High","#ff7043"),("orl","OR Low","#66bb6a")]:
        if col in z and z[col].notna().any():
            fig.add_trace(go.Scatter(x=z.index,y=z[col],mode="lines",name=name,line=dict(width=1,color=color)))
    buys=z[z.signal=="BUY CE"]; sells=z[z.signal=="BUY PE"]
    fig.add_trace(go.Scatter(x=buys.index,y=buys.close,mode="markers",name="BUY CE",marker=dict(symbol="triangle-up",size=13,color="lime")))
    fig.add_trace(go.Scatter(x=sells.index,y=sells.close,mode="markers",name="BUY PE",marker=dict(symbol="triangle-down",size=13,color="red")))
    fig.update_layout(height=650,xaxis_rangeslider_visible=False,template="plotly_dark",
                      legend_orientation="h",margin=dict(l=10,r=10,t=30,b=10))
    return fig

st_autorefresh(interval=refresh_ms, key="data_refresh")
token = st.session_state.get("kite_access_token")
if not token:
    st.info("Connect your Zerodha Kite Connect account in the sidebar to load live NIFTY data.")
    st.markdown("""
    **What you need:** a Kite Connect developer app (API key and secret). The normal Kite trading login alone does not provide API access.

    You can still test the indicator using a 15-minute or 1-minute CSV below.
    """)
else:
    try:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(token)
        now = datetime.now(IST)
        raw = kite.historical_data(NIFTY_TOKEN, now-timedelta(days=7), now, "minute")
        bars = make_15m(pd.DataFrame(raw))
        if len(bars) < 60:
            st.warning("Not enough candles yet to calculate all indicators. Try again after more market data is available.")
        else:
            z = signals(build_levels(bars, pivot_len), ema_filter, rr1, rr2)
            last = z.iloc[-1]
            a,b,c,d = st.columns(4)
            a.metric("NIFTY 50", f'{last.close:,.2f}')
            a2 = b.metric("EMA trend", "BULLISH" if last.ema20>last.ema50 else "BEARISH")
            c.metric("Last completed candle", z.index[-1].strftime("%d %b %H:%M"))
            latest = z[z.signal!=""].tail(1)
            d.metric("Latest V3 signal", latest.signal.iloc[0] if len(latest) else "NO NEW SIGNAL")
            st.plotly_chart(chart(z.tail(160)), use_container_width=True)
            if len(latest):
                q=latest.iloc[0]
                st.subheader(f"Latest signal: {q.signal}")
                x1,x2,x3,x4=st.columns(4)
                x1.metric("Index entry",f"{q.entry:,.2f}")
                x2.metric("Index stop",f"{q.stop:,.2f}")
                x3.metric("Target 1",f"{q.t1:,.2f}")
                x4.metric("Target 2",f"{q.t2:,.2f}")
                st.caption("These are NIFTY index reference levels, not option premium prices.")
            st.subheader("Recent signals")
            st.dataframe(z[z.signal!=""][["signal","close","entry","stop","t1","t2"]].tail(20),use_container_width=True)
    except Exception as e:
        st.error(f"Kite data request failed: {e}")
        st.caption("If the token expired, log in again. Kite access tokens generally need to be renewed each trading day.")

st.divider()
st.subheader("Test with your own historical CSV")
uploaded = st.file_uploader("Upload CSV with date, open, high, low, close (volume optional)", type=["csv"])
if uploaded:
    try:
        csvdf = pd.read_csv(uploaded)
        csvdf.columns = [c.lower().strip() for c in csvdf.columns]
        if "date" not in csvdf.columns and "timestamp" in csvdf.columns:
            csvdf = csvdf.rename(columns={"timestamp":"date"})
        if "volume" not in csvdf.columns:
            csvdf["volume"] = 0
        b15 = make_15m(csvdf[["date","open","high","low","close","volume"]])
        zz = signals(build_levels(b15,pivot_len),ema_filter,rr1,rr2)
        st.plotly_chart(chart(zz.tail(160)),use_container_width=True)
        st.dataframe(zz[zz.signal!=""][["signal","close","entry","stop","t1","t2"]].tail(30),use_container_width=True)
    except Exception as e:
        st.error(f"CSV could not be processed: {e}")

st.warning("Research tool only. It does not place orders. Validate every signal; index reference levels are not CE/PE option prices. Live Kite data requires a separate Kite Connect API subscription and valid credentials.")
