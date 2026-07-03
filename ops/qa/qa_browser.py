"""Playwright QA — captures every BusTrain view after a code change.
Grants geolocation (Beppu Station) so Nearby/Compare render real content."""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent.parent / "designs" / "qa"
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:3021/"
BEPPU = {"latitude": 33.2796, "longitude": 131.5000}


async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 420, "height": 900}, device_scale_factor=2,
            geolocation=BEPPU, permissions=["geolocation", "notifications"],
            timezone_id="Asia/Tokyo", locale="ja-JP",
        )
        page = await ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "01-home.png")

        # search tab = journey planner (From: my location -> To: a place)
        await page.click('nav a[data-tab="search"]')
        await page.wait_for_timeout(1500)
        await page.fill("#j-to-input", "大分駅")
        await page.wait_for_timeout(600)
        await page.click("#j-sugg .sg >> nth=0")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "02-search.png")

        # stop detail via nearby list
        await page.click('nav a[data-tab="nearby"]')
        await page.click("#nearby-btn")
        await page.wait_for_timeout(1200)
        await page.click("#nearby-results .row >> nth=0")
        await page.wait_for_timeout(900)
        await page.screenshot(path=OUT / "03-detail.png")
        await page.click("#detail-close")

        await page.click('nav a[data-tab="nearby"]')
        await page.click("#nearby-btn")
        await page.wait_for_timeout(1200)
        await page.screenshot(path=OUT / "04-nearby.png")

        await page.click('nav a[data-tab="compare"]')
        await page.click("#vs-locate")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "05-compare.png")

        # destination verdict + account + trip logging
        await page.fill("#vs-to-input", "大分駅")
        await page.wait_for_timeout(700)
        if await page.locator("#vs-sugg .sg").count():
            await page.locator("#vs-sugg .sg").nth(0).dispatch_event("mousedown")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=OUT / "08-compare-verdict.png")

        await page.click('nav a[data-tab="reminders"]')
        await page.wait_for_timeout(400)
        import random
        uname = f"qa_{random.randint(1000, 99999)}"
        await page.fill("#acct-user", uname)
        await page.fill("#acct-pass", "test-password-1")
        await page.click("#acct-register")
        await page.wait_for_timeout(900)
        await page.screenshot(path=OUT / "09-account.png")

        await page.click('nav a[data-tab="compare"]')
        await page.wait_for_timeout(1000)
        take = page.locator("#vs-verdict [data-take]")
        if await take.count():
            await take.first.click()
            await page.wait_for_timeout(800)
        await page.click('nav a[data-tab="reminders"]')
        await page.wait_for_timeout(800)
        await page.screenshot(path=OUT / "10-history.png")

        # set a reminder: open home, click first bell
        await page.click('nav a[data-tab="compare"]')
        await page.wait_for_timeout(800)
        bells = page.locator(".bell")
        if await bells.count():
            await bells.first.click()
            await page.wait_for_timeout(500)
        await page.click('nav a[data-tab="reminders"]')
        await page.wait_for_timeout(500)
        await page.screenshot(path=OUT / "06-reminders.png")

        await page.click('nav a[data-tab="compare"]')
        await page.wait_for_timeout(800)
        await page.screenshot(path=OUT / "07-home-with-reminder.png")

        await browser.close()
    print("captured 7 views ->", OUT)
    if errors:
        print("CONSOLE ERRORS:")
        for e in errors[:20]:
            print(" -", e)
        sys.exit(1)
    print("no console errors")


asyncio.run(main())
