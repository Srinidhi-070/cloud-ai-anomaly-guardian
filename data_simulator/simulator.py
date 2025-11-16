import random
import time
import json
from datetime import datetime

EVENT_TYPES = ["login_success", "login_failed", "api_access", "password_change"]

def generate_normal_event():
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "user": f"user_{random.randint(1, 20)}",
        "event_type": random.choice(EVENT_TYPES),
        "response_time_ms": random.randint(50, 300),
        "ip": f"192.168.1.{random.randint(1, 255)}",
        "anomaly": False
    }

def generate_anomaly_event():
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "user": f"user_{random.randint(1, 20)}",
        "event_type": random.choice(EVENT_TYPES),
        "response_time_ms": random.randint(800, 2000),  # suspiciously slow
        "ip": f"10.0.0.{random.randint(1, 255)}",
        "anomaly": True
    }

def run_simulator():
    print("\nEvent Simulator Running...")
    print("Press CTRL + C to stop.\n")

    try:
        while True:
            # 90% normal, 10% anomaly
            if random.random() < 0.9:
                event = generate_normal_event()
            else:
                event = generate_anomaly_event()

            print(json.dumps(event))
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n Simulator Stopped")

if __name__ == "__main__":
    run_simulator()
