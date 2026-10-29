"""The test suite itself must have the plugins its configuration requires."""


def test_asyncio_plugin_is_available():
    import pytest_asyncio

    assert pytest_asyncio.__version__
