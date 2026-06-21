"""Per-agent cost tracking using genai-prices."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from genai_prices import calc_price

logger = logging.getLogger(__name__)

@dataclass
class RunUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def has_values(self) -> bool:
        return any((self.input_tokens, self.output_tokens, self.cache_read_tokens))

    def __iadd__(self, other: RunUsage) -> RunUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        return self


# Provider ID mapping for genai-prices
PROVIDER_MAP: dict[str, str] = {
    "codex": "openai",
    "claude": "anthropic",
}

# Local pricing table (per 1M tokens, USD). genai-prices doesn't know these exact
# model ids (GPT-5.5 is absent; the new Claude Opus ids may lag the snapshot), so we
# price them here and fall back to genai-prices for anything else.
#
# CONFIRMED — published rates. ESTIMATED — best-effort placeholders until the real
# upstream rate is known; costs derived from these are not trustworthy and are flagged
# at runtime (see `_warned_estimated`).
FALLBACK_PRICING: dict[str, dict[str, float]] = {
    # Claude Opus 4.8 / 4.7: $5.00 input / $25.00 output per 1M; cache reads ~0.1x.
    "claude-opus-4-8": {"input": 5.00, "cached_input": 0.50, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "cached_input": 0.50, "output": 25.00},
    # GPT-5.5: ESTIMATE — replace with the real rate from your upstream account.
    "gpt-5.5": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
}

# Model ids whose pricing above is a guess. Cost for these is reported but unreliable.
ESTIMATED_PRICING_MODELS: set[str] = {"gpt-5.5"}
_warned_estimated: set[str] = set()


def _calc_fallback_cost(usage: RunUsage, model: str) -> float | None:
    pricing = FALLBACK_PRICING.get(model)
    if not pricing:
        return None
    input_rate = pricing.get("input", 0)
    cached_rate = pricing.get("cached_input", input_rate)
    output_rate = pricing.get("output", 0)
    uncached = max(0, usage.input_tokens - usage.cache_read_tokens)
    return (
        (uncached * input_rate) / 1_000_000
        + (usage.cache_read_tokens * cached_rate) / 1_000_000
        + (usage.output_tokens * output_rate) / 1_000_000
    )


def calc_cost(usage: RunUsage, model_name: str, provider_spec: str = "") -> float:
    """Calculate cost.

    Our own FALLBACK_PRICING is authoritative for the supported models (genai-prices
    doesn't know these ids); fall back to genai-prices for anything else so the number
    is never silently $0.
    """
    if not usage.has_values():
        return 0.0

    fallback = _calc_fallback_cost(usage, model_name)
    if fallback is not None:
        if model_name in ESTIMATED_PRICING_MODELS and model_name not in _warned_estimated:
            _warned_estimated.add(model_name)
            logger.warning(
                "Cost for %s uses ESTIMATED pricing — reported $ figures are not reliable. "
                "Set the real rate in FALLBACK_PRICING.", model_name
            )
        return fallback

    provider_id = PROVIDER_MAP.get(provider_spec, "unknown")
    try:
        price = calc_price(usage, model_name, provider_id=provider_id)
        return float(price.total_price)
    except Exception as e:
        logger.warning("Could not price %s (%s) — recording $0; add it to FALLBACK_PRICING", model_name, e)
        return 0.0


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _cache_rate(usage: RunUsage) -> str:
    """Compute cache hit rate as a percentage string."""
    if usage.input_tokens == 0:
        return "n/a"
    rate = (usage.cache_read_tokens / usage.input_tokens) * 100
    return f"{rate:.0f}%"


@dataclass
class AgentUsage:
    usage: RunUsage = field(default_factory=RunUsage)
    model_name: str = ""
    provider_spec: str = ""
    duration_seconds: float = 0.0
    cost_usd: float = 0.0


@dataclass
class CostTracker:
    by_agent: dict[str, AgentUsage] = field(default_factory=dict)

    def record_tokens(
        self,
        agent_name: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        provider_spec: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        """Record token usage without requiring SDK-specific types."""
        usage = RunUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        self.record(agent_name, usage, model_name, provider_spec, duration_seconds)

    def record(
        self,
        agent_name: str,
        usage: RunUsage,
        model_name: str,
        provider_spec: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        cost = calc_cost(usage, model_name, provider_spec)

        if agent_name not in self.by_agent:
            self.by_agent[agent_name] = AgentUsage(
                model_name=model_name, provider_spec=provider_spec
            )

        agent = self.by_agent[agent_name]
        agent.usage += usage
        agent.duration_seconds += duration_seconds
        agent.cost_usd += cost

        # Log per-step with cache rate (f-string avoids Rich handler % formatting issues)
        logger.debug(
            f"{agent_name}: {_fmt_tokens(usage.input_tokens)} in / "
            f"{_fmt_tokens(usage.cache_read_tokens)} cached ({_cache_rate(usage)} hit) / "
            f"{_fmt_tokens(usage.output_tokens)} out | ${cost:.4f} | {duration_seconds:.1f}s"
        )

    @property
    def total_cost_usd(self) -> float:
        return sum(a.cost_usd for a in self.by_agent.values())

    @property
    def total_tokens(self) -> int:
        total = RunUsage()
        for a in self.by_agent.values():
            total += a.usage
        return total.total_tokens

    def format_usage(self, agent_name: str) -> str:
        """Format: '45k in / 32k cached (71% hit) / 2.1k out | $0.05 | 28.3s'"""
        agent = self.by_agent.get(agent_name)
        if not agent:
            return ""
        u = agent.usage
        return (
            f"{_fmt_tokens(u.input_tokens)} in / "
            f"{_fmt_tokens(u.cache_read_tokens)} cached ({_cache_rate(u)} hit) / "
            f"{_fmt_tokens(u.output_tokens)} out | "
            f"${agent.cost_usd:.2f} | "
            f"{agent.duration_seconds:.1f}s"
        )

    def get_usage_by_model(self) -> dict[str, dict[str, Any]]:
        by_model: dict[str, dict[str, Any]] = {}
        for agent in self.by_agent.values():
            model = agent.model_name
            if model not in by_model:
                by_model[model] = {"cost": 0.0, "input": 0, "cached": 0, "output": 0}
            by_model[model]["cost"] += agent.cost_usd
            by_model[model]["input"] += agent.usage.input_tokens
            by_model[model]["cached"] += agent.usage.cache_read_tokens
            by_model[model]["output"] += agent.usage.output_tokens
        return by_model

    def log_summary(self) -> None:
        """Log summary grouped by model with cache hit rates."""
        by_model = self.get_usage_by_model()
        for model, s in by_model.items():
            hit_rate = f"{(s['cached'] / s['input'] * 100):.0f}%" if s["input"] > 0 else "n/a"
            logger.info(
                "  %s: $%.2f | %s in / %s cached (%s hit) / %s out",
                model, s["cost"],
                _fmt_tokens(s["input"]),
                _fmt_tokens(s["cached"]),
                hit_rate,
                _fmt_tokens(s["output"]),
            )
        total = sum(s["input"] for s in by_model.values())
        total_cached = sum(s["cached"] for s in by_model.values())
        overall_hit = f"{(total_cached / total * 100):.0f}%" if total > 0 else "n/a"
        logger.info(
            "  Total: $%.2f | %s tokens | %s overall cache hit rate",
            self.total_cost_usd,
            _fmt_tokens(self.total_tokens),
            overall_hit,
        )
