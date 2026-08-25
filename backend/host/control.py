"""Structured PC-control intents: the safe whitelist and their implementations.

Mira proposes control via [[control|action|target|reason]]. Unlike the free
[[run|reason|command]] marker (arbitrary approved PowerShell), control intents
are a *whitelist*: the action is one of a fixed set, and each action maps to a
pinned, safe PowerShell implementation on the host. The model can never inject
a command — it can only name a whitelisted action and, for ``open``, a validated
app name. Everything still sits behind the same approval gate as host_command.

This module is the single source of truth. The backend imports it to validate
proposals; the host agent imports it to perform them.
"""

import re
import subprocess
from pathlib import Path

# The actions Mira may propose. Add a new action only with its safe
# implementation below AND its payload shape handled in the backend.
CONTROL_ACTIONS = frozenset(
    {
        "open",  # launch an app on the voice's machine (target = app name/path)
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
    }
)

# A target for `open` is an app name or path: letters, digits, spaces, dots,
# dashes, underscores, and path separators. No shell metacharacters, no pipes,
# no argument passing — just the thing to launch.
_OPEN_TARGET_RE = re.compile(r"^[A-Za-z0-9 _.\-\\/:]{1,120}$")
_MAX_TARGET = 120

# Volume/brightness/media steps.
_VOLUME_STEP_KEYS = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD, "unmute": 0xAD}
_MEDIA_KEYS = {
    "media_play_pause": 0xB3,
    "media_next": 0xB0,
    "media_prev": 0xB1,
}

_SCREENSHOTS_DIR = Path(__file__).resolve().parents[1] / "data" / "host" / "screenshots"


class ControlError(Exception):
    """Raised when an action is not whitelisted or a target is unsafe."""


def validate_control(action: str, target: str) -> None:
    """Validate an action + target against the whitelist. Raises ControlError."""
    action = action.strip().lower()
    if action not in CONTROL_ACTIONS:
        raise ControlError(
            f"unknown control action {action!r} (allowed: {', '.join(sorted(CONTROL_ACTIONS))})"
        )
    target = target.strip()
    if action == "open":
        if not target:
            raise ControlError("open needs an app name or path")
        if len(target) > _MAX_TARGET or not _OPEN_TARGET_RE.match(target):
            raise ControlError(f"open target is not a plain app name/path: {target!r}")
    else:
        if target:
            raise ControlError(f"{action} takes no target (got {target!r})")


def _send_key(vk: int) -> None:
    """Press and release a virtual key via keybd_event (no window focus needed)."""
    ps = (
        "Add-Type -Namespace Win32Input -Name Key -MemberDefinition "
        "'[DllImport(\"user32.dll\")] public static extern void keybd_event("
        "byte bVk, byte bScan, uint dwFlags, System.UIntPtr dwExtraInfo);'; "
        f"[Win32Input.Key]::keybd_event({vk}, 0, 0, [UIntPtr]::Zero); "
        f"[Win32Input.Key]::keybd_event({vk}, 0, 2, [UIntPtr]::Zero)"
    )
    _ps(ps)


def _ps(script: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    combined = f"{proc.stdout}{proc.stderr}".strip()
    return proc.returncode, combined


def run_control(action: str, target: str = "") -> str:
    """Perform a whitelisted control action on this machine.

    Returns a short human-readable note for the transcript. The implementation
    of each action is pinned here — a control proposal can never run arbitrary
    command text.
    """
    action = action.strip().lower()
    target = target.strip()
    validate_control(action, target)

    if action == "open":
        _, out = _ps(f"Start-Process -FilePath '{target}'; if ($?) {{ 'launched' }}")
        return f"opened {target}" if not out or "launched" in out else f"open failed: {out}"
    if action in _VOLUME_STEP_KEYS:
        _send_key(_VOLUME_STEP_KEYS[action])
        return "mute toggled" if action in ("mute", "unmute") else f"{action}"
    if action in _MEDIA_KEYS:
        _send_key(_MEDIA_KEYS[action])
        return action.replace("_", " ")
    if action in ("brightness_up", "brightness_down"):
        return _brightness_step(action == "brightness_up")
    if action == "screenshot":
        return _screenshot()
    if action == "lock":
        _, out = _ps("rundll32.exe user32.dll,LockWorkStation")
        return "lock requested" if not out else f"lock failed: {out}"
    raise ControlError(f"no implementation for {action!r}")


def _brightness_step(up: bool) -> str:
    """Best-effort screen brightness step via WMI. Laptops support it; desktops
    typically have no brightness control and return nothing, which we say so."""
    ps = (
        "try { $m = Get-WmiObject -Namespace root\\wmi -Class WmiMonitorBrightness; "
        "$cur = $m.CurrentBrightness; "
        "$target = [Math]::Max(0, [Math]::Min(100, $cur $sign 10)); "
        "(Get-WmiObject -Namespace root\\wmi -Class WmiMonitorBrightnessMethods) | "
        "ForEach-Object { $_.WmiSetBrightness(1, $target) }; "
        "Write-Output \"$cur->$target\" } catch { Write-Output \"no brightness control\" }"
    )
    code, out = _ps(ps)
    if "no brightness control" in out or "->" not in out:
        return "brightness: no control available"
    return f"brightness {out.strip()}"


def _screenshot() -> str:
    """Capture the primary screen to data/host/screenshots and return the path."""
    from datetime import datetime

    _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCREENSHOTS_DIR / f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        f"$bmp.Save('{path}'); "
        "Write-Output 'saved'"
    )
    code, out = _ps(ps)
    if out.strip() == "saved" and path.exists():
        return f"screenshot saved to {path}"
    return f"screenshot failed: {out or f'exit {code}'}"