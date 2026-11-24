import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="NIFTY LEVEL MASTER V3", layout="wide")
st.title("NIFTY LEVEL MASTER V3")
st.caption("15-minute direct breakout • EMA 20/50 filter • Historical CSV tester")

with st.sidebar:
    st.header("V3 settings")
    ema_filter = st.toggle("EMA 20/50 trend filter", value=True)
    atr_period = st.number_input("ATR period", 5, 50, 14)
    pivot_len = st.number_input("Confirmed swing pivot length", 2, 10, 5)
    rr1 = st.number_input("Target 1 (R)", 0.5, 5.0, 1.0, 0.25)
    rr2 = st.number_input("Target 2 (R)", 1.0, 8.0, 2.0, 0.25)
    st.caption("Signals use completed 15-minute candles only.")

uploaded = st.file_uploader("Upload NIFTY 15-minute CSV", type=["csv"])

def prepare_data(file):
    d = pd.read_csv(file)
    d.columns = [str(c).strip().lower() for c in d.columns]
    tcol = next((c for c in ["timestamp", "date", "datetime", "time"] if c in d.columns), None)
    if tcol is None:
        raise ValueError("CSV needs a timestamp/date/datetime column.")
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in d.columns]
    if missing:
        raise ValueError("Missing OHLC columns: " + ", ".join(missing))
    d["timestamp"] = pd.to_datetime(d[tcol], errors="coerce")
    d = d.dropna(subset=["timestamp"])
    for c in required:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=required).sort_values("timestamp")
    d = d.drop_duplicates("timestamp", keep="last")
    # The supplied dataset is already 15-minute bars; do not resample it.
    if d["timestamp"].dt.tz is None:
        d["timestamp"] = d["timestamp"].dt.tz_localize("Asia/Kolkata")
    else:
        d["timestamp"] = d["timestamp"].dt.tz_convert("Asia/Kolkata")
    d = d.set_index("timestamp")
    if "volume" not in d:
        d["volume"] = 0
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0)
    return d[["open", "high", "low", "close", "volume"]]

def calculate(df, atr_n, pivot_n, use_ema, r1, r2):
    z = df.copy()
    z["ema20"] = z.close.ewm(span=20, adjust=False).mean()
    z["ema50"] = z.close.ewm(span=50, adjust=False).mean()
    prev = z.close.shift(1)
    tr = pd.concat([(z.high-z.low), (z.high-prev).abs(), (z.low-prev).abs()], axis=1).max(axis=1)
    z["atr"] = tr.rolling(int(atr_n)).mean()
    z["session"] = z.index.date
    for c in ["pdh","pdl","cpr_tc","cpr_bc","orh","orl"]:
        z[c] = np.nan

    days = list(pd.unique(z.session))
    for j, day in enumerate(days):
        ix = z.index[z.session == day]
        day_df = z.loc[ix]
        if j > 0:
            prior = z[z.session == days[j-1]]
            ph, pl, pc = prior.high.max(), prior.low.min(), prior.close.iloc[-1]
            pp = (ph+pl+pc)/3
            bc = (ph+pl)/2
            tc = 2*pp-bc
            z.loc[ix, "pdh"] = ph
            z.loc[ix, "pdl"] = pl
            z.loc[ix, "cpr_tc"] = max(tc,bc)
            z.loc[ix, "cpr_bc"] = min(tc,bc)
        first = day_df[day_df.index.strftime("%H:%M") == "09:15"]
        if len(first):
            z.loc[ix, "orh"] = first.high.iloc[0]
            z.loc[ix, "orl"] = first.low.iloc[0]

    # Confirmed pivots become available only after pivot_n bars to the right.
    highs, lows = z.high.to_numpy(), z.low.to_numpy()
    sh = np.full(len(z), np.nan)
    sl = np.full(len(z), np.nan)
    n = int(pivot_n)
    for i in range(2*n, len(z)):
        p = i-n
        if highs[p] == np.max(highs[p-n:p+n+1]):
            sh[i] = highs[p]
        if lows[p] == np.min(lows[p-n:p+n+1]):
            sl[i] = lows[p]
    z["swing_high"] = pd.Series(sh, index=z.index).ffill()
    z["swing_low"] = pd.Series(sl, index=z.index).ffill()

    z["signal"] = ""
    z["entry"] = np.nan
    z["stop"] = np.nan
    z["t1"] = np.nan
    z["t2"] = np.nan
    for i in range(1, len(z)):
        r, p = z.iloc[i], z.iloc[i-1]
        if pd.isna(r.atr):
            continue
        resist = [v for v in [r.pdh, r.orh, r.cpr_tc, r.swing_high] if pd.notna(v)]
        support = [v for v in [r.pdl, r.orl, r.cpr_bc, r.swing_low] if pd.notna(v)]
        up = min((v for v in resist if v >= p.close), default=np.nan)
        dn = max((v for v in support if v <= p.close), default=np.nan)
        long_ok = (not use_ema) or (r.ema20 > r.ema50 and r.close > r.ema20)
        short_ok = (not use_ema) or (r.ema20 < r.ema50 and r.close < r.ema20)
        if pd.notna(up) and p.close <= up < r.close and long_ok:
            ent = r.close
            stop = min(r.low, ent-r.atr) - 0.10*r.atr
            risk = ent-stop
            if risk > 0:
                z.iloc[i, z.columns.get_loc("signal")] = "BUY CE"
                for col, val in [("entry",ent),("stop",stop),("t1",ent+r1*risk),("t2",ent+r2*risk)]:
                    z.iloc[i, z.columns.get_loc(col)] = val
        elif pd.notna(dn) and p.close >= dn > r.close and short_ok:
            ent = r.close
            stop = max(r.high, ent+r.atr) + 0.10*r.atr
            risk = stop-ent
            if risk > 0:
                z.iloc[i, z.columns.get_loc("signal")] = "BUY PE"
                for col, val in [("entry",ent),("stop",stop),("t1",ent-r1*risk),("t2",ent-r2*risk)]:
                    z.iloc[i, z.columns.get_loc(col)] = val
    return z

