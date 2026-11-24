"""Mixkit is link hand-off only; no adapter may reach it."""
import pytest
from footage_scout import providers
from footage_scout.core import FscError, load_sources


def test_mixkit_link_only():
    s = load_sources()["mixkit"]
    assert s["tier"] == "T3" and "mixkit" not in providers.ADAPTERS
    with pytest.raises(FscError):
        providers.get(None, s)
