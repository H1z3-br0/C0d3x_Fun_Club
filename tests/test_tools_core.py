import pytest

from backend.tools.core import _resolve_is_internal


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://[::1]/",
        "http://localhost:8000/",
    ],
)
def test_internal_targets_blocked(url):
    assert _resolve_is_internal(url) is True


@pytest.mark.parametrize("url", ["http://8.8.8.8/", "https://1.1.1.1/"])
def test_public_ip_literals_allowed(url):
    assert _resolve_is_internal(url) is False


def test_missing_host_blocked():
    assert _resolve_is_internal("not-a-url") is True
