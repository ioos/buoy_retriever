"""
Setup sentry and use some sane defaults
"""

import functools
from typing import Annotated

import dagster as dg
import sentry_sdk
from pydantic import BaseModel, Field

from .config.env import (
    IMAGE_TAG,
    SENTRY_DSN,
    SENTRY_PROFILE_SAMPLE_RATE,
    SENTRY_TRACES_SAMPLE_RATE,
)


class SentryConfig(BaseModel):
    """Configure Sentry for a pipeline"""

    pipeline_name: Annotated[
        str,
        Field(description="Name of the pipeline for Sentry tagging"),
    ]

    def model_post_init(self, context):
        """Post init hook to setup Sentry"""
        self.setup_sentry()

    def setup_sentry(self):
        """Setup Sentry SDK"""
        setup_sentry(self.pipeline_name)

    def log_op_context(self, context: dg.OpExecutionContext):
        """Log Dagster OP context to Sentry"""
        data = {
            "op_name": context.op_def.name,
            "retry_number": context.retry_number,
            "pipeline_name": self.pipeline_name,
        }

        try:
            sentry_sdk.set_tag("job_name", context.job_name)
            data["job_name"] = context.job_name
            data["run_config"] = context.run.run_config
            sentry_sdk.set_tag("run_id", context.run.run_id)
            data["run_id"] = context.run.run_id
        except dg.DagsterInvalidPropertyError:
            pass

        sentry_sdk.add_breadcrumb(
            category="dagster",
            message=f"{self.pipeline_name} - {context.op_def.name}",
            level="info",
            data=data,
        )
        sentry_sdk.set_tag("op_name", context.op_def.name)
        sentry_sdk.set_tag("pipeline_name", self.pipeline_name)

        sentry_sdk.set_context("dagster_op", data)

    def capture_op_exceptions(self, func):
        """
        Captures exceptions thrown by Dagster Ops and forwards them to Sentry
        before re-throwing them for Dagster.

        Expects ops to receive Dagster context as the first argument,
        but it will continue if it doesn't (it just won't get as much context).

        It will log a unique ID that can be then entered into Sentry to find
        the exception.

        This should be used as a decorator between Dagster's `@op`,
        and the function to be handled.

        @op
        @sentry.capture_op_exceptions
        def op_with_error(context):
            raise Exception("Ahh!")
        """

        @functools.wraps(func)
        def wrapped_fn(*args, **kwargs):
            logger = dg.get_dagster_logger("sentry")

            try:
                self.log_op_context(args[0])
            except (AttributeError, IndexError):
                logger.warning("Sentry did not find execution context as the first arg")

            with sentry_sdk.start_transaction(
                op=func.__name__,
                name=f"{self.pipeline_name} op: {func.__name__}",
            ):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    event_id = sentry_sdk.capture_exception(e)
                    logger.error(f"Sentry captured an exception. Event ID: {event_id}")
                    raise e

        return wrapped_fn

    capture_asset_exceptions = capture_op_exceptions


def setup_sentry(pipeline_name: str):
    """
    Setup the sentry SDK for Dagster.

    Additionally if IMAGE_TAG is defined it will be set as the release,
    and TRACES_SAMPLE_RATE can be set 0-1 otherwise will default to 0.

    Manually sets up a bunch of the default integrations and disables logging of dagster
    to quiet things down.
    """

    # ignore_logger("dagster")

    environment = "dev" if "dev" in IMAGE_TAG else "production"

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=environment,
        server_name=pipeline_name,
        # integrations=[
        #     AtexitIntegration(),
        #     DedupeIntegration(),
        #     StdlibIntegration(),
        #     ModulesIntegration(),
        #     ArgvIntegration(),
        #     LoggingIntegration(),
        # ],
        # before_send=dagster_before_send,
        # Add request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        # To collect profiles for all profile sessions,
        # set `profile_session_sample_rate` to 1.0.
        profile_session_sample_rate=SENTRY_PROFILE_SAMPLE_RATE,
        # Profiles will be automatically collected while
        # there is an active span.
        profile_lifecycle="trace",
        # Enable logs to be sent to Sentry
        enable_logs=True,
    )

    sentry_sdk.set_tag("image_tag", IMAGE_TAG)
    sentry_sdk.set_tag("pipeline_name", pipeline_name)


def dagster_before_send(event, hint):
    """
    Don't send sentry event id error logs to sentry
    """
    logentry = event.get("logentry")
    if logentry and "Sentry captured an exception. Event ID:" in logentry.get(
        "message",
        "",
    ):
        return None
    return event
