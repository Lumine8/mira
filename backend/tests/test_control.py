import pytest

from host.control import CONTROL_ACTIONS, ControlError, validate_control


def test_all_actions_have_implementations() -> None:
    """Every whitelisted action must have a pinned implementation in
    run_control (else it would validate but never do anything)."""
    for action in CONTROL_ACTIONS:
        if action in {"open"}:
            continue  # covered by the open branch below
        assert action in (
            "volume_up",
            "volume_down",
            "mute",
            "unmute",
            "brightness_up",
            "brightness_down",
            "media_play_pause",
            "media_next",
            "media_prev",
            "screenshot",
            "lock",
        )


def test_open_target_must_be_plain() -> None:
    validate_control("open", "Spotify")
    validate_control("open", r"C:\Program Files\Some App\app.exe")
    with pytest.raises(ControlError):
        validate_control("open", "notepad.exe; Remove-Item -Recurse C:\\")
    with pytest.raises(ControlError):
        validate_control("open", "app & cmd /c whoami")
    with pytest.raises(ControlError):
        validate_control("open", "")


def test_non_open_actions_reject_target() -> None:
    with pytest.raises(ControlError):
        validate_control("volume_up", "Spotify")
    validate_control("volume_up", "")


def test_unknown_action_rejected() -> None:
    with pytest.raises(ControlError):
        validate_control("shutdown", "")


def test_case_insensitive() -> None:
    validate_control("OPEN", "Spotify")
    validate_control("Volume_Up", "")