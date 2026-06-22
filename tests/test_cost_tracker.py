from backend.cost_tracker import CostTracker, RunUsage, calc_cost


def test_known_models_priced_non_zero():
    # 1M in + 1M out. Opus = $5 + $25; gpt-5.5 uses the (estimated) fallback table.
    usage = RunUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert calc_cost(usage, "claude-opus-4-8") == 30.0
    assert calc_cost(usage, "claude-opus-4-7") == 30.0
    assert calc_cost(usage, "gpt-5.5") > 0  # regression guard for the silent-$0 bug


def test_cached_tokens_cheaper_than_uncached():
    plain = RunUsage(input_tokens=1_000_000, output_tokens=0)
    cached = RunUsage(input_tokens=1_000_000, cache_read_tokens=1_000_000, output_tokens=0)
    assert calc_cost(cached, "claude-opus-4-8") < calc_cost(plain, "claude-opus-4-8")


def test_zero_usage_is_zero_cost():
    assert calc_cost(RunUsage(), "claude-opus-4-8") == 0.0


def test_tracker_accumulates_per_agent():
    t = CostTracker()
    t.record_tokens("a/opus", "claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, provider_spec="claude")
    t.record_tokens("a/opus", "claude-opus-4-8", input_tokens=1_000_000, output_tokens=0, provider_spec="claude")
    assert t.by_agent["a/opus"].usage.input_tokens == 2_000_000
    assert t.total_cost_usd == 10.0  # 2M input @ $5/1M
