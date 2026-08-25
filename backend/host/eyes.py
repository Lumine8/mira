"""Mira's eyes: capture the screen (or a region), OCR it with Windows built-in
OCR, and post *changes* to /mira/perceive as source="market" observations.

Live-editable: just edit eyes_config.json and the script picks up the change on
its next loop — switch mode between "fullscreen" and "region" while trading.

Run:
    python -m venv .venv
    .venv\\Scripts\\pip install mss winsdk requests
    .venv\\Scripts\\python eyes.py
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import mss
import requests
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

CONFIG_PATH = Path(__file__).with_name("eyes_config.json")
DEFAULT_CONFIG = {
    "api_url": "http://localhost:8000/mira/perceive",
    "interval_seconds": 10,
    "mode": "fullscreen",
    "region": None,
    "min_change_ratio": 0.1,
    "min_change_chars": 8,
    "post_cooldown_seconds": 30,
    "api_key": None,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - keep last good config on a typo
            print(f"[eyes] config error ({exc}); using previous values")
    return cfg


def validate_config(cfg: dict) -> dict:
    mode = cfg.get("mode", "fullscreen")
    if mode not in ("fullscreen", "region"):
        mode = "fullscreen"
    region = cfg.get("region")
    if mode == "region" and isinstance(region, dict):
        try:
            region = {
                "left": int(region["left"]),
                "top": int(region["top"]),
                "width": int(region["width"]),
                "height": int(region["height"]),
            }
        except (KeyError, TypeError, ValueError):
            region = None
    cfg["mode"] = mode
    cfg["region"] = region
    cfg["interval_seconds"] = max(1, int(cfg.get("interval_seconds", 10)))
    cfg["min_change_ratio"] = float(cfg.get("min_change_ratio", 0.1))
    cfg["min_change_chars"] = int(cfg.get("min_change_chars", 8))
    cfg["post_cooldown_seconds"] = int(cfg.get("post_cooldown_seconds", 30))
    return cfg


async def capture_region_png(sct: mss.MSS, region: dict) -> bytes:
    shot = sct.grab(region)
    return bytes(mss.tools.to_png(shot.rgb, shot.size))


async def ocr_png(png_bytes: bytes) -> str:
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png_bytes)
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        engine = OcrEngine.try_create_from_language(
            OcrEngine.available_recognizer_languages.__getitem__(0)
        )
    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def diff_ratio(a: str, b: str) -> float:
    """Fraction of chars in a that are NOT in the common subsequence with b."""
    if not a or not b:
        return 1.0
    import difflib

    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return 1.0 - sm.ratio()


async def run_once(sct: mss.mss, cfg: dict, last_text: str) -> tuple[str, bool]:
    try:
        region = None
        if cfg["mode"] == "region" and cfg["region"] is not None:
            region = cfg["region"]
        else:
            region = sct.monitors[1]
        png = await capture_region_png(sct, region)
        text = await ocr_png(png)
    except Exception as exc:  # noqa: BLE001 - a bad frame must not kill the loop
        print(f"[eyes] capture/ocr error: {exc}")
        return last_text, False

    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not text:
        return last_text, False
    if text == last_text:
        return last_text, False

    change = diff_ratio(last_text, text)
    changed = change >= cfg["min_change_ratio"] or (
        last_text and abs(len(text) - len(last_text)) >= cfg["min_change_chars"]
    )
    if not changed:
        return last_text, False
    return text, True


def post_observation(cfg: dict, text: str) -> bool:
    payload = {
        "source": "market",
        "kind": "screen",
        "content": f"Screen {cfg['mode']} capture changed:\n{text[:2000]}",
    }
    headers = {}
    if cfg.get("api_key"):
        headers["X-API-Key"] = cfg["api_key"]
    try:
        resp = requests.post(cfg["api_url"], json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        print(f"[eyes] posted {len(text)} chars of change to Mira")
        return True
    except Exception as exc:  # noqa: BLE001 - network blips should not kill us
        print(f"[eyes] post failed: {exc}")
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(description="Mira's screen eyes")
    parser.add_argument("--once", action="store_true", help="capture and post one frame, then exit")
    args = parser.parse_args()

    cfg = validate_config(load_config())
    with mss.MSS() as sct:
        last_text = ""
        last_post_at = 0.0
        import time

        while True:
            cfg = validate_config(load_config())
            new_text, changed = await run_once(sct, cfg, last_text)
            if new_text != last_text:
                last_text = new_text
            now = time.monotonic()
            if changed and (now - last_post_at) >= cfg["post_cooldown_seconds"]:
                if post_observation(cfg, new_text):
                    last_post_at = now
            elif changed:
                print("[eyes] change detected, cooling down")
            if args.once:
                break
            await asyncio.sleep(cfg["interval_seconds"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
