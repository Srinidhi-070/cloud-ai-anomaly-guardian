# models/detector.py
import sys
import json
import numpy as np
from sklearn.ensemble import IsolationForest

# Simple encoder for categorical fields on the fly
class SimpleEncoder:
    def __init__(self):
        self.user_map = {}
        self.event_map = {}
        self.next_user = 1
        self.next_event = 1

    def encode(self, event):
        # user -> numeric id
        u = event.get("user", "user_0")
        if u not in self.user_map:
            self.user_map[u] = self.next_user
            self.next_user += 1
        user_id = self.user_map[u]

        # event_type -> numeric id
        e = event.get("event_type", "unknown")
        if e not in self.event_map:
            self.event_map[e] = self.next_event
            self.next_event += 1
        event_id = self.event_map[e]

        # use last octet of ip as numeric proxy
        ip = event.get("ip", "0.0.0.0")
        try:
            last_octet = int(ip.strip().split(".")[-1])
        except Exception:
            last_octet = 0

        # response_time as int
        try:
            resp = int(event.get("response_time_ms", 0))
        except Exception:
            resp = 0

        return [user_id, event_id, last_octet, resp]


def build_initial_training_data(n=500):
    """Create a synthetic 'normal' dataset for training the IsolationForest."""
    import random
    rows = []
    for _ in range(n):
        user = f"user_{random.randint(1, 20)}"
        event_type = random.choice(["login_success", "api_access", "password_change"])
        ip = f"192.168.1.{random.randint(1, 240)}"
        response_time = random.randint(50, 400)
        rows.append(
            {
                "user": user,
                "event_type": event_type,
                "ip": ip,
                "response_time_ms": response_time,
            }
        )
    return rows


def safe_json_dump(obj):
    """Ensure obj is JSON-serializable by converting non-primitive values to str."""
    safe = {}
    for k, v in obj.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            safe[k] = v
        else:
            # convert numpy types and others to native python types or str
            try:
                # numpy scalar -> python scalar
                if hasattr(v, "item"):
                    safe[k] = v.item()
                else:
                    safe[k] = str(v)
            except Exception:
                safe[k] = str(v)
    return json.dumps(safe)


def main():
    encoder = SimpleEncoder()

    # 1) Build training data and fit IsolationForest
    print(
        "Building synthetic training data and fitting IsolationForest (this may take a sec)...",
        file=sys.stderr,
    )
    train_rows = build_initial_training_data(1000)
    X_train = np.array([encoder.encode(r) for r in train_rows], dtype=float)

    model = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    model.fit(X_train)
    print(
        "Model trained on synthetic normal data. Waiting for incoming events on stdin...",
        file=sys.stderr,
    )

    # 2) Read JSON events from stdin line-by-line
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # ignore lines that aren't JSON
                continue

            # encode and predict
            x = np.array(encoder.encode(event), dtype=float).reshape(1, -1)
            score = model.decision_function(x)[0]  # higher is more normal
            pred = model.predict(x)[0]  # 1 = normal, -1 = anomaly

            # convert to native python floats / bools
            try:
                raw_score = float(score)
            except Exception:
                raw_score = float(np.asarray(score).item())

            # approximate scaling (clamp to 0..1)
            anomaly_score = (raw_score - (-0.5)) / (0.5 - (-0.5))
            anomaly_score = max(0.0, min(1.0, float(anomaly_score)))

            anomaly_flag = bool(pred == -1)

            event_out = event.copy()
            event_out["anomaly_score"] = round(anomaly_score, 4)
            event_out["anomaly_flag"] = anomaly_flag

            # print annotated JSON to stdout (use safe fallback)
            try:
                print(json.dumps(event_out), flush=True)
            except TypeError:
                print(safe_json_dump(event_out), flush=True)

    except KeyboardInterrupt:
        print("\nDetector stopped by user.", file=sys.stderr)
    except BrokenPipeError:
        # upstream process (simulator) closed pipe; exit gracefully
        print("Broken pipe (simulator ended). Exiting.", file=sys.stderr)
    except Exception as e:
        print(f"Unhandled error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
