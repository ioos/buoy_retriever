import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from common.resource.s3fs_resource import S3Credentials, S3FSResource

pytest_plugins = ["common.test_utils.snapshot"]


TEST_DATA_DIR = Path("/mnt/test-data/s3_timeseries/")


def pytest_addoption(parser):
    parser.addoption(
        "--aws",
        action="store_true",
        default=False,
        help="run tests that require AWS S3 access",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "aws: mark test as requiring AWS S3 access",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--aws"):
        skip_aws = pytest.mark.skip(reason="need --aws option to run")
        for item in items:
            if "aws" in item.keywords:
                item.add_marker(skip_aws)


@pytest.fixture
def s3_credentials():
    return S3Credentials(
        access_key_id=os.environ["S3_TS_ACCESS_KEY_ID"],
        secret_access_key=os.environ["S3_TS_SECRET_ACCESS_KEY"],
    )


@pytest.fixture
def s3_resource(s3_credentials):
    return S3FSResource(
        credentials=s3_credentials,
        region_name="us-east-1",
    )


@pytest.fixture
def mocked_s3():
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    return TEST_DATA_DIR


@pytest.fixture(scope="session")
def lazy_datadir() -> Path:
    return TEST_DATA_DIR


@pytest.fixture(scope="session")
def original_datadir() -> Path:
    return TEST_DATA_DIR
