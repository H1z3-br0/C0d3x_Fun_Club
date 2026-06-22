from backend.loop_detect import LoopDetector


def test_distinct_calls_never_flag():
    d = LoopDetector()
    for i in range(10):
        assert d.check("bash", {"command": f"echo {i}"}) is None


def test_repeated_calls_warn_then_break():
    d = LoopDetector(warn_threshold=3, break_threshold=5)
    args = {"command": "ls"}
    results = [d.check("bash", args) for _ in range(5)]
    assert results[2] == "warn"  # 3rd identical call
    assert results[4] == "break"  # 5th identical call


def test_reset_clears_history():
    d = LoopDetector(break_threshold=2)
    d.check("bash", {"command": "x"})
    d.reset()
    assert d.check("bash", {"command": "x"}) is None
