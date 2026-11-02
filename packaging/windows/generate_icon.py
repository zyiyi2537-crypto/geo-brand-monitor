"""Render the desktop SVG to PNGs and a multi-resolution Windows icon."""

from __future__ import annotations

import asyncio
from pathlib import Path
import struct

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets"
SVG = ASSETS / "geo-logo.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256)


async def generate() -> None:
    svg = SVG.read_text(encoding="utf-8")
    images: list[tuple[int, bytes]] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 512, "height": 512}, device_scale_factor=1)
        await page.set_content(svg)
        element = page.locator("svg")
        for size in SIZES:
            await element.evaluate("(svg, size) => { svg.style.width = `${size}px`; svg.style.height = `${size}px`; }", size)
            data = await element.screenshot(omit_background=True)
            images.append((size, data))
            if size in (48, 256):
                (ASSETS / f"geo-logo-{size}.png").write_bytes(data)
        await browser.close()

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = []
    for size, data in images:
        entries.append(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32,
                                   len(data), offset))
        offset += len(data)
    (ASSETS / "geo-logo.ico").write_bytes(header + b"".join(entries) + b"".join(data for _, data in images))


if __name__ == "__main__":
    asyncio.run(generate())
