import numpy as np


def standardize_ncojson(ncojson: dict) -> dict:
    """Process various flavors of ncoJson input to a standardized format"""
    return remove_none_values(convert_to_ncojson_level_1(ncojson))


def convert_to_ncojson_level_1(attributes: dict) -> dict:
    """Recursively convert verbose ncoJson levels (>1) to concise level 1.

    Example: value {"type": "short", "data": [1, 2, 3]}
    would be converted to [1, 2, 3]
    """

    if not isinstance(attributes, dict):
        return attributes

    return {
        k: v
        if not isinstance(v, dict)
        else (
            v.get("data")
            if set(v.keys()) == {"data", "type"}
            else convert_to_ncojson_level_1(v)
        )
        for k, v in attributes.items()
    }


def remove_none_values(attributes: dict) -> dict:
    """Recursively remove None attribute values (illegal when writing NetCDF)"""

    if not isinstance(attributes, dict):
        return attributes

    return {
        k: v if not isinstance(v, dict) else remove_none_values(v)
        for k, v in attributes.items()
        if v is not None
    }


def convert_numpy_values(ncojson: dict) -> dict:
    """Recursively convert numpy attribute values to regular python types for serialization"""
    if isinstance(ncojson, dict):
        return {k: convert_numpy_values(v) for k, v in ncojson.items()}
    elif isinstance(ncojson, list):
        return [convert_numpy_values(v) for v in ncojson]
    elif isinstance(ncojson, np.generic):
        return ncojson.item()
    elif isinstance(ncojson, np.ndarray):
        return ncojson.tolist()
    return ncojson
