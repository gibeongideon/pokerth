"""Render the Android launcher icons and splash screens from public/logo.svg.

Uses headless Chrome (no ImageMagick needed). Run from apps/player:
    python scripts/gen_android_assets.py
Needs: google-chrome, Python packages httpx + websockets (the platform venv has both).
"""
import asyncio
import base64
import json
import struct
import subprocess
import tempfile
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android/app/src/main/res"
LOGO = (ROOT / "public/logo.svg").read_text()
LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(LOGO.encode()).decode()
BG = "#030c08"
ICON_BG = "#0b2a1f"

DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def png_size(p: Path) -> tuple[int, int]:
    data = p.read_bytes()[16:24]
    return struct.unpack(">II", data)


def page(w: int, h: int, logo_px: int, bg: str | None, glow: bool = False) -> str:
    background = bg or "transparent"
    shadow = "filter: drop-shadow(0 0 %dpx rgba(245,196,81,.35));" % (logo_px // 6) if glow else ""
    return f"""<html><body style="margin:0;width:{w}px;height:{h}px;background:{background};
      display:flex;align-items:center;justify-content:center;overflow:hidden">
      <img src="{LOGO_URI}" style="width:{logo_px}px;height:{logo_px}px;{shadow}"></body></html>"""


async def main() -> None:
    jobs: list[tuple[Path, int, int, str]] = []
    for name, scale in DENSITIES.items():
        d = RES / f"mipmap-{name}"
        legacy = round(48 * scale)
        fg = round(108 * scale)
        # Legacy icons: the chip itself, nearly full size, transparent corners.
        jobs.append((d / "ic_launcher.png", legacy, legacy, page(legacy, legacy, round(legacy * 0.92), None)))
        jobs.append((d / "ic_launcher_round.png", legacy, legacy, page(legacy, legacy, round(legacy * 0.92), None)))
        # Adaptive foreground: keep the logo inside the 66dp safe zone of 108dp.
        jobs.append((d / "ic_launcher_foreground.png", fg, fg, page(fg, fg, round(fg * 0.58), None)))
    for splash in RES.glob("drawable*/splash.png"):
        w, h = png_size(splash)
        jobs.append((splash, w, h, page(w, h, round(min(w, h) * 0.32), BG, glow=True)))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        chrome = subprocess.Popen(
            ["google-chrome", "--headless=new", "--remote-debugging-port=9351", f"--user-data-dir={profile}",
             "--hide-scrollbars", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                try:
                    targets = httpx.get("http://127.0.0.1:9351/json").json()
                    break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            ws_url = next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"]
            async with websockets.connect(ws_url, max_size=100_000_000) as ws:
                n = 0

                async def cmd(method: str, **params: object) -> dict:
                    nonlocal n
                    n += 1
                    await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        m = json.loads(await ws.recv())
                        if m.get("id") == n:
                            return m.get("result", {})

                await cmd("Page.enable")
                await cmd("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
                for path, w, h, html in jobs:
                    await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
                    await cmd("Page.navigate", url="data:text/html;base64," + base64.b64encode(html.encode()).decode())
                    await asyncio.sleep(0.25)
                    shot = await cmd("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": w, "height": h, "scale": 1})
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(base64.b64decode(shot["data"]))
                    print(f"{path.relative_to(ROOT)}  {w}x{h}")
        finally:
            chrome.terminate()
            chrome.wait(timeout=10)

    # Adaptive icon background colour.
    (RES / "values/ic_launcher_background.xml").write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">{ICON_BG}</color>\n</resources>\n'
    )


asyncio.run(main())
