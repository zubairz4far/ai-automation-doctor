from __future__ import annotations

from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

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


def _write_debug_state(page: Page) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT / "debug-failure.png"), full_page=True)
    (OUTPUT / "debug-page.html").write_text(page.content(), encoding="utf-8")
    print("Result panel text:", page.locator("#result").inner_text())


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    home = OUTPUT / "demo-home.png"
    result = OUTPUT / "demo-rate-limit.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.on("console", lambda message: print(f"browser console [{message.type}]: {message.text}"))
        page.on("pageerror", lambda error: print(f"browser page error: {error}"))

        page.goto("http://127.0.0.1:8000/demo", wait_until="networkidle")
        page.locator("#analyze").wait_for(state="visible")
        page.screenshot(path=str(home), full_page=True)

        page.locator('[data-sample="rate"]').click()
        assert page.locator("#statusCode").input_value() == "429"

        try:
            with page.expect_response(
                lambda response: response.url.endswith("/v1/demo/analyze")
                and response.request.method == "POST",
                timeout=15_000,
            ) as response_info:
                page.locator("#analyze").click()

            response = response_info.value
            print("Demo analyze status:", response.status)
            print("Demo analyze response:", response.text())
            assert response.ok, f"Demo analyze returned HTTP {response.status}"

            page.locator("#result .safe").wait_for(state="visible", timeout=10_000)
            assert "Patch preview" in page.locator("#result").inner_text()
            assert "workflow mutation: disabled" in page.locator("#result").inner_text()
            page.screenshot(path=str(result), full_page=True)
        except Exception:
            _write_debug_state(page)
            raise
        finally:
            browser.close()

    _save_showcase_gif([home, result], OUTPUT / "demo-showcase.gif")

    for debug_file in (OUTPUT / "debug-failure.png", OUTPUT / "debug-page.html"):
        if debug_file.exists():
            debug_file.unlink()


if __name__ == "__main__":
    main()
