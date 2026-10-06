from numbers import Real
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class QartodTestDefinition(BaseModel):
    """Base configuration for the qartod tests"""

    test_name: str

    threshold_type: Annotated[
        str | None,
        Field(
            description="Optional argument that defaults to fixed."
            "Specifies how numeric thresholds are interpreted. "
            "When set to 'fixed', configured thresholds are used directly. "
            "When set to 'std', configured thresholds are treated as "
            "multipliers of the monthly standard deviation.",
        ),
    ] = "fixed"

    def to_config(self, **kwargs) -> str:
        raise NotImplementedError


class GrossRange(QartodTestDefinition):
    """Configuration options for the gross range test"""

    test_name: Literal["gross_range_test"] = "gross_range_test"

    suspect_span: Annotated[
        tuple[float, float],
        Field(
            description="Valid value range for the suspect test. "
            "Values outside this range are flagged as suspect.",
        ),
    ]

    fail_span: Annotated[
        tuple[float, float],
        Field(
            description="Valid value range for the fail test. "
            "Values outside this range are flagged as fail.",
        ),
    ]

    def to_config(self, **kwargs) -> str:
        return {
            self.test_name: {
                "suspect_span": list(self.suspect_span),
                "fail_span": list(self.fail_span),
            },
        }


class FlatLine(QartodTestDefinition):
    """Configuration options for the flat line test"""

    test_name: Literal["flat_line_test"] = "flat_line_test"

    tolerance: Annotated[
        float,
        Field(
            description="Maximum difference between observations for them to be "
            "considered effectively unchanged.",
        ),
    ]

    suspect_threshold: Annotated[
        float,
        Field(
            description="Duration, in seconds, that values may remain within the "
            "specified tolerance before being flagged as suspect.",
        ),
    ]

    fail_threshold: Annotated[
        float,
        Field(
            description="Duration, in seconds, that values may remain within the "
            "specified tolerance before being flagged as fail.",
        ),
    ]

    def to_config(self, **kwargs) -> str:
        return {
            self.test_name: {
                "tolerance": self.tolerance,
                "fail_threshold": self.fail_threshold,
                "suspect_threshold": self.suspect_threshold,
            },
        }


class SpikeTest(QartodTestDefinition):
    """Configuration options for the spike test"""

    test_name: Literal["spike_test"] = "spike_test"

    suspect_threshold: Annotated[
        float,
        Field(
            description="Spike magnitude above which an observation is flagged as suspect.",
        ),
    ]

    fail_threshold: Annotated[
        float,
        Field(
            description="Spike magnitude above which an observation is flagged as fail.",
        ),
    ]

    def to_config(self, **kwargs) -> str:
        update_threshold = self.threshold_type == "std"

        return {
            self.test_name: {
                "fail_threshold": self.fail_threshold * kwargs["std"]
                if update_threshold
                else self.fail_threshold,
                "suspect_threshold": self.suspect_threshold * kwargs["std"]
                if update_threshold
                else self.suspect_threshold,
            },
        }


class RateOfChange(QartodTestDefinition):
    """Configuration options for the rate of change test"""

    test_name: Literal["rate_of_change_test"] = "rate_of_change_test"

    threshold: Annotated[
        float,
        Field(
            description="Rate-of-change threshold above which an observation is "
            "flagged as suspect.",
        ),
    ]

    fail_threshold: Annotated[
        float | None,
        Field(
            description="Rate-of-change threshold above which an observation is "
            "flagged as fail.",
        ),
    ] = None

    def to_config(self, **kwargs) -> str:
        update_threshold = self.threshold_type == "std"

        thresholds_args = {
            "threshold": self.threshold * kwargs["std"]
            if update_threshold
            else self.threshold,
        }
        if self.fail_threshold is not None:
            thresholds_args["fail_threshold"] = (
                self.fail_threshold * kwargs["std"]
                if update_threshold
                else self.fail_threshold
            )

        return {self.test_name: thresholds_args}


class ClimatologyPeriodConfig(BaseModel):
    """Configuration options for the QARTOD climatology test."""

    vspan: Annotated[
        tuple[Real, Real],
        Field(
            description="Valid value range for this climatology interval. "
            "Values outside this range are flagged as suspect.",
        ),
    ]

    tspan: Annotated[
        tuple[Real, Real],
        Field(
            description="Time interval over which this climatology configuration applies. "
            "When 'period' is provided, values are interpreted using that "
            "datetime component; otherwise they represent a datetime range.",
        ),
    ]

    fspan: Annotated[
        tuple[Real, Real] | None,
        Field(
            description="Optional fail value range for this climatology interval. "
            "Values outside this range are flagged as fail.",
        ),
    ] = None

    zspan: Annotated[
        tuple[Real, Real] | None,
        Field(
            description="Optional depth range over which this climatology "
            "configuration applies.",
        ),
    ] = None

    period: Annotated[
        str | None,
        Field(
            description="Optional datetime component used to interpret numeric tspan "
            "values, such as month or day of year.",
        ),
    ] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_config(self) -> str:
        return (
            {
                "vspan": list(self.vspan),
                "tspan": list(self.tspan),
                "zspan": None,
            }
            | ({"fspan": list(self.fspan)} if self.fspan is not None else {})
            | ({"period": self.period} if self.period is not None else {})
        )


class ClimatologyTest(QartodTestDefinition):
    """Configuration for the climatology tests"""

    test_name: Literal["climatology_test"] = "climatology_test"

    config: Annotated[
        list[ClimatologyPeriodConfig],
        Field(
            description="List of climatology period configurations (ie. each season having different valid values)",
        ),
    ]

    def to_config(self, **kwargs) -> str:
        return {
            self.test_name: {
                "config": [c.to_config() for c in self.config],
            },
        }


class QartodConfig(BaseModel):
    """Add qartod configurations to a dataset"""

    variable_name: Annotated[
        str,
        Field(
            description="Name of the variable to which the QARTOD tests apply.",
        ),
    ]

    qartod_test_config: Annotated[
        list[GrossRange | FlatLine | RateOfChange | SpikeTest | ClimatologyTest],
        Field(
            description="QARTOD test configurations to apply to the variable.",
        ),
    ]

    """Build the ioos_qc configuration.

        Tests configured with threshold_type='std' use the supplied
        monthly standard deviation to calculate their numeric thresholds.
        """

    def to_qartod_config(self, std: float) -> str:
        qc = {self.variable_name: {"qartod": {}}}
        for var in self.qartod_test_config:
            qc[self.variable_name]["qartod"] |= var.to_config(std=std)

        return qc


class QartodConfigMixIn:
    """Mixin to add qartod configurations to a dataset"""

    qartod_config: Annotated[
        list[QartodConfig],
        Field(
            description="QARTOD configurations to apply to dataset variables.",
        ),
    ] = None
