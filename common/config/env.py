import os

LOCAL_IO = os.environ.get("LOCAL_IO")
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY")

# metadata attribute sources
METADATA_SERVICE_URL = os.environ.get("METADATA_SERVICE_URL")
METADATA_SERVICE_NCOJSON_PATH = os.environ.get("METADATA_SERVICE_NCOJSON_PATH")
METADATA_PATH = os.environ.get("METADATA_PATH", "")

# sentry
SENTRY_DSN = os.environ.get("SENTRY_DSN")
IMAGE_TAG = os.environ.get("IMAGE_TAG")
SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", 1))
SENTRY_PROFILE_SAMPLE_RATE = float(os.environ.get("SENTRY_PROFILE_SAMPLE_RATE", 1))

# erddapper
ERDDAPPER_URL = os.environ.get("ERDDAPPER_URL")
ERDDAPPER_TIMEOUT = int(os.environ.get("ERDDAPPER_TIMEOUT", 60))
