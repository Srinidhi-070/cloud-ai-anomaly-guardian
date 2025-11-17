# dashboard/optimized_app.py
import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
from requests.adapters import HTTPAdapter, Retry
import altair as alt
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor

# -------------------------
# CONFIG
# -------------------------
API_URL = "https://cloud-ai-anomaly-guardian.onrender.com/ingest"
DEFAULT_TIMEOUT = 30
MAX_EVENTS_DISPLAY = 1000
BATCH_SIZE = 5  # Process events in batches

st.set_page_config(
    page_title="Anomaly Guardian — Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------
# SESSION STATE init
# -------------------------
if "events" not in st.session_state:
    st.session_state.events = []

if "last_error" not in st.session_state:
    st.session_state.last_error = None

if "api_status" not in st.session_state:
    st.session_state.api_status = "Unknown"

if "processing" not in st.session_state:
    st.session_state.processing = False

# -------------------------
# Optimized HTTP session
# -------------------------
@st.cache_resource
def get_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

session = get_session()

# -------------------------
# HELPERS
# -------------------------
@st.cache_data(ttl=60)
def cached_dataframe_operations(events_hash):
    """Cache expensive dataframe operations"""
    return df_from_events(st.session_state.events)

def push_event_batch(payloads):
    """Send multiple events in parallel"""
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(push_event, payload) for payload in payloads]
        for future in futures:
            try:
                result = future.result(timeout=DEFAULT_TIMEOUT)
                results.append(result)
            except Exception as e:
                raise e
    return results

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

    # Use list comprehension for better performance
    safe_events = [
        {
            "timestamp": e.get("timestamp") or "",
            "user": e.get("user") or "",
            "event_type": e.get("event_type") or "",
            "response_time_ms": e.get("response_time_ms") if e.get("response_time_ms") is not None else 0,
            "ip": e.get("ip") or "",
            "anomaly_score": e.get("anomaly_score") if e.get("anomaly_score") is not None else 0.0,
            "anomaly_flag": bool(e.get("anomaly_flag")) if e.get("anomaly_flag") is not None else False,
        }
        for e in events if isinstance(e, dict)
    ]

    if not safe_events:
        return pd.DataFrame(columns=[
            "timestamp", "ts_pretty", "user", "event_type", "response_time_ms",
            "ip", "anomaly_score", "anomaly_flag"
        ])

    df = pd.DataFrame(safe_events)

    # Optimize pandas operations
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["ts_pretty"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
    df["response_time_ms"] = pd.to_numeric(df["response_time_ms"], errors="coerce").fillna(0).astype(int)
    df["anomaly_score"] = pd.to_numeric(df["anomaly_score"], errors="coerce").fillna(0.0).astype(float)
    df["anomaly_flag"] = df["anomaly_flag"].astype(bool)

    # Filter out empty rows
    df = df[~((df["user"] == "") & (df["event_type"] == ""))].reset_index(drop=True)
    return df

# -------------------------
# SIDEBAR / CONTROLS
# -------------------------
with st.sidebar:
    st.title("🛡️ Controls")
    st.markdown("Generate synthetic events and send them to the cloud API.")

    refresh_interval = st.number_input("Auto refresh (s, 0 = off)", value=0, min_value=0, step=1)
    events_per_click = st.number_input("Events per click", value=1, min_value=1, max_value=20, step=1)
    chosen_event_type = st.selectbox("Event type", ["api_access", "login_success", "login_failed", "password_change"])
    resp_time = st.slider("Response time (ms)", 50, 2000, value=300)

    st.markdown("---")
    st.markdown("**API Status**")
    if st.session_state.api_status == "Online":
        st.success("🟢 Online")
    elif st.session_state.api_status == "Error":
        st.error("🔴 Error")
    else:
        st.info("🟡 Unknown")

    st.markdown("---")
    
    # Improved generate button with better UX
    col1, col2 = st.columns(2)
    with col1:
        generate_button = st.button(
            "🚀 Generate & Send", 
            disabled=st.session_state.processing,
            use_container_width=True
        )
    with col2:
        clear_button = st.button(
            "🗑️ Clear Events",
            use_container_width=True
        )

    if generate_button and not st.session_state.processing:
        st.session_state.processing = True
        st.session_state.last_error = None
        
        progress_container = st.container()
        
        try:
            with progress_container:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Generate payloads
                payloads = []
                for i in range(int(events_per_click)):
                    payload = {
                        "user": f"user_{int(time.time() + i) % 100}",
                        "event_type": chosen_event_type,
                        "response_time_ms": int(resp_time + (i * 10)),  # Slight variation
                        "ip": f"10.0.0.{(int(time.time() * 1000) + i) % 255}",
                    }
                    payloads.append(payload)
                
                # Process in batches for better performance
                for batch_start in range(0, len(payloads), BATCH_SIZE):
                    batch_end = min(batch_start + BATCH_SIZE, len(payloads))
                    batch = payloads[batch_start:batch_end]
                    
                    status_text.text(f"Processing batch {batch_start//BATCH_SIZE + 1}...")
                    progress_bar.progress((batch_end) / len(payloads))
                    
                    if len(batch) == 1:
                        # Single event
                        annotated = push_event(batch[0])
                        if "timestamp" not in annotated or not annotated["timestamp"]:
                            annotated["timestamp"] = datetime.utcnow().isoformat()
                        st.session_state.events.insert(0, annotated)
                    else:
                        # Batch processing
                        results = push_event_batch(batch)
                        for annotated in results:
                            if "timestamp" not in annotated or not annotated["timestamp"]:
                                annotated["timestamp"] = datetime.utcnow().isoformat()
                            st.session_state.events.insert(0, annotated)
                
                # Memory management
                if len(st.session_state.events) > MAX_EVENTS_DISPLAY:
                    st.session_state.events = st.session_state.events[:MAX_EVENTS_DISPLAY]
                
                st.session_state.api_status = "Online"
                status_text.text("✅ All events sent successfully!")
                
        except Exception as e:
            st.session_state.last_error = str(e)
            st.session_state.api_status = "Error"
            st.error(f"❌ Send failed: {e}")
        finally:
            st.session_state.processing = False
            time.sleep(1)  # Brief pause to show completion
            st.rerun()

    if clear_button:
        st.session_state.events = []
        st.session_state.last_error = None
        st.rerun()

    st.markdown("---")
    st.markdown("**📊 Quick Stats**")
    total = len(st.session_state.events)
    if total > 0:
        df_temp = df_from_events(st.session_state.events)
        anomalies = int(df_temp["anomaly_flag"].sum()) if not df_temp.empty else 0
        st.metric("Total Events", total)
        st.metric("Anomalies", anomalies, delta=f"{(anomalies/total*100):.1f}%" if total > 0 else "0%")
    else:
        st.info("No events yet")

# -------------------------
# MAIN PAGE
# -------------------------
st.markdown("## 🛡️ Anomaly Guardian — Live Dashboard")

# Create hash for caching
events_hash = hash(str(st.session_state.events))
df = cached_dataframe_operations(events_hash)

if df.empty:
    st.info("🎯 No events yet. Click 'Generate & Send' in the sidebar to start monitoring!")
else:
    # Improved filters
    with st.expander("🔍 Filters & Options", expanded=False):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            user_filter = st.text_input("👤 Filter user contains", value="")
        with col_b:
            event_types = sorted(df["event_type"].dropna().unique().tolist()) if "event_type" in df.columns else []
            event_filter = st.selectbox("📋 Event type filter", options=["ALL"] + event_types)
        with col_c:
            show_count = st.number_input("📄 Show rows", min_value=5, max_value=200, value=50)

    # Apply filters
    view_df = df.copy()
    if user_filter:
        view_df = view_df[view_df["user"].str.contains(user_filter, na=False, case=False)]
    if event_filter != "ALL":
        view_df = view_df[view_df["event_type"] == event_filter]
    view_df = view_df.head(int(show_count))

    # Display table with better formatting
    display_df = view_df[[
        "ts_pretty", "user", "event_type", "response_time_ms", 
        "ip", "anomaly_score", "anomaly_flag"
    ]].rename(columns={
        "ts_pretty": "🕐 Timestamp",
        "user": "👤 User", 
        "event_type": "📋 Event Type",
        "response_time_ms": "⏱️ Response (ms)",
        "ip": "🌐 IP Address",
        "anomaly_score": "🎯 Anomaly Score",
        "anomaly_flag": "⚠️ Is Anomaly"
    })

    st.dataframe(display_df, use_container_width=True, height=400)

    # Enhanced charts
    st.markdown("### 📈 Analytics")
    
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.markdown("**Event Distribution**")
        try:
            summary = pd.DataFrame({
                "type": ["Normal", "Anomaly"],
                "count": [
                    int((df["anomaly_flag"] == False).sum()), 
                    int((df["anomaly_flag"] == True).sum())
                ]
            })
            
            bar_chart = alt.Chart(summary).mark_bar(cornerRadius=5).encode(
                x=alt.X("type:N", title="Event Type"),
                y=alt.Y("count:Q", title="Count"),
                color=alt.Color(
                    "type:N", 
                    scale=alt.Scale(domain=["Normal", "Anomaly"], range=["#2E8B57", "#DC143C"]),
                    legend=None
                )
            ).properties(height=200)
            
            st.altair_chart(bar_chart, use_container_width=True)
        except Exception as e:
            st.error(f"Chart error: {e}")

    with chart_col2:
        st.markdown("**Response Time Trends**")
        try:
            if not df.empty and "timestamp" in df.columns:
                df_rt = df.dropna(subset=["timestamp"]).copy()
                if not df_rt.empty:
                    df_rt["anomaly_label"] = df_rt["anomaly_flag"].map({True: "Anomaly", False: "Normal"})
                    
                    scatter_chart = alt.Chart(df_rt).mark_circle(size=80, opacity=0.8).encode(
                        x=alt.X("timestamp:T", title="Time"),
                        y=alt.Y("response_time_ms:Q", title="Response Time (ms)"),
                        color=alt.Color(
                            "anomaly_label:N", 
                            scale=alt.Scale(domain=["Normal", "Anomaly"], range=["#2E8B57", "#DC143C"])
                        ),
                        tooltip=["user", "event_type", "response_time_ms", "anomaly_score"]
                    ).properties(height=200)
                    
                    st.altair_chart(scatter_chart, use_container_width=True)
                else:
                    st.info("No timestamped data available")
        except Exception as e:
            st.error(f"Chart error: {e}")

# Error display
if st.session_state.last_error:
    st.error(f"🚨 Last Error: {st.session_state.last_error}")

# Auto-refresh (optimized)
if refresh_interval > 0 and not st.session_state.processing:
    time.sleep(refresh_interval)
    st.rerun()