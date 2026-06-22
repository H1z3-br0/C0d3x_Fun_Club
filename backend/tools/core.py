"""SDK-agnostic tool logic — pure async functions, no model-SDK types."""

import asyncio
import ipaddress
import json
import shlex
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

MAX_OUTPUT = 24_000


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    head = "\n".join(lines[:200])
    return head[:limit] + f"\n... [truncated — {len(text)} total chars, {len(lines)} lines]"


def _resolve(path: str, workdir: str | None) -> str:
    """Resolve a model-supplied path: absolute as-is, relative against the model's workdir."""
    if workdir and not path.startswith("/"):
        return f"{workdir.rstrip('/')}/{path}"
    return path


async def do_bash(sandbox, command: str, timeout_seconds: int = 60, workdir: str | None = None) -> str:
    result = await sandbox.exec(command, timeout_s=timeout_seconds, workdir=workdir)
    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr}")
    if result.exit_code != 0:
        parts.append(f"[exit {result.exit_code}]")
    out = "\n".join(parts).strip() or "(no output)"
    return _truncate(out)


async def do_read_file(sandbox, path: str, workdir: str | None = None) -> str:
    path = _resolve(path, workdir)
    try:
        data = await sandbox.read_file(path)
    except Exception as e:
        return f"Error reading file: {e}"

    if isinstance(data, bytes):
        sample = data[:4096]
        non_text = sum(
            1
            for b in sample
            if b == 0 or (b < 9 and b not in (7, 8)) or (9 < b < 13) or (13 < b < 32 and b != 27)
        )
        if len(sample) > 0 and non_text / len(sample) > 0.05:
            return (
                f"Binary file ({len(data)} bytes) — use bash to inspect it:\n"
                f"  file {path}\n"
                f"  xxd {path} | head -40\n"
                f"  strings {path}\n"
                f"  exiftool {path}\n"
                f"  binwalk {path}"
            )
        return _truncate(data.decode("utf-8", errors="replace"))

    return _truncate(data) if isinstance(data, str) else data


async def do_write_file(sandbox, path: str, content: str, workdir: str | None = None) -> str:
    path = _resolve(path, workdir)
    try:
        await sandbox.write_file(path, content)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def do_list_files(sandbox, path: str = "/challenge/distfiles", workdir: str | None = None) -> str:
    path = _resolve(path, workdir)
    result = await sandbox.exec(f"ls -la {shlex.quote(path)}")
    out = result.stdout.strip()
    if result.exit_code != 0:
        return result.stderr.strip() or f"Error listing {path}"
    return out or f"{path} is empty."


async def do_submit_flag(ctfd, challenge_name: str, flag: str) -> tuple[str, bool]:
    """Submit a flag. Returns (display_message, is_confirmed)."""
    flag = flag.strip()
    if not flag:
        return "Empty flag — nothing to submit.", False

    try:
        result = await ctfd.submit_flag(challenge_name, flag)
        is_confirmed = result.status in ("correct", "already_solved")
        return result.display, is_confirmed
    except Exception as e:
        return f"submit_flag error: {e}", False


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_is_internal(url: str) -> bool:
    """Block fetches that resolve to internal/private addresses.

    Resolves the hostname via DNS and checks every returned address — so a public
    hostname pointing at an internal IP (decimal/hex IP literals, IPv6) is caught, not
    just literal RFC1918 strings. Unresolvable hosts are allowed through (httpx fails
    the connection itself).

    Best-effort only: this is a pre-connect check, and httpx re-resolves at connect
    time, so a DNS-rebinding host that flips its answer between the two lookups could
    slip past. A true fix would pin the resolved IP into the connection. We don't,
    because the solver already has unrestricted network via `bash` in the sandbox —
    this guard stops accidental/obvious internal fetches, not a determined attacker.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return True
    try:
        return _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        pass  # not a literal IP — resolve it
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            if _ip_is_blocked(ipaddress.ip_address(info[4][0])):
                return True
        except ValueError:
            continue
    return False


async def do_web_fetch(url: str, method: str = "GET", body: str = "") -> str:
    # getaddrinfo is blocking — run it in a thread.
    if await asyncio.to_thread(_resolve_is_internal, url):
        return "Fetch error: access to internal/private networks is blocked."
    try:
        # verify=False: CTF challenge services often use self-signed certs
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.request(
                method,
                url,
                content=body or None,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            text = resp.text
            prefix = f"HTTP {resp.status_code} {resp.reason_phrase}\n{'─' * 40}\n"
            if len(text) > 20_000:
                text = text[:20_000] + f"\n... [truncated, total {len(resp.text)} bytes]"
            return prefix + text
    except Exception as e:
        return f"Fetch error: {e}"


async def do_web_search(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo HTML and return top results."""
    try:
        url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.post(
                url,
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            )
            text = resp.text

        # Parse results from DDG HTML response
        import re
        results: list[str] = []
        # DDG HTML wraps each result in <a class="result__a" href="...">title</a>
        # and snippet in <a class="result__snippet">...</a>
        links = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            text,
        )
        snippets = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            text,
            re.DOTALL,
        )
        for i, (href, title) in enumerate(links[:max_results]):
            title_clean = re.sub(r"<[^>]+>", "", title).strip()
            snippet_clean = ""
            if i < len(snippets):
                snippet_clean = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            results.append(f"{i+1}. {title_clean}\n   {href}\n   {snippet_clean}")

        if not results:
            return f"No results found for: {query}"
        return "\n\n".join(results)
    except Exception as e:
        return f"Search error: {e}"


