import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--aveva",
        action="store_true",
        default=False,
        help="run tests that require Aveva API access",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "aveva: mark test as requiring Aveva API access",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--aveva"):
        skip_aveva = pytest.mark.skip(reason="need --aveva option to run")
        for item in items:
            if "aveva" in item.keywords:
                item.add_marker(skip_aveva)
