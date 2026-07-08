"""Code location entry point for the Hohonu dg project.

Loads all components discovered under ``hohonu_defs/defs`` (currently the
state-backed ``HohonuStateComponent``). This replaces the previous
``pipeline.py`` ``@dg.definitions`` function that fetched dataset configs from
the backend API on every code-server load.
"""

from pathlib import Path

import dagster as dg
from dagster.components import load_from_defs_folder


@dg.definitions
def defs() -> dg.Definitions:
    """Load definitions from the project's defs folder."""
    return load_from_defs_folder(project_root=Path(__file__).parent.parent)
