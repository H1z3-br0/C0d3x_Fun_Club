from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .schemas import TaskSpec
from .utils import dump_yaml_file, ensure_dir, slugify


class CTFdError(RuntimeError):
    pass


@dataclass
class CTFdChallenge:
    challenge_id: int
    name: str
    value: int | None
    category: str | None
    solves: int = 0
    description: str | None = None
    connection_info: str | None = None
    file_urls: list[str] | None = None


class CTFdClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        session_cookie: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.session_cookie = session_cookie
        self._client = None

    async def __aenter__(self) -> CTFdClient:
        headers = {}
        cookies = {}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        if self.session_cookie:
            cookies["session"] = self.session_cookie
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            cookies=cookies,
            timeout=60,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()

    @property
    def client(self):
        if self._client is None:
            raise RuntimeError("CTFdClient не открыт")
        return self._client

    async def list_challenges(self) -> list[CTFdChallenge]:
        payload = await self._get_json("/api/v1/challenges")
        items = payload.get("data", [])
        challenges: list[CTFdChallenge] = []
        for item in items:
            challenges.append(
                CTFdChallenge(
                    challenge_id=int(item["id"]),
                    name=str(item["name"]),
                    value=_maybe_int(item.get("value")),
                    category=item.get("category"),
                    solves=_maybe_int(item.get("solves")) or 0,
                )
            )
        return challenges

    async def get_challenge(self, challenge_id: int) -> CTFdChallenge:
        payload = await self._get_json(f"/api/v1/challenges/{challenge_id}")
        item = payload.get("data", {})
        file_urls = self._extract_file_urls(item.get("files", []))
        if not file_urls:
            file_urls = await self.get_challenge_files(challenge_id)
        return CTFdChallenge(
            challenge_id=int(item["id"]),
            name=str(item["name"]),
            value=_maybe_int(item.get("value")),
            category=item.get("category"),
            solves=_maybe_int(item.get("solves")) or 0,
            description=item.get("description"),
            connection_info=item.get("connection_info"),
            file_urls=file_urls,
        )

    async def get_challenge_files(self, challenge_id: int) -> list[str]:
        payload = await self._get_json(f"/api/v1/challenges/{challenge_id}/files")
        return self._extract_file_urls(payload.get("data", []))

    async def resolve_exact_name(self, challenge_name: str) -> CTFdChallenge:
        matches = [
            challenge
            for challenge in await self.list_challenges()
            if challenge.name == challenge_name
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise CTFdError(f"CTFd exact match not found for challenge name: {challenge_name}")
        raise CTFdError(
            "CTFd exact match is ambiguous for challenge name "
            f"{challenge_name}: {[item.name for item in matches]}"
        )

    async def download_challenge(self, challenge: CTFdChallenge, workspace_root: Path) -> TaskSpec:
        task_root = ensure_dir(workspace_root / "downloads" / slugify(challenge.name))
        detail = await self.get_challenge(challenge.challenge_id)
        for index, file_url in enumerate(detail.file_urls or [], start=1):
            filename = _filename_from_url(file_url) or f"file-{index}"
            target = task_root / filename
            await self._download(file_url, target)

        task_yaml = task_root / "task.yaml"
        dump_yaml_file(
            task_yaml,
            {
                "name": challenge.name,
                "points": detail.value or 0,
                "category": detail.category or "",
                "url": self.base_url,
            },
        )

        description = detail.description or detail.connection_info or ""
        if description:
            (task_root / "README.generated.md").write_text(description, encoding="utf-8")

        files = sorted(
            str(item.relative_to(task_root)) for item in task_root.rglob("*") if item.is_file()
        )
        return TaskSpec(
            task_id=slugify(challenge.name),
            name=challenge.name,
            task_dir=str(task_root),
            description=description,
            source="ctfd",
            points=detail.value,
            category=detail.category,
            metadata={
                "challenge_id": detail.challenge_id,
                "solves": detail.solves,
                "ctfd_url": self.base_url,
            },
            files=files,
        )

    def _extract_file_urls(self, items: list[Any]) -> list[str]:
        file_urls = []
        for file_entry in items:
            if isinstance(file_entry, dict):
                target = file_entry.get("url") or file_entry.get("location")
                if target:
                    file_urls.append(str(target))
            elif isinstance(file_entry, str):
                file_urls.append(file_entry)
        return file_urls

    async def get_scoreboard(self) -> list[dict[str, Any]]:
        payload = await self._get_json("/api/v1/scoreboard")
        return payload.get("data", [])

    async def _get_json(self, path: str) -> dict[str, Any]:
        response = await self.client.get(path)
        if response.status_code >= 400:
            raise CTFdError(f"CTFd API error {response.status_code}: {response.text}")
        payload = response.json()
        if not payload.get("success", True):
            raise CTFdError(f"CTFd API returned success=false for {path}: {payload}")
        return payload

    async def _download(self, url: str, target: Path) -> None:
        request_url, use_primary_client = self._prepare_download_request(url)
        if use_primary_client:
            response = await self.client.get(request_url)
        else:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as external_client:
                response = await external_client.get(request_url)
        if response.status_code >= 400:
            raise CTFdError(f"Не удалось скачать {url}: {response.status_code}")
        target.write_bytes(response.content)

    def _prepare_download_request(self, url: str) -> tuple[str, bool]:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            base = urlparse(self.base_url)
            same_origin = (parsed.scheme, parsed.netloc) == (base.scheme, base.netloc)
            return url, same_origin
        if url.startswith("/"):
            return url, True
        return f"/{url}", True


def compute_priority(challenge: CTFdChallenge) -> float:
    points = float(challenge.value or 100)
    solves = float(max(challenge.solves, 0))
    return points / (1.0 + solves)


def _maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _filename_from_url(url: str) -> str | None:
    stripped = urlparse(url).path.rstrip("/")
    if not stripped:
        return None
    filename = stripped.split("/")[-1] or None
    return unquote(filename) if filename else None
