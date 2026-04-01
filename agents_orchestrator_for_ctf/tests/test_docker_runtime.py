from __future__ import annotations

from ctf_swarm.docker_runtime import parse_ctf_install_command


def test_parse_ctf_install_command_accepts_simple_standalone_install() -> None:
    command = parse_ctf_install_command('ctf-install pip "requests==2.32.3"')

    assert command is not None
    assert command.manager == "pip"
    assert command.packages == ("requests==2.32.3",)


def test_parse_ctf_install_command_rejects_shell_chaining() -> None:
    assert parse_ctf_install_command("ctf-install pip requests && python -c 'print(1)'") is None
    assert parse_ctf_install_command("bash -lc 'ctf-install pip requests'") is None
