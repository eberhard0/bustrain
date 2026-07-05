"""Full QA sweep — every view/state on desktop Chromium + iPhone WebKit.
Writes to designs/qa-full/<engine>-NN-name.png and reports console errors
and failed same-origin requests per engine."""
import asyncio
import random
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent.parent / "designs" / "qa-full"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:3021/"
BEPPU = {"latitude": 33.2796, "longitude": 131.5000}


async def flow(page, ctx, tag, shot):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    bad = []
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}")
            if r.status >= 400 and "127.0.0.1" in r.url else None)

    # 01 fresh home (empty state): wipe storage first
    await page.goto(URL, wait_until="networkidle")
    await page.evaluate("localStorage.clear(); localStorage.setItem('bt_city','beppu_oita')")
    await page.reload(wait_until="networkidle")
    await page.wait_for_timeout(1800)
    await shot("01-home-default")

    # 02 journey empty (no destination yet)
    await page.click('nav a[data-tab="search"]')
    await page.wait_for_timeout(2500)
    await shot("02-journey-empty")

    # 03 suggestions dropdown
    await page.fill("#j-to-input", "kannawa")
    await page.wait_for_timeout(700)
    await shot("03-journey-suggest")

    # 04 journey result with maps
    texts = await page.locator("#j-sugg .sg").all_inner_texts()
    idx = next((i for i, t in enumerate(texts) if "鉄輪温泉" in t), 0)
    await page.locator("#j-sugg .sg").nth(idx).dispatch_event("mousedown")
    await page.wait_for_timeout(5000)
    await shot("04-journey-result")
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2500)
    await shot("05-journey-result-bottom")

    # 06 nearby
    await page.click('nav a[data-tab="nearby"]')
    await page.click("#nearby-btn")
    await page.wait_for_timeout(1500)
    await shot("06-nearby")

    # 07 stop detail (bus, scrolled to "now")
    await page.click("#nearby-results .row >> nth=1")
    await page.wait_for_timeout(1200)
    await shot("07-detail-bus")
    await page.click("#detail-close")

    # 08 compare with verdict
    await page.click('nav a[data-tab="compare"]')
    await page.click("#vs-locate")
    await page.wait_for_timeout(2000)
    await page.fill("#vs-to-input", "oita station")
    await page.wait_for_timeout(700)
    if await page.locator("#vs-sugg .sg").count():
        await page.locator("#vs-sugg .sg").nth(0).dispatch_event("mousedown")
        await page.wait_for_timeout(1500)
    await shot("08-compare-verdict")

    # 09 you-tab logged out (form + empty reminders/history)
    await page.click('nav a[data-tab="reminders"]')
    await page.wait_for_timeout(600)
    await shot("09-you-loggedout")

    # 10 validation error message
    await page.click("#acct-register")
    await page.wait_for_timeout(300)
    await shot("10-account-validation")

    # 11 register + take a trip -> history & stats
    uname = f"qa_{tag}_{random.randint(1000, 99999)}"
    await page.fill("#acct-user", uname)
    await page.fill("#acct-pass", "test-password-1")
    await page.click("#acct-register")
    await page.wait_for_timeout(900)
    await page.click('nav a[data-tab="search"]')
    await page.wait_for_timeout(1500)
    take = page.locator("#journey [data-take]")
    if await take.count():
        await take.first.click()
        await page.wait_for_timeout(900)
    await page.click('nav a[data-tab="reminders"]')
    await page.wait_for_timeout(800)
    await shot("11-you-history")

    # 12 home with pinned stops + reminder banner
    await page.click('nav a[data-tab="compare"]')
    await page.wait_for_timeout(1200)
    await shot("12-home-after-trip")

    return errors, bad


