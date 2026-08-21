from __future__ import annotations

from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

OUTPUT = Path("docs/assets/demo")
VIEWPORT = {"width": 1440, "height": 1050}


def _save_showcase_gif(paths: list[Path], output: Path) -> None:
    frames = [Image.open(path).convert("RGB") for path in paths]
    resized = []
    for frame in frames:
        width = 1200
        height = round(frame.height * (width / frame.width))
        resized.append(frame.resize((width, height)))
    resized[0].save(
        output,
        save_all=True,
        append_images=resized[1:],
        duration=[1100, 1900],
        loop=0,
        optimize=True,
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    home = OUTPUT / "demo-home.png"
    result = OUTPUT / "demo-rate-limit.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto("http://127.0.0.1:8000/demo", wait_until="networkidle")
        page.screenshot(path=str(home), full_page=True)

        page.get_by_role("button", name="Rate limit").click()
        page.get_by_role("button", name="Analyze safely").click()
        page.wait_for_selector("text=Patch preview")
        page.screenshot(path=str(result), full_page=True)
        browser.close()

    _save_showcase_gif([home, result], OUTPUT / "demo-showcase.gif")


if __name__ == "__main__":
    main()
