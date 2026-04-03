"""Rich console output for verbose mode — human-friendly live view of solver activity."""

from __future__ import annotations

import time

from rich.console import Console

_console = Console(highlight=False)
_verbose = False

_AGENT_STYLES = ["cyan", "green", "yellow", "magenta", "blue", "bright_red"]
_style_map: dict[str, str] = {}


def set_verbose(enabled: bool = True) -> None:
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    return _verbose


def _style_for(agent: str) -> str:
    if agent not in _style_map:
        _style_map[agent] = _AGENT_STYLES[len(_style_map) % len(_AGENT_STYLES)]
    return _style_map[agent]


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _truncate(text: str, limit: int = 160) -> str:
    text = text.replace("\n", " ↵ ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _format_args(tool: str, args: dict) -> str:
    """Extract the most useful summary from tool args."""
    if tool == "bash":
        return args.get("command", "")
    if tool == "read_file":
        return args.get("path", "")
    if tool == "write_file":
        path = args.get("path", "")
        size = len(args.get("content", ""))
        return f"{path} ({size} bytes)"
    if tool == "list_files":
        return args.get("path", "/challenge/workspace")
    if tool == "submit_flag":
        return args.get("flag", "")
    if tool == "web_fetch":
        return f"{args.get('method', 'GET')} {args.get('url', '')}"
    if tool == "view_image":
        return args.get("filename", "")
    if tool == "notify_coordinator":
        return args.get("message", "")[:80]
    return str(args)[:120]


def _format_result(tool: str, result: str) -> str:
    """Abbreviate tool results for display."""
    if not result:
        return "(empty)"
    lines = result.strip().split("\n")
    total_lines = len(lines)
    total_chars = len(result)
    first_line = lines[0][:160]

    if total_lines == 1 and total_chars <= 160:
        return result.strip()
    if total_chars > 500:
        return f"{first_line}… ({total_lines} lines, {total_chars // 1024}KB)"
    return f"{first_line}… ({total_lines} lines)"


def log_tool_call(agent: str, step: int, tool: str, args: dict) -> None:
    if not _verbose:
        return
    s = _style_for(agent)
    summary = _truncate(_format_args(tool, args))
    icon = ">>>" if tool == "submit_flag" else ">>>"
    _console.print(
        f"[dim]{_ts()}[/dim] [{s}]{agent:<26}[/{s}] "
        f"{icon} [bold]{tool}[/bold]: {summary}",
    )


def log_tool_result(agent: str, step: int, tool: str, result: str, duration: float = 0) -> None:
    if not _verbose:
        return
    s = _style_for(agent)
    summary = _truncate(_format_result(tool, result))
    dur = f" [dim]({duration:.1f}s)[/dim]" if duration > 0.1 else ""

    if tool == "submit_flag":
        if "CORRECT" in result or "DRY RUN" in result:
            icon = "[bold green]OK[/bold green] "
        elif "INCORRECT" in result or "COOLDOWN" in result:
            icon = "[bold red]FAIL[/bold red]"
        else:
            icon = "[yellow]??[/yellow] "
    else:
        icon = "[green]<-[/green] " if "[exit" not in result else "[red]<![/red] "

    _console.print(
        f"[dim]{_ts()}[/dim] [{s}]{'':<26}[/{s}] "
        f"{icon} {summary}{dur}",
    )


def log_model_text(agent: str, step: int, text: str) -> None:
    if not _verbose:
        return
    s = _style_for(agent)
    _console.print(
        f"[dim]{_ts()}[/dim] [{s}]{agent:<26}[/{s}] "
        f"[dim]...[/dim] {_truncate(text, 200)}",
    )


def log_usage(agent: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    if not _verbose:
        return
    s = _style_for(agent)
    _console.print(
        f"[dim]{_ts()}[/dim] [{s}]{'':<26}[/{s}] "
        f"[dim]   in={input_tokens:,} out={output_tokens:,} cost=${cost_usd:.4f}[/dim]",
    )


def log_event(agent: str, message: str, style: str = "") -> None:
    if not _verbose:
        return
    s = _style_for(agent)
    _console.print(
        f"[dim]{_ts()}[/dim] [{s}]{agent:<26}[/{s}] "
        f"[{style}]{message}[/{style}]" if style else
        f"[dim]{_ts()}[/dim] [{s}]{agent:<26}[/{s}] {message}",
    )