async def flow_jakarta(page, ctx, tag, shot):
    """Jakarta parity pass: same journey, columns, detail, guide checks."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    bad = []
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}")
            if r.status >= 400 and "127.0.0.1" in r.url else None)

    await ctx.set_geolocation({"latitude": -6.1754, "longitude": 106.8272})  # Monas
    await page.goto(URL, wait_until="networkidle")
    await page.evaluate("localStorage.clear(); localStorage.setItem('bt_city','jakarta');"
                        "localStorage.setItem('bt_howto_done','1'); state.geo = null")
    await page.wait_for_timeout(1500)  # let any cached geo fix age out
    await page.reload(wait_until="networkidle")
    await page.wait_for_timeout(1800)
    await shot("20-jkt-home")

    await page.click("#vs-locate")
    await page.wait_for_timeout(2500)
    await page.fill("#vs-to-input", "kota tua")
    await page.wait_for_timeout(900)
    if await page.locator("#vs-sugg .sg").count():
        await page.locator("#vs-sugg .sg").nth(0).dispatch_event("mousedown")
        await page.wait_for_timeout(4000)
    await shot("21-jkt-verdict")

    # tap a departure row -> walking guide (direction clarity)
    rows = page.locator("#vs-bus-list .vdep[data-guide]")
    if await rows.count():
        await rows.first.click()
        await page.wait_for_timeout(4000)
        await shot("22-jkt-guide")
        await page.click("#guide-close")

    # journey planner
    await page.click('nav a[data-tab="search"]')
    await page.wait_for_timeout(2000)
    await page.fill("#j-to-input", "monas")
    await page.wait_for_timeout(900)
    if await page.locator("#j-sugg .sg").count():
        await page.locator("#j-sugg .sg").nth(0).dispatch_event("mousedown")
        await page.wait_for_timeout(4500)
    await shot("23-jkt-journey")

    # stop detail with frequency rows
    await page.click('nav a[data-tab="nearby"]')
    await page.click("#nearby-btn")
    await page.wait_for_timeout(1500)
    await page.click("#nearby-results .row >> nth=0")
    await page.wait_for_timeout(1200)
    await shot("24-jkt-detail")
    await page.click("#detail-close")
    return errors, bad


async def flow_tokyo(page, ctx, tag, shot):
    """Tokyo parity pass: real-GTFS rail city with generated Metro layer."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    bad = []
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}")
            if r.status >= 400 and "127.0.0.1" in r.url else None)
    await ctx.set_geolocation({"latitude": 35.6896, "longitude": 139.7006})  # Shinjuku
    await page.goto(URL, wait_until="networkidle")
    await page.evaluate("localStorage.clear(); localStorage.setItem('bt_city','tokyo');"
                        "localStorage.setItem('bt_howto_done','1'); state.geo = null")
    await page.wait_for_timeout(1500)
    await page.reload(wait_until="networkidle")
    await page.wait_for_timeout(2000)
    await shot("30-tokyo-home")
    await page.click("#vs-locate")
    await page.wait_for_timeout(3000)
    await page.fill("#vs-to-input", "tokyo tower")
    await page.wait_for_timeout(1000)
    if await page.locator("#vs-sugg .sg").count():
        texts = await page.locator("#vs-sugg .sg").all_inner_texts()
        idx = next((i for i, t in enumerate(texts) if "東京タワー" in t), 0)
        await page.locator("#vs-sugg .sg").nth(idx).dispatch_event("mousedown")
        await page.wait_for_timeout(5500)
    await shot("31-tokyo-verdict")
    await page.click('nav a[data-tab="nearby"]')
    await page.click("#nearby-btn")
    await page.wait_for_timeout(1500)
    if await page.locator("#nearby-results .row").count():
        await page.click("#nearby-results .row >> nth=0")
        await page.wait_for_timeout(1200)
        await shot("32-tokyo-detail")
        await page.click("#detail-close")
    return errors, bad


async def main():
    async with async_playwright() as p:
        report = {}
        for engine, launcher, ctx_args in [
            ("desktop", p.chromium,
             {"viewport": {"width": 1280, "height": 900}, "device_scale_factor": 2}),
            ("iphone", p.webkit, {**p.devices["iPhone 13"]}),
        ]:
            browser = await launcher.launch(headless=True)
            ctx = await browser.new_context(
                **ctx_args, geolocation=BEPPU, permissions=["geolocation", "notifications"],
                timezone_id="Asia/Tokyo", locale="ja-JP")
            page = await ctx.new_page()

            async def shot(name, page=page, engine=engine):
                await page.screenshot(path=OUT / f"{engine}-{name}.png")

            e1, b1 = await flow(page, ctx, engine, shot)
            e2, b2 = await flow_jakarta(page, ctx, engine, shot)
            e3, b3 = await flow_tokyo(page, ctx, engine, shot)
            report[engine] = (e1 + e2 + e3, b1 + b2 + b3)
            await browser.close()

        ok = True
        for engine, (errors, bad) in report.items():
            print(f"== {engine}: {len(errors)} console errors, {len(bad)} failed requests")
            for e in errors[:8]:
                print("   ERR", e[:200]); ok = False
            for b in [x for x in bad if "/api/history" not in x][:8]:
                print("   REQ", b); ok = False
        print("captured ->", OUT)
        sys.exit(0 if ok else 1)


asyncio.run(main())
