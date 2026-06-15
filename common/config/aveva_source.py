from typing import Annotated

from pydantic import BaseModel, Field


class AvevaSourceConfig(BaseModel):
    """Configuration for data coming from an S3 Bucket"""

    resource: Annotated[
        str,
        Field(description="The Aveva resource"),
    ]

    namespace: Annotated[
        str,
        Field(description="The Aveva namespace"),
    ]


class AvevaSourceMixin:
    """Mixin to add S3 source configuration to a dataset or reader"""

    aveva_source: Annotated[
        AvevaSourceConfig,
        Field(
            default_factory=AvevaSourceConfig,
            description="Configuration for accessing data in S3",
        ),
    ]
