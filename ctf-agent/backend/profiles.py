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
    return Path(__file__).resolve().parents[1] / "container" / "profiles.md"


@lru_cache(maxsize=1)
def load_profile_catalog() -> tuple[DockerProfile, ...]:
    path = profiles_doc_path()
    text = path.read_text(encoding="utf-8")
    start = text.find(PROFILE_SECTION_START)
    end = text.find(PROFILE_SECTION_END)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Profile section not found in {path}")

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
        raise RuntimeError(f"Profile list is empty in {path}")
    if DEFAULT_PROFILE not in {item.name for item in profiles}:
        raise RuntimeError(f"Profile {DEFAULT_PROFILE} is missing in {path}")
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


def suggest_profile(category: str | None) -> str:
    """Map a CTF category to the best-fit Docker profile."""
    if not category:
        return DEFAULT_PROFILE
    cat = category.strip().lower()
    if not cat:
        return DEFAULT_PROFILE

    if "web" in cat:
        return "web"
    if "pwn" in cat or "binary" in cat or "binexp" in cat:
        return "pwn-userspace"
    if "reverse" in cat or cat in {"re", "rev"}:
        return "reverse-static"
    if "forensics" in cat or "forensic" in cat:
        return "forensics-disk"
    if "crypto" in cat or "crypt" in cat:
        return "crypto"
    if "steg" in cat:
        return "stego-image"
    if "network" in cat or "net" in cat:
        return "network"
    if "mobile" in cat or "android" in cat or "apk" in cat:
        return "mobile"
    if "dotnet" in cat or ".net" in cat:
        return "reverse-dotnet"
    if "wasm" in cat or "webassembly" in cat:
        return "reverse-wasm"
    if "ai" in cat or "ml" in cat:
        return "ai-ml"

    return DEFAULT_PROFILE


def render_profile_reference() -> str:
    lines = []
    for item in load_profile_catalog():
        default_suffix = " (default)" if item.name == DEFAULT_PROFILE else ""
        lines.append(f"- {item.name}{default_suffix}: {item.description}")
    return "\n".join(lines)
