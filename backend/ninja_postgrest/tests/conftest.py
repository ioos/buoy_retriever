"""Test fixtures for the ninja_postgrest suite."""

import pytest


@pytest.fixture(autouse=True)
def _clear_contenttype_caches():
    """Keep guardian's and Django's ContentType caches in sync across tests.

    guardian caches content types in a process-level ``lru_cache``
    (``guardian.shortcuts._get_ct_cached``) that is never invalidated, while
    Django clears ``ContentType.objects`` between tests. Under the ``live_server``
    fixture those two views of the same content type can diverge and trigger a
    spurious ``MixedContentTypeError``. Clearing both before each test keeps them
    consistent. (Production content-type ids are stable, so this only matters in
    tests.)
    """
    from django.contrib.contenttypes.models import ContentType
    from guardian.shortcuts import _get_ct_cached

    _get_ct_cached.cache_clear()
    ContentType.objects.clear_cache()
    yield
