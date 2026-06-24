from typing import Annotated, Literal

import pandas as pd
from pydantic import BaseModel, Field


class VarMap(BaseModel):
    """Configure a single variable mapping"""

    source: Annotated[
        str,
        Field(
            description="The source variable name in the input data",
        ),
    ]
    output: Annotated[
        str,
        Field(
            description="The output variable name in the dataset",
        ),
    ]


class VariableMappingMixin:
    """Mixin to add variable mapping configuration to a dataset or reader"""

    variable_mappings: Annotated[
        list[VarMap],
        Field(
            description="Variable name mappings, source to output dataset destination name",
            default_factory=list,
        ),
    ]

    def map_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Loop over variable_mappings and rename specified variables"""
        for var_map in self.variable_mappings:
            if var_map.source in df.columns:
                df = df.rename(columns={var_map.source: var_map.output})

        if len(set(df.columns)) != len(df.columns):
            """Deal with duplicate column names
               Combines columns with identical names by keeping the first non-null value for each row"""
            df = df.groupby(df.columns, axis=1).first()
        return df


class DepthMap(BaseModel):
    """Configure depth mapping for a single variable"""

    source_variable: Annotated[
        str,
        Field(
            description="The source variable name in the input data",
        ),
    ]
    depth: Annotated[
        int,
        Field(
            description="The depth (in meters) for this variable",
        ),
    ]


class DepthGroup(BaseModel):
    """Configure depth mappings for a variable"""

    output_variable: Annotated[
        str,
        Field(
            description="The output variable name in the dataset",
        ),
    ]
    depths: Annotated[
        list[DepthMap],
        Field(
            description="List of source variables and their corresponding depths",
        ),
    ]


class DepthMappingMixin:
    """Mixin to add depth mapping configuration to a dataset or reader"""

    depth_mappings: Annotated[
        list[DepthGroup],
        Field(
            description="Depth mappings for variables with multiple depth levels",
            default_factory=list,
        ),
    ]


class OptionalDepthMappingMixin:
    """Mixin to add depth mapping configuration to a dataset or reader"""

    depth_mappings: Annotated[
        list[DepthGroup] | None,
        Field(
            description="Depth mappings for variables with multiple depth levels",
        ),
    ] = None


class VariableConverter(BaseModel):
    converter_type: str

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


class SplitOperator(VariableConverter):
    """Takes the source variable, splits it on the separator and  maps the resulting array to new variables"""

    converter_type: Literal["split"] = "split"
    sep: Annotated[
        str,
        Field(
            description="The separator",
        ),
    ]
    col_data_type: Annotated[
        str,
        Field(
            description="The data type of the new variables",
        ),
    ] = "float"

    output_variables: Annotated[
        dict[int, str],
        Field(
            description="Mapping of index number to output variable.",
        ),
    ]
    source_variable: Annotated[
        str,
        Field(
            description="The source variable to split into multiple columns",
        ),
    ]

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        splt_col = df[self.source_variable].str.split(
            self.sep,
            expand=True,
        )
        for n_var in self.output_variables:
            df[self.output_variables[n_var]] = splt_col[n_var].astype(
                self.col_data_type,
            )
        df = df.drop(self.source_variable, axis=1)
        return df


class ProfileDepthMappings(BaseModel):
    depth: Annotated[
        float,
        Field(
            description="Optional- fixed depth for the mapping.",
        ),
    ] = None

    mappings: Annotated[
        dict[str, str],
        Field(
            description="Maps input variables to output variables at the current depth ",
        ),
    ]


class ProfileConverter(VariableConverter):
    converter_type: Literal["profile"] = "profile"

    profile_data: Annotated[
        list[ProfileDepthMappings],
        Field(
            description="Mapping for variables with multiple depth levels",
        ),
    ]

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        daily_dfs = []
        all_profile_vars = [
            var
            for depth_conf in self.profile_data
            for var in depth_conf.mappings.keys()
        ]

        non_profile_vars = df.columns.difference(all_profile_vars).tolist()
        for depth in self.profile_data:
            keep = non_profile_vars + list(depth.mappings.keys())

            df_depth = df[keep].copy()

            df_depth = df_depth.rename(columns=depth.mappings)

            if depth.depth is not None:
                df_depth["depth"] = float(depth.depth)

            daily_dfs.append(df_depth)

        return pd.concat(daily_dfs)


class DropColumns(VariableConverter):
    converter_type: Literal["drop"] = "drop"

    column_names: list[str]

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df = df.drop(columns=self.column_names)
        return df


class VariableConverterMixIn:
    """Mixin to add column conversion rules to a dataset"""

    variable_converter: Annotated[
        list[
            SplitOperator | DropColumns | ProfileConverter,
            Field(discriminator="converter_type"),
        ],
        Field(
            description="List of variable conversion steps",
        ),
    ] = None
