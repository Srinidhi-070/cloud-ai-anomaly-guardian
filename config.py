# config.py
import os

# API Configuration
API_URL = os.getenv("API_URL", "https://cloud-ai-anomaly-guardian.onrender.com/ingest")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))

# Performance Configuration
MAX_EVENTS_DISPLAY = int(os.getenv("MAX_EVENTS_DISPLAY", "1000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))
MODEL_ESTIMATORS = int(os.getenv("MODEL_ESTIMATORS", "50"))
TRAINING_DATA_SIZE = int(os.getenv("TRAINING_DATA_SIZE", "500"))

# Dashboard Configuration
DEFAULT_REFRESH_INTERVAL = int(os.getenv("DEFAULT_REFRESH_INTERVAL", "0"))
MAX_EVENTS_PER_CLICK = int(os.getenv("MAX_EVENTS_PER_CLICK", "20"))