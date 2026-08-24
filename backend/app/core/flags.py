"""Experimental feature flags. Every capability that could harm someone or
the system if deployed too early is gated behind a flag. Default: OFF.
The founder turns them on when ready."""

import os


def _is_truthy(val: str) -> bool:
    return val.lower() in ("1", "true", "yes", "on")


def _is_falsy(val: str) -> bool:
    return val.lower() in ("0", "false", "no", "off", "")


# --- Phase 4 scope flags ---

def host_commands_enabled() -> bool:
    """Mira executing shell commands on the host machine. OFF by default
    until the permission wall and audit trail are proven."""
    val = os.environ.get("MIRA_EXPERIMENTAL_HOST_COMMANDS", "0")
    return _is_truthy(val)


def self_edit_enabled() -> bool:
    """Mira writing her own code files. OFF by default — the approve gate
    must be proven before any self-modification is allowed."""
    val = os.environ.get("MIRA_EXPERIMENTAL_SELF_EDIT", "0")
    return _is_truthy(val)


def x_posting_enabled() -> bool:
    """Mira posting to X/Twitter. OFF by default — identity and rate limits
    must be proven before public-facing writes."""
    val = os.environ.get("MIRA_EXPERIMENTAL_X_POSTING", "0")
    return _is_truthy(val)


def video_watching_enabled() -> bool:
    """Mira watching/processing video content. OFF by default — resource
    usage on low-end devices is unbounded."""
    val = os.environ.get("MIRA_EXPERIMENTAL_VIDEO", "0")
    return _is_truthy(val)


def research_enabled() -> bool:
    """Mira's literature search. ON by default (read-only, fully recorded)."""
    val = os.environ.get("MIRA_EXPERIMENTAL_RESEARCH", "1")
    return _is_truthy(val)


# --- Age gate ---

MINIMUM_AGE = 16

def age_gate_required() -> bool:
    """When on, new users must confirm they are at least MINIMUM_AGE before
    their first conversation. The founder is exempt."""
    val = os.environ.get("MIRA_AGE_GATE", "1")
    return _is_truthy(val)


# --- Data disclosures ---

PRIVACY_DISCLOSURE_URL = os.environ.get("MIRA_PRIVACY_URL", "")
TERMS_DISCLOSURE_URL = os.environ.get("MIRA_TERMS_URL", "")
