"""Limited browser checks; these do not certify visual fidelity or behavior."""

from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright, expect

from design2code.runner import _child_env, preview_url
from design2code.settings import get_settings


async def _watch_resources(page: Any, url: str, problems: set[str]) -> None:
    """Record failed local responses and requests blocked by preview isolation."""
    page.on("response", lambda response: problems.add("页面资源返回错误状态") if response.status >= 400 else None)

    async def route_request(route: Any) -> None:
        if route.request.url.startswith(url):
            await route.continue_()
        else:
            problems.add("页面请求了被阻止的外部资源")
            await route.abort()

    await page.route("**/*", route_request)


async def inspect_search(run_id: str, candidate: str, rule: dict[str, str]) -> dict[str, Any]:
    """Verify the user's declared two-example search behavior, not arbitrary semantics."""
    stage = "加载页面"
    try:
        url = preview_url(run_id, get_settings(), candidate)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, env=dict(_child_env()))
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                errors: set[str] = set()
                page.on("pageerror", lambda _error: errors.add("页面脚本报错"))
                page.on("console", lambda message: errors.add("页面或资源报错") if message.type == "error" else None)
                await _watch_resources(page, url, errors)
                response = await page.goto(url, wait_until="load", timeout=15000)
                if response is None:
                    raise RuntimeError("Preview did not respond")
                if not response.ok:
                    return {"id": "spec_search_01", "status": "FAIL", "message": "搜索验收失败：预览页面返回错误状态。"}
                field = page.get_by_placeholder(rule["placeholder"], exact=True)
                shown = page.get_by_text(rule["visible_text"], exact=True)
                hidden = page.get_by_text(rule["hidden_text"], exact=True)
                stage = "查找唯一搜索框"
                await expect(field).to_have_count(1, timeout=3000)
                stage = "查找初始保留示例"
                await expect(shown).to_have_count(1, timeout=3000)
                stage = "查找初始隐藏示例"
                await expect(hidden).to_have_count(1, timeout=3000)
                stage = "检查初始显示状态"
                await expect(field).to_be_visible(timeout=3000)
                await expect(shown).to_be_visible(timeout=3000)
                await expect(hidden).to_be_visible(timeout=3000)
                stage = "输入搜索词"
                await field.fill(rule["query"], timeout=3000)
                stage = "检查搜索后保留示例"
                await expect(shown).to_be_visible(timeout=3000)
                stage = "检查搜索后隐藏示例"
                await expect(hidden).to_be_hidden(timeout=3000)
                if errors:
                    return {"id": "spec_search_01", "status": "FAIL", "message": "搜索验收发现页面或资源错误。"}
                return {"id": "spec_search_01", "status": "PASS", "message": "搜索验收通过：输入指定内容后，保留和隐藏的示例均符合预先填写的规则；仅覆盖这一组示例。"}
            finally:
                await browser.close()
    except (PlaywrightTimeoutError, AssertionError):
        return {"id": "spec_search_01", "status": "FAIL", "message": f"搜索验收失败：{stage}未符合规则。请检查输入框提示文字、示例是否唯一及搜索后的显示状态。"}
    except Exception:
        return {"id": "spec_search_01", "status": "NOT_RUN", "message": "搜索验收未能运行；请检查本机浏览器和预览。"}


