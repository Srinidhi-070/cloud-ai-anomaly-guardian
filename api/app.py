# api/app.py
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
import numpy as np
from sklearn.ensemble import IsolationForest
from datetime import datetime, timezone


app = FastAPI(title="Anomaly Guardian - Ingestion API", version="0.1")


# --- Simple Pydantic model for incoming events ---
class Event(BaseModel):
    timestamp: str | None = None
    user: str
    event_type: str
    response_time_ms: int
    ip: str


# --- SimpleEncoder (same logic as detector) ---
class SimpleEncoder:
    def __init__(self):
        self.user_map = {}
        self.event_map = {}
        self.next_user = 1
        self.next_event = 1

    def encode(self, event: dict):
        u = event.get("user", "user_0")
        if u not in self.user_map:
            self.user_map[u] = self.next_user
            self.next_user += 1
        user_id = self.user_map[u]

        e = event.get("event_type", "unknown")
        if e not in self.event_map:
            self.event_map[e] = self.next_event
            self.next_event += 1
        event_id = self.event_map[e]

        ip = event.get("ip", "0.0.0.0")
        try:
            last_octet = int(ip.strip().split(".")[-1])
        except Exception:
            last_octet = 0

        try:
            resp = int(event.get("response_time_ms", 0))
        except Exception:
            resp = 0

        return [user_id, event_id, last_octet, resp]


# --- Build a tiny in-memory model on startup ---
encoder = SimpleEncoder()


def build_training_and_model():
    import random

    rows = []
    for _ in range(1000):
        user = f"user_{random.randint(1,20)}"
        event_type = random.choice(["login_success", "api_access", "password_change"])
        ip = f"192.168.1.{random.randint(1,240)}"
        response_time = random.randint(50, 400)
        rows.append({"user": user, "event_type": event_type, "ip": ip, "response_time_ms": response_time})
    X = np.array([encoder.encode(r) for r in rows], dtype=float)
    m = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    m.fit(X)
    return m


model = build_training_and_model()


def annotate_event(event: dict):
    x = np.array(encoder.encode(event), dtype=float).reshape(1, -1)
    score = model.decision_function(x)[0]
    pred = model.predict(x)[0]
    try:
        raw_score = float(score)
    except Exception:
        raw_score = float(np.asarray(score).item())
    anomaly_score = (raw_score - (-0.5)) / (0.5 - (-0.5))
    anomaly_score = max(0.0, min(1.0, float(anomaly_score)))
    anomaly_flag = bool(pred == -1)
    out = event.copy()
    out["anomaly_score"] = round(anomaly_score, 4)
    out["anomaly_flag"] = anomaly_flag
    # ensure timestamp exists
    if not out.get("timestamp"):
        out["timestamp"] = datetime.now(timezone.utc).isoformat()
    return out


# --- API routes ---
@app.get("/")
def root():
    return {"status": "ok", "desc": "Anomaly Guardian Ingestion API"}


@app.head("/")
def health_head():
    # Respond to HEAD probes with 200 OK (no body)
    return Response(status_code=200)


@app.post("/ingest")
def ingest(event: Event):
    try:
        ev = event.dict()
        annotated = annotate_event(ev)
        return {"success": True, "annotated_event": annotated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# run locally with: uvicorn api.app:app --reload --port 8000
if __name__ == "__main__":
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)
