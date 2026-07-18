"""e2e-only: replay the existing Hohonu VCR cassette for every Python
process in this container, hermetically (no real Hohonu API access).

Named `e2e_sitecustomize.py` on disk (and excluded from Docker build
contexts via .dockerignore) precisely so it can never activate by accident:
Python's `site` module auto-imports a module named exactly `sitecustomize`
from `sys.path` at interpreter startup. docker-compose.e2e.yaml bind-mounts
this file into the hohonu container *as* `/home/ioos/sitecustomize.py` and
sets PYTHONPATH=/home/ioos, so only the e2e stack loads it -- never the dev
stack or a production image. The auto-import happens in every process,
which is what makes this apply not just to the Dagster code-server process
but also to the separate run and step-worker processes Dagster's
daemon/multiprocess executor spawn for each materialization.

Rather than holding one `vcr.use_cassette()` context open for the whole
process (vcrpy patches HTTP libraries by swapping classes in place, and
Dagster's definition-loading/run machinery was observed restoring the
originals mid-process, silently letting the op's call through to the real
API), this wraps `requests.get` itself: each call to a dashboard.hohonu.io
URL enters the cassette just for that call. Reassigning a module attribute
can't be undone by vcrpy's class-level unpatching, so it survives whatever
Dagster does between definition load and step execution.
"""

from pathlib import Path

import requests
import vcr

CASSETTE_PATH = Path(
    "/mnt/test-data/hohonu/cassettes/test_hohonu_pipeline/test_daily_asset.yaml",
)

hohonu_vcr = vcr.VCR(
    cassette_library_dir=str(CASSETTE_PATH.parent),
    filter_headers=[("Authorization", "FAKE")],
    record_mode="none",
)

_real_get = requests.get


def _cassette_get(url, **kwargs):
    if "dashboard.hohonu.io" not in url:
        return _real_get(url, **kwargs)
    with hohonu_vcr.use_cassette(
        CASSETTE_PATH.name,
        # The same recorded interaction replays many times across (and
        # within) processes; without this vcrpy raises after the first
        # playback of each recorded request.
        allow_playback_repeats=True,
    ):
        return _real_get(url, **kwargs)


requests.get = _cassette_get
