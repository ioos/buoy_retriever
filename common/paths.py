"""Common paths across services"""

from pathlib import Path

from .config.env import LOCAL_IO

# Base path of the filesystem, if `LOCAL_IO` environment variable
# is set, adapt to running directly rather than in Docker/Kubernetes
if LOCAL_IO:
    SHARED_STORAGE = Path(__file__).parent.parent / "docker-data/shared-fs"
else:
    SHARED_STORAGE = Path("/mnt/efs/")

# Path for dataset storage
DATASET_PATH = SHARED_STORAGE / "datasets/"

# Temporary data storage for dataset processing
SCRATCH_PATH = SHARED_STORAGE / "scratch/"

# Path for various services, like ERDDAP, THREDDS, ...
SERVICE_PATH = SHARED_STORAGE / "services/"


def pathsafe_url(url: str) -> str:
    """Renders a URL safe to be a file path component

    'data.neracoos.org/erddap/' becomes 'data_neracoos_org_erddap'
    """
    return url.rstrip("/").replace(".", "_").replace("/", "_")