async def capture_reference_viewport(run_id: str, candidate: str, width: int, height: int) -> tuple[bytes, list[str]]:
    """Capture only the initial viewport, using the reference image dimensions."""
    settings = get_settings()
    url = preview_url(run_id, settings, candidate)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, env=dict(_child_env()))
        try:
            page = await browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            problems: set[str] = set()
            page.on("pageerror", lambda _error: problems.add("页面存在脚本错误。"))
            page.on("console", lambda message: problems.add("页面或资源报告错误。") if message.type == "error" else None)
            page.on("response", lambda response: problems.add("页面资源返回错误状态。") if response.status >= 400 else None)
            async def route_request(route: Any) -> None:
                if route.request.url.startswith(url):
                    await route.continue_()
                else:
                    problems.add("页面请求了被阻止的外部资源。")
                    await route.abort()
            await page.route("**/*", route_request)
            response = await page.goto(url, wait_until="load", timeout=15000)
            if response is None or not response.ok:
                raise RuntimeError("Preview returned an unsuccessful HTTP response")
            overflow = await page.evaluate("() => ({ horizontal: document.documentElement.scrollWidth > innerWidth + 1, vertical: document.documentElement.scrollHeight > innerHeight + 1 })")
            if overflow["horizontal"]:
                problems.add("页面存在水平溢出，视口外内容未纳入比较。")
            if overflow["vertical"]:
                problems.add("页面存在视口下方内容，未纳入比较。")
            screenshot = await page.screenshot(full_page=False, timeout=15000)
            return screenshot, sorted(problems)
        finally:
            await browser.close()


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
                screenshots = 0
                for name, width, height in (("desktop", 1440, 900), ("tablet", 768, 1024), ("mobile", 390, 844)):
                    page = await browser.new_page(viewport={"width": width, "height": height})
                    page_errors: list[str] = []
                    resource_errors: set[str] = set()
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.on("console", lambda message: page_errors.append(message.text) if message.type == "error" else None)
                    await _watch_resources(page, url, resource_errors)
                    response = await page.goto(url, wait_until="load", timeout=15000)
                    if response is None:
                        raise RuntimeError("Preview did not return a response")
                    if not response.ok:
                        observations.append(f"{name}: 预览页面返回错误状态")
                        failed = True
                        await page.close()
                        continue
                    overflow = await page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 1")
                    target = settings.runtime_dir / "runs" / run_id / candidate / f"inspection-{name}.png"
                    await page.screenshot(path=str(target), full_page=True, timeout=15000)
                    screenshots += 1
                    observations.append(f"{name}: {'水平溢出' if overflow else '无水平溢出'}" + ("，页面脚本或资源报错" if page_errors else "") + ("，" + "、".join(sorted(resource_errors)) if resource_errors else ""))
                    failed = failed or bool(overflow) or bool(page_errors) or bool(resource_errors)
                    await page.close()
                return {"id": "viewport", "status": "FAIL" if failed else "PASS", "message": "；".join(observations) + f"。已保存 {screenshots} 张视口截图；视觉还原和功能仍需人工检查。"}
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
                resource_errors: set[str] = set()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                await _watch_resources(page, url, resource_errors)
                response = await page.goto(url, wait_until="load", timeout=15000)
                if response is None:
                    raise RuntimeError("Preview did not return a response")
                if not response.ok:
                    return {"id": "interaction_smoke", "status": "FAIL", "message": "预览页面返回错误状态，无法执行交互冒烟检查。"}
                controls = await page.locator("button, input, select, textarea").count()
                exercised = 0
                incomplete = 0
                for index in range(min(controls, 30)):
                    # Each action starts from the same state: a dialog or search
                    # from an earlier action must not hide subsequent controls.
                    if index:
                        response = await page.goto(url, wait_until="load", timeout=15000)
                        if response is None:
                            raise RuntimeError("Preview did not return a response")
                        if not response.ok:
                            return {"id": "interaction_smoke", "status": "FAIL", "message": "预览页面返回错误状态，交互冒烟检查中断。"}
                    locator = page.locator("button, input, select, textarea").nth(index)
                    try:
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
                                await locator.fill("smoke", timeout=3000)
                                acted = True
                        elif tag == "select":
                            options = await locator.locator("option").all()
                            if len(options) > 1:
                                value = await options[1].get_attribute("value")
                                if value is not None:
                                    await locator.select_option(value, timeout=3000)
                                    acted = True
                        if acted:
                            exercised += 1
                    except Exception:
                        incomplete += 1
                await page.close()
                if resource_errors:
                    return {"id": "interaction_smoke", "status": "FAIL", "message": "交互冒烟检查发现资源问题：" + "；".join(sorted(resource_errors)) + "。"}
                if errors:
                    return {"id": "interaction_smoke", "status": "FAIL", "message": "交互冒烟检查发现页面错误：" + "；".join(errors[:3])}
                if incomplete or controls > 30:
                    return {"id": "interaction_smoke", "status": "NOT_RUN", "message": f"交互冒烟检查不完整：已尝试 {exercised} 个控件，{incomplete} 个控件操作未完成；最多检查前 30 个控件，请人工检查。"}
                if not exercised:
                    return {"id": "interaction_smoke", "status": "NOT_RUN", "message": "没有可操作的控件，未执行交互冒烟检查。"}
                return {"id": "interaction_smoke", "status": "PASS", "message": f"交互冒烟检查通过，已尝试 {exercised} 个控件；不代表业务逻辑验收通过。"}
            finally:
                await browser.close()
    except Exception:
        return {"id": "interaction_smoke", "status": "NOT_RUN", "message": "交互冒烟检查未能运行；请人工检查页面。"}