def draw_chart(z):
    x = z.index.to_pydatetime()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=z.open, high=z.high, low=z.low, close=z.close,
        name="NIFTY 50", increasing_line_color="#26a69a", decreasing_line_color="#ef5350"
    ))
    lines = [
        ("ema20","EMA 20","#f5a623"), ("ema50","EMA 50","#4da3ff"),
        ("pdh","PDH","#ef5350"), ("pdl","PDL","#26a69a"),
        ("cpr_tc","CPR TC","#ab47bc"), ("cpr_bc","CPR BC","#ab47bc"),
        ("orh","OR High","#ff7043"), ("orl","OR Low","#66bb6a")
    ]
    for col, label, color in lines:
        if z[col].notna().any():
            fig.add_trace(go.Scatter(x=x, y=z[col], mode="lines", name=label,
                                     line=dict(width=1, color=color)))
    ce = z[z.signal == "BUY CE"]
    pe = z[z.signal == "BUY PE"]
    if len(ce):
        fig.add_trace(go.Scatter(x=ce.index.to_pydatetime(), y=ce.close, mode="markers",
                                 name="BUY CE", marker=dict(symbol="triangle-up", size=12, color="lime")))
    if len(pe):
        fig.add_trace(go.Scatter(x=pe.index.to_pydatetime(), y=pe.close, mode="markers",
                                 name="BUY PE", marker=dict(symbol="triangle-down", size=12, color="red")))
    fig.update_layout(
        template="plotly_dark", height=620, xaxis_rangeslider_visible=False,
        xaxis=dict(type="date", title="Date / time", tickformat="%d %b\n%H:%M"),
        yaxis=dict(title="NIFTY 50 index level", tickformat=",.0f"),
        legend=dict(orientation="h", y=-0.2), margin=dict(l=10,r=10,t=25,b=80)
    )
    return fig

if uploaded is None:
    st.info("Upload your NIFTY 15-minute CSV to display historical candles and V3 signals.")
    st.markdown("Expected columns: `timestamp, open, high, low, close, volume`.")
else:
    try:
        data = prepare_data(uploaded)
        result = calculate(data, atr_period, pivot_len, ema_filter, rr1, rr2)
        st.success(
            f"Loaded {len(data):,} candles • {data.index.min():%d %b %Y} to "
            f"{data.index.max():%d %b %Y} • {data.index.date.nunique()} trading sessions"
        )
        st.caption("Chart uses the CSV's actual timestamp column. No synthetic row-number x-axis.")
        latest = result.iloc[-1]
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Latest NIFTY close", f"{latest.close:,.2f}")
        m2.metric("EMA trend", "BULLISH" if latest.ema20 > latest.ema50 else "BEARISH")
        m3.metric("Last candle", result.index[-1].strftime("%d %b %Y %H:%M"))
        sigs = result[result.signal != ""]
        m4.metric("Latest signal", sigs.signal.iloc[-1] if len(sigs) else "NONE")
        st.plotly_chart(draw_chart(result.tail(500)), use_container_width=True)
        st.subheader("Latest signal details")
        if len(sigs):
            s = sigs.iloc[-1]
            a,b,c,d,e = st.columns(5)
            a.metric("Signal", s.signal)
            b.metric("Entry (index)", f"{s.entry:,.2f}")
            c.metric("Stop", f"{s.stop:,.2f}")
            d.metric("Target 1", f"{s.t1:,.2f}")
            e.metric("Target 2", f"{s.t2:,.2f}")
        else:
            st.write("No V3 signals found in this dataset with the current filter settings.")
        st.subheader("Recent V3 signals")
        if len(sigs):
            view = sigs[["signal","close","entry","stop","t1","t2"]].tail(30).copy()
            view.index.name = "Signal timestamp (IST)"
            st.dataframe(view, use_container_width=True)
            st.download_button("Download signal history CSV", sigs.reset_index().to_csv(index=False),
                               "nifty_v3_signals.csv", "text/csv")
        else:
            st.info("Try comparing EMA filter ON and OFF. This changes signal frequency.")
    except Exception as e:
        st.error(f"Could not read/process CSV: {e}")
        st.write("Please check that the CSV has timestamp/date plus open, high, low and close columns.")
st.warning("Research/testing only. BUY CE / BUY PE are directional index signals, not option premium prices or trade instructions. Verify signals and costs before any live use.")
