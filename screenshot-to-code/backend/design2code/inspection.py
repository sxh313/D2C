"""Limited browser checks; these do not certify visual fidelity or behavior."""

from typing import Any

from playwright.async_api import async_playwright

from design2code.runner import _child_env, preview_url
from design2code.settings import get_settings


async def inspect_candidate(run_id: str, candidate: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        url = preview_url(run_id, settings, candidate)
        async with async_playwright() as playwright:
            browser_env: dict[str, str | float | bool] = dict(_child_env())
            browser = await playwright.chromium.launch(headless=True, env=browser_env)
            try:
                observations: list[str] = []
                failed = False
                for name, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
                    page = await browser.new_page(viewport={"width": width, "height": height})
                    page_errors: list[str] = []
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.on("console", lambda message: page_errors.append(message.text) if message.type == "error" else None)
                    await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url) else route.abort())
                    response = await page.goto(url, wait_until="load", timeout=15000)
                    if response is None or not response.ok:
                        raise RuntimeError("Preview returned an unsuccessful HTTP response")
                    overflow = await page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
                    target = settings.runtime_dir / "runs" / run_id / candidate / f"inspection-{name}.png"
                    await page.screenshot(path=str(target), full_page=True, timeout=15000)
                    observations.append(f"{name}: {'水平溢出' if overflow else '无水平溢出'}" + ("，页面脚本或资源报错" if page_errors else ""))
                    failed = failed or bool(overflow) or bool(page_errors)
                    await page.close()
                return {"id": "viewport", "status": "FAIL" if failed else "PASS", "message": "；".join(observations) + "。已保存截图；视觉还原和功能仍需人工检查。"}
            finally:
                await browser.close()
    except Exception:
        return {"id": "viewport", "status": "NOT_RUN", "message": "浏览器截图或视口检查未能运行；请检查 Chromium 安装。"}


async def inspect_interactions(run_id: str, candidate: str) -> dict[str, Any]:
    """Run a small local smoke check, without claiming business behavior is correct."""
    settings = get_settings()
    try:
        url = preview_url(run_id, settings, candidate)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, env=dict(_child_env()))
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                await page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url) else route.abort())
                response = await page.goto(url, wait_until="load", timeout=15000)
                if response is None or not response.ok:
                    raise RuntimeError("Preview returned an unsuccessful HTTP response")
                controls = await page.locator("button, input, select, textarea").count()
                exercised = 0
                for index in range(controls):
                    locator = page.locator("button, input, select, textarea").nth(index)
                    if not await locator.is_visible() or not await locator.is_enabled():
                        continue
                    tag = await locator.evaluate("element => element.tagName.toLowerCase()")
                    acted = False
                    if tag == "button":
                        await locator.click(timeout=3000)
                        acted = True
                    elif tag in {"input", "textarea"}:
                        input_type = await locator.get_attribute("type")
                        if input_type not in {"checkbox", "radio", "file", "submit", "button", "hidden"}:
                            await locator.fill("smoke")
                            acted = True
                    elif tag == "select":
                        options = await locator.locator("option").all()
                        if len(options) > 1:
                            value = await options[1].get_attribute("value")
                            if value is not None:
                                await locator.select_option(value)
                                acted = True
                    if acted:
                        exercised += 1
                await page.close()
                if errors:
                    return {"id": "interaction_smoke", "status": "FAIL", "message": "交互冒烟检查发现页面错误：" + "；".join(errors[:3])}
                if not exercised:
                    return {"id": "interaction_smoke", "status": "NOT_RUN", "message": "没有可操作的控件，未执行交互冒烟检查。"}
                return {"id": "interaction_smoke", "status": "PASS", "message": f"交互冒烟检查通过，已尝试 {exercised} 个控件；不代表业务逻辑验收通过。"}
            finally:
                await browser.close()
    except Exception:
        return {"id": "interaction_smoke", "status": "NOT_RUN", "message": "交互冒烟检查未能运行；请人工检查页面。"}
