from app import deps


def test_verify_always_passes_when_gate_disabled() -> None:
    """Access token gate is disabled — _verify always passes."""
    deps._verify(None)
    deps._verify("")
    deps._verify("wrong")
    deps._verify("sekrit")


def test_ws_authorized_always_passes_when_gate_disabled() -> None:
    """Access token gate is disabled — ws_authorized always returns True."""
    assert deps.ws_authorized(None) is True
    assert deps.ws_authorized("") is True
    assert deps.ws_authorized("wrong") is True
    assert deps.ws_authorized("sekrit") is True
