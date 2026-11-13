import dagster as dg


def get_asset_by_name(defs, name: str) -> dg.AssetsDefinition:
    """Extract a specific asset from Dagster Definitions by name.

    Uses the function name, not the full asset key/prefix.
    """
    for asset in defs.assets:
        if asset.key.path[-1] == name:
            return asset
    raise KeyError(f"Asset with name {name} not found")
