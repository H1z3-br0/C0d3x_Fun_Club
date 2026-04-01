from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_PROFILE = "base"
PROFILE_SECTION_START = "<!-- profiles:start -->"
PROFILE_SECTION_END = "<!-- profiles:end -->"
PROFILE_LINE_RE = re.compile(r"^- `(?P<name>[a-z0-9-]+)`: (?P<description>.+)$")


@dataclass(frozen=True)
class DockerProfile:
    name: str
    description: str


def profiles_doc_path() -> Path:
    return Path(__file__).resolve().parents[2] / "container" / "profiles.md"


@lru_cache(maxsize=1)
def load_profile_catalog() -> tuple[DockerProfile, ...]:
    path = profiles_doc_path()
    text = path.read_text(encoding="utf-8")
    start = text.find(PROFILE_SECTION_START)
    end = text.find(PROFILE_SECTION_END)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Не найден section с профилями в {path}")

    block = text[start + len(PROFILE_SECTION_START) : end]
    profiles: list[DockerProfile] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = PROFILE_LINE_RE.match(stripped)
        if not match:
            continue
        profiles.append(
            DockerProfile(
                name=match.group("name"),
                description=match.group("description").strip(),
            )
        )

    if not profiles:
        raise RuntimeError(f"Список профилей пуст в {path}")
    if DEFAULT_PROFILE not in {item.name for item in profiles}:
        raise RuntimeError(f"Профиль {DEFAULT_PROFILE} отсутствует в {path}")
    return tuple(profiles)


def available_profiles() -> tuple[str, ...]:
    return tuple(item.name for item in load_profile_catalog())


def profile_descriptions() -> dict[str, str]:
    return {item.name: item.description for item in load_profile_catalog()}


def normalize_profile_name(value: str | None) -> str:
    if value is None:
        return DEFAULT_PROFILE
    candidate = value.strip().lower()
    if not candidate:
        return DEFAULT_PROFILE
    if candidate not in available_profiles():
        return DEFAULT_PROFILE
    return candidate


def image_for_profile(profile: str) -> str:
    return f"ctf-swarm:{normalize_profile_name(profile)}"


def render_profile_reference() -> str:
    lines = []
    for item in load_profile_catalog():
        default_suffix = " (default)" if item.name == DEFAULT_PROFILE else ""
        lines.append(f"- {item.name}{default_suffix}: {item.description}")
    return "\n".join(lines)