async def do_webhook_create() -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://webhook.site/token")
            if resp.status_code != 200:
                return f"webhook.site error: HTTP {resp.status_code}"
            data = resp.json()
            return json.dumps({"uuid": data["uuid"], "url": f"https://webhook.site/{data['uuid']}"})
    except Exception as e:
        return f"webhook_create error: {e}"


async def do_webhook_get_requests(uuid: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://webhook.site/token/{uuid}/requests")
            if resp.status_code != 200:
                return f"webhook.site error: HTTP {resp.status_code}"
            data = resp.json()
            if not data.get("data"):
                return "No requests received yet."
            out = json.dumps(data["data"], indent=2)
            return out[:8000] if len(out) > 8000 else out
    except Exception as e:
        return f"webhook_get_requests error: {e}"


async def do_check_findings(message_bus, model_spec: str) -> str:
    """Get unread findings from sibling solvers."""
    if not message_bus:
        return "No message bus available."
    findings = await message_bus.check(model_spec)
    if not findings:
        return "No new findings from other agents."
    return message_bus.format_unread(findings)


# Image constants (shared with vision wrapper)
IMAGE_EXTS_FOR_VISION: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".webp": "image/webp",
}

IMAGE_MAGIC: dict[str, list[int]] = {
    "image/png": [0x89, 0x50, 0x4E, 0x47],
    "image/jpeg": [0xFF, 0xD8, 0xFF],
    "image/gif": [0x47, 0x49, 0x46],
    "image/bmp": [0x42, 0x4D],
    "image/webp": [0x52, 0x49, 0x46, 0x46],
}

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4 MB


def _has_valid_magic(data: bytes, mime_type: str) -> bool:
    magic = IMAGE_MAGIC.get(mime_type)
    if not magic:
        return True
    return all(i < len(data) and data[i] == b for i, b in enumerate(magic))


async def do_view_image(
    sandbox, filename: str, use_vision: bool, workdir: str | None = None
) -> tuple[bytes, str] | str:
    """Returns (image_bytes, media_type) on success, or error string."""
    # Strip leading path if model passes full container path
    basename = Path(filename).name
    ext = Path(basename).suffix.lower()
    mime_type = IMAGE_EXTS_FOR_VISION.get(ext)
    if not mime_type:
        return f"Not a supported image type: {filename}"

    if not use_vision:
        return "Vision not available for this model. Use bash tools (steghide, zsteg, exiftool, strings) instead."

    # Try the filename as-is first (if it's an absolute path), then search standard dirs
    # (the model's own workdir first, then shared distfiles).
    search_paths = []
    if filename.startswith("/"):
        search_paths.append(filename)
    if workdir:
        search_paths.append(f"{workdir.rstrip('/')}/{basename}")
    search_paths.append(f"/challenge/distfiles/{basename}")

    for path in search_paths:
        try:
            data = await sandbox.read_file_bytes(path)
            if not _has_valid_magic(data, mime_type):
                return (
                    "Cannot load image: file appears invalid or corrupted. "
                    "Fix the magic bytes in the sandbox first, save it into your workspace, "
                    "then call view_image again."
                )
            if len(data) > MAX_IMAGE_BYTES:
                return (
                    f"Image too large for vision ({len(data) / 1024 / 1024:.1f} MB > 4 MB limit). "
                    "Use bash tools (steghide, zsteg, binwalk, exiftool, strings, xxd) instead."
                )
            return (data, mime_type)
        except Exception:
            continue

    return f"File not found: {filename} (searched: {', '.join(search_paths)})"
