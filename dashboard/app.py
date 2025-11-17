# dashboard/app.py
import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
from requests.adapters import HTTPAdapter, Retry
import altair as alt

# -------------------------
# CONFIG
# -------------------------
API_URL = "https://cloud-ai-anomaly-guardian.onrender.com/ingest"  # change if needed
DEFAULT_TIMEOUT = 30  # Increased timeout for cold starts
MAX_EVENTS_DISPLAY = 1000  # Limit events to prevent memory issues

st.set_page_config(
    page_title="Anomaly Guardian — Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------
# SESSION STATE init
# -------------------------
if "events" not in st.session_state:
    st.session_state.events = []  # newest first

if "last_error" not in st.session_state:
    st.session_state.last_error = None

if "api_status" not in st.session_state:
    st.session_state.api_status = "Unknown"

if "processing" not in st.session_state:
    st.session_state.processing = False

# -------------------------
# HTTP session with retries
# -------------------------
session = requests.Session()
retries = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)


# -------------------------
# HELPERS
# -------------------------
def pretty_ts(ts_str):
    try:
        return pd.to_datetime(ts_str).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts_str or "")


def push_event(payload):
    """Post payload to API and return annotated_event dict or raise."""
    r = session.post(API_URL, json=payload, timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    return r.json().get("annotated_event", {})


def df_from_events(events):
    """Return a safe dataframe with required columns and sanitized values."""
    if not events:
        return pd.DataFrame(columns=[
            "timestamp", "ts_pretty", "user", "event_type", "response_time_ms",
            "ip", "anomaly_score", "anomaly_flag"
        ])

    # defensive copy and normalization
    safe_events = []
    for e in events:
        if not isinstance(e, dict):
            continue
        # ensure keys exist and are not None
        s = {
            "timestamp": e.get("timestamp") or "",
            "user": e.get("user") or "",
            "event_type": e.get("event_type") or "",
            "response_time_ms": e.get("response_time_ms") if e.get("response_time_ms") is not None else 0,
            "ip": e.get("ip") or "",
            "anomaly_score": e.get("anomaly_score") if e.get("anomaly_score") is not None else 0.0,
            "anomaly_flag": bool(e.get("anomaly_flag")) if e.get("anomaly_flag") is not None else False,
        }
        safe_events.append(s)

    df = pd.DataFrame(safe_events)

    # parse timestamps safely
    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    except Exception:
        df["timestamp"] = pd.NaT

    df["ts_pretty"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")

    # ensure column types
    df["response_time_ms"] = pd.to_numeric(df["response_time_ms"], errors="coerce").fillna(0).astype(int)
    df["anomaly_score"] = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0).astype(float)
    df["anomaly_flag"] = df["anomaly_flag"].astype(bool)

    # remove rows with completely empty user & event_type (they're useless)
    df = df[~((df["user"] == "") & (df["event_type"] == ""))].reset_index(drop=True)

    return df


# -------------------------
# SIDEBAR / CONTROLS
# -------------------------
with st.sidebar:
    st.title("Controls")
    st.markdown("Generate synthetic events and send them to the cloud API.")

    refresh_interval = st.number_input("Auto refresh (s, 0 = off)", value=0, min_value=0, step=1)
    events_per_click = st.number_input("Events per click", value=1, min_value=1, max_value=50, step=1)
    chosen_event_type = st.selectbox("Event type", ["api_access", "login_success", "login_failed", "password_change"])
    resp_time = st.slider("Response time (ms)", 50, 2000, value=300)

    st.markdown("---")
    st.markdown("**API / Deployment**")
    st.code(API_URL)
    st.markdown("API status:")
    if st.session_state.api_status == "Online":
        st.success("Online")
    elif st.session_state.api_status == "Error":
        st.error("Error")
    else:
        st.info("Unknown")

    st.markdown("---")
    generate_button = st.button("Generate & send", disabled=st.session_state.processing)
    
    if generate_button and not st.session_state.processing:
        st.session_state.processing = True
        st.session_state.last_error = None
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        try:
            for i in range(int(events_per_click)):
                status_text.text(f"Sending event {i+1}/{events_per_click}...")
                progress_bar.progress((i + 1) / events_per_click)
                
                payload = {
                    "user": f"user_{int(time.time()) % 100}",
                    "event_type": chosen_event_type,
                    "response_time_ms": int(resp_time),
                    "ip": f"10.0.0.{int(time.time() * 1000) % 255}",
                }
                
                annotated = push_event(payload)
                # normalized timestamp
                if "timestamp" not in annotated or not annotated["timestamp"]:
                    annotated["timestamp"] = datetime.utcnow().isoformat()
                st.session_state.events.insert(0, annotated)
                
                # Limit events to prevent memory issues
                if len(st.session_state.events) > MAX_EVENTS_DISPLAY:
                    st.session_state.events = st.session_state.events[:MAX_EVENTS_DISPLAY]
                
                st.session_state.api_status = "Online"
                
        except Exception as e:
            st.session_state.last_error = str(e)
            st.session_state.api_status = "Error"
            st.error(f"Send failed: {e}")
        finally:
            st.session_state.processing = False
            progress_bar.empty()
            status_text.empty()
            st.rerun()

    if st.button("Clear events"):
        st.session_state.events = []
        st.session_state.last_error = None

    st.markdown("---")
    st.markdown("Download")
    if st.button("Download CSV of local events"):
        dfdl = df_from_events(st.session_state.events)
        if not dfdl.empty:
            csv = dfdl.to_csv(index=False)
            st.download_button("Download CSV", csv, file_name="anomaly_events.csv", mime="text/csv")
        else:
            st.info("No events to download")

    st.markdown("---")
    st.caption("Tip: increase timeout in code if you see cold-start timeouts on free infra.")


# -------------------------
# MAIN PAGE
# -------------------------
st.markdown("## 🛡️ Anomaly Guardian — Live Dashboard")
cols = st.columns([3, 1])
left, right = cols[0], cols[1]

with left:
    st.markdown("### Recent Events")
    df = df_from_events(st.session_state.events)

    if df.empty:
        st.info("No events yet. Click 'Generate & send' in the sidebar or POST to the API.")
    else:
        # filter UI
        with st.expander("Filters & view options", expanded=False):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                user_filter = st.text_input("Filter user contains", value="")
            with col_b:
                # defensive: if event_type column is empty use empty list
                event_types = sorted(df["event_type"].dropna().unique().tolist()) if "event_type" in df.columns else []
                event_filter = st.selectbox("Event type filter", options=["ALL"] + event_types)
            with col_c:
                show_count = st.number_input("Show rows", min_value=5, max_value=200, value=50)

        view_df = df.copy()
        if user_filter:
            view_df = view_df[view_df["user"].str.contains(user_filter, na=False)]
        if event_filter != "ALL":
            view_df = view_df[view_df["event_type"] == event_filter]
        view_df = view_df.head(int(show_count))

        display_df = view_df[["ts_pretty", "user", "event_type", "response_time_ms", "ip", "anomaly_score", "anomaly_flag"]].rename(
            columns={
                "ts_pretty": "timestamp",
            }
        )

        st.dataframe(display_df, use_container_width=True)

        # charts
        st.markdown("### Charts")

        # 1) anomaly summary bar
        if "anomaly_flag" in df.columns:
            try:
                summary = pd.DataFrame({
                    "type": ["Normal", "Anomaly"],
                    "count": [int((df["anomaly_flag"] == False).sum()), int((df["anomaly_flag"] == True).sum())]
                })
                bar = alt.Chart(summary).mark_bar().encode(
                    x=alt.X("type:N", title="Event Type"),
                    y=alt.Y("count:Q", title="Count"),
                    color=alt.Color("type:N", legend=None)
                ).properties(height=180)
                st.altair_chart(bar, use_container_width=True)
            except Exception as e:
                st.error(f"Chart error (summary): {e}")

        # 2) response_time scatter (defensive)
        if "response_time_ms" in df.columns:
            try:
                df_rt = df.copy()
                # ensure timestamp exists and is not null
                if "timestamp" in df_rt.columns:
                    df_rt = df_rt.dropna(subset=["timestamp"])
                else:
                    df_rt["timestamp"] = pd.NaT

                if df_rt.empty:
                    st.info("No valid timestamped rows for response-time chart.")
                else:
                    df_rt["anomaly_label"] = df_rt["anomaly_flag"].map({True: "anomaly", False: "normal"})
                    # ensure tooltip fields are strings (Altair can choke on None)
                    df_rt["user"] = df_rt["user"].fillna("").astype(str)
                    df_rt["event_type"] = df_rt["event_type"].fillna("").astype(str)
                    df_rt["anomaly_score"] = pd.to_numeric(df_rt["anomaly_score"], errors="coerce").fillna(0.0)
                    rt_chart = alt.Chart(df_rt).mark_circle(size=60, opacity=0.7).encode(
                        x=alt.X("timestamp:T", title="Timestamp"),
                        y=alt.Y("response_time_ms:Q", title="Response time (ms)"),
                        color=alt.Color("anomaly_label:N", scale=alt.Scale(domain=["normal", "anomaly"], range=["#2b8cbe", "#de2d26"])),
                        tooltip=["user", "event_type", "response_time_ms", "anomaly_score", "anomaly_flag"]
                    ).properties(height=220)
                    st.altair_chart(rt_chart, use_container_width=True)
            except Exception as e:
                st.error(f"Chart error (response_time): {e}")

with right:
    st.markdown("### Quick Summary")
    total = len(df)
    anomalies = int(df["anomaly_flag"].sum()) if not df.empty else 0
    normals = total - anomalies
    st.metric("Total events (local session)", total)
    st.metric("Anomalies", anomalies)
    st.metric("Normals", normals)

    st.markdown("### Last error")
    if st.session_state.last_error:
        st.code(st.session_state.last_error)
    else:
        st.success("No errors")

    st.markdown("### Actions")
    if st.button("Run a sample curl test (server-side)"):
        # quick server-side test (uses session) with a fixed payload
        try:
            test_payload = {"user": "curl_test", "event_type": "api_access", "response_time_ms": 1000, "ip": "10.0.0.9"}
            annotated = push_event(test_payload)
            st.success("Server-side POST succeeded. Event annotated and added locally.")
            st.session_state.events.insert(0, annotated)
            st.session_state.api_status = "Online"
        except Exception as e:
            st.session_state.last_error = str(e)
            st.session_state.api_status = "Error"
            st.error(f"Server-side POST failed: {e}")

# auto-refresh (non-blocking)
if refresh_interval > 0:
    st.rerun()
