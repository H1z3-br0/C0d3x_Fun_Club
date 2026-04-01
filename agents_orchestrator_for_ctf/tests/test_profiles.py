from __future__ import annotations

from ctf_swarm.profiles import available_profiles, normalize_profile_name


def test_available_profiles_contains_base_and_requested_profiles() -> None:
    profiles = available_profiles()

    assert "base" in profiles
    assert "web" in profiles
    assert "privesc" in profiles
    assert "reverse-mobile" in profiles
    assert "ai-ml" in profiles


def test_normalize_profile_name_defaults_to_base_for_unknown_values() -> None:
    assert normalize_profile_name(None) == "base"
    assert normalize_profile_name("") == "base"
    assert normalize_profile_name("unknown-profile") == "base"
    assert normalize_profile_name("WEB") == "web"
    assert normalize_profile_name("PRIVESC") == "privesc"
