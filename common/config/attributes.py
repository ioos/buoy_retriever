from pathlib import Path
from typing import Annotated, Any

import requests
import xarray as xr
import yaml
from pydantic import BaseModel, Field

from ..config.env import METADATA_PATH, METADATA_SERVICE_URL
from ..ncojson import standardize_ncojson

# Xarray has typed attributes as dict[Any, Any]
# https://github.com/pydata/xarray/blob/64704605a4912946d2835e54baa2905b8b4396a9/xarray/namedarray/core.py#L252
Attributes = dict[Any, Any]


class NcAttributes(BaseModel):
    """Configure variable and global dataset attributes"""

    global_attributes: Annotated[
        Attributes,
        Field(
            description="Global attributes to add to the NetCDF file",
            default_factory=dict,
        ),
    ]

    variables: Annotated[
        dict[str, Attributes],
        Field(
            description="Variable-specific attributes",
            default_factory=dict,
        ),
    ]

    additional_attributes_file: Annotated[
        str,
        Field(
            description="Path to the file that defines additional attributes for source",
        ),
    ] = None

    def add_attributes_from_yaml(self):
        if self.additional_attributes_file is not None:
            with Path.open(
                Path(METADATA_PATH) / self.additional_attributes_file,
                "r",
            ) as file:
                data = yaml.safe_load(file)
            if "global_attributes" in data:
                self.global_attributes = (
                    data["global_attributes"] | self.global_attributes
                )
            if "variable_attributes" in data:
                self.variables = data["variable_attributes"] | self.variables

    def apply_to_dataset(self, ds: xr.Dataset):
        """Apply the configured attributes to an xarray Dataset"""
        for var_name, attrs in self.variables.items():
            if var_name in ds:
                ds[var_name].attrs.update(attrs)

        ds.attrs.update(self.global_attributes)

    @classmethod
    def from_yaml(cls, path: Path):
        """Load attributes from a YAML file"""

        with path.open("r") as f:
            data = yaml.safe_load(f)

        return cls(**data)

    @classmethod
    def from_metadata_service(cls, slug: str):
        """Load ncoJson style attributes from a metadata service.

        The ncoJson document should contain a top level "attributes"
        key containing global attributes and an optional top level
        "variables" key containing variable attributes.

        We support both verbose ncoJson (level > 1, with attribute values as
        objects specifying attribute data type and value) and
        the concise format (level == 1, with attribute values only
        containing value) by converting verbose formats to concise.

        The metadata service to be queried is configured via the
        METADATA_SERVICE_URL, which should include a {slug} token
        to be replaced by dataset slug. We aim to agnostically
        support any metadata service capable of returning an ncoJson
        record for a dataset including asset manager, ERDDAP, and
        simple webservers serving static ncoJson documents.
        """

        if not METADATA_SERVICE_URL:
            return

        try:
            response = requests.get(
                METADATA_SERVICE_URL.format(slug=slug),
                timeout=5,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"Metadata service document not found for {slug}")
            else:
                print(f"Error when requesting {slug} from metadata service: {e}")
                raise e
            return

        ncojson = standardize_ncojson(response.json())

        # remove unwanted global attributes
        if "attributes" in ncojson:
            ncojson["attributes"] = {
                k: v
                for k, v in ncojson["attributes"].items()
                if k
                not in ["defaultDataQuery", "time_coverage_end", "time_coverage_start"]
            }

        # unwrap variable attributes if they are in an 'attributes' child dict
        # example {'water_surface_above_navd88': {'type': 'double', 'attributes': {...}}
        ncojson["variables"] = {
            k: v if "attributes" not in v else v["attributes"]
            for k, v in ncojson.get("variables", {}).items()
        }

        # remove some time variable attributes if present
        # because xarray sets them explicitly or they are dynamic
        if "time" in ncojson["variables"]:
            ncojson["variables"]["time"] = {
                k: v
                for k, v in ncojson["variables"]["time"].items()
                if k not in ["actual_range", "calendar", "units"]
            }

        data = {
            "global_attributes": ncojson.get("attributes", {}),
            "variables": ncojson["variables"],
        }

        return cls(**data)


class AttributeConfigMixin:
    """Mixin to add attribute configuration to a dataset or reader"""

    attributes: Annotated[
        NcAttributes,
        Field(
            default_factory=NcAttributes,
            description="NetCDF attributes to add to the dataset and variables",
        ),
    ]
