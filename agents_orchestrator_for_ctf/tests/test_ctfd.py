from __future__ import annotations

from pathlib import Path

import pytest

from ctf_swarm.ctfd import CTFdClient


class _DummyResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = b"payload") -> None:
        self.status_code = status_code
        self.content = content


class _PrimaryClient:
    def __init__(self, response: _DummyResponse | None = None) -> None:
        self.calls: list[str] = []
        self.response = response or _DummyResponse()

    async def get(self, url: str) -> _DummyResponse:
        self.calls.append(url)
        return self.response


def test_prepare_download_request_routes_same_origin_and_external_urls() -> None:
    client = CTFdClient("https://ctf.example")

    assert client._prepare_download_request("/files/challenge.zip") == (
        "/files/challenge.zip",
        True,
    )
    assert client._prepare_download_request("files/challenge.zip") == (
        "/files/challenge.zip",
        True,
    )
    assert client._prepare_download_request("https://ctf.example/files/challenge.zip") == (
        "https://ctf.example/files/challenge.zip",
        True,
    )
    assert client._prepare_download_request("https://cdn.example/challenge.zip") == (
        "https://cdn.example/challenge.zip",
        False,
    )


@pytest.mark.asyncio
async def test_download_uses_primary_client_for_same_origin_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CTFdClient("https://ctf.example")
    primary = _PrimaryClient(_DummyResponse(content=b"primary"))
    client._client = primary

    def _unexpected_external_client(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("external client must not be used for same-origin downloads")

    monkeypatch.setattr("ctf_swarm.ctfd.httpx.AsyncClient", _unexpected_external_client)

    target = tmp_path / "challenge.zip"
    await client._download("https://ctf.example/files/challenge.zip", target)

    assert primary.calls == ["https://ctf.example/files/challenge.zip"]
    assert target.read_bytes() == b"primary"


@pytest.mark.asyncio
async def test_download_uses_external_client_for_external_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = CTFdClient("https://ctf.example")
    primary = _PrimaryClient()
    client._client = primary
    external_calls: list[str] = []

    class _ExternalClient:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self) -> _ExternalClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> _DummyResponse:
            external_calls.append(url)
            return _DummyResponse(content=b"external")

    monkeypatch.setattr("ctf_swarm.ctfd.httpx.AsyncClient", _ExternalClient)

    target = tmp_path / "challenge.zip"
    await client._download("https://cdn.example/challenge.zip", target)

    assert primary.calls == []
    assert external_calls == ["https://cdn.example/challenge.zip"]
    assert target.read_bytes() == b"external"
