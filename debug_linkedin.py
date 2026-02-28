"""
Debug script — dumps HTML of the first job card so we can see
the internal structure for title/company/location/link parsing.
"""
import asyncio
from pathlib import Path
from utils.stealth import StealthBrowser

URL = "https://www.linkedin.com/jobs/search/?keywords=AI+Engineer&location=India&sortBy=DD&position=1&pageNum=0"


async def main():
    browser = StealthBrowser(headless=True)
    await browser.start()
    ctx = await browser.new_context("linkedin")
    page = await browser.new_page(ctx)

    await page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    for _ in range(6):
        await page.mouse.wheel(0, 600)
        await asyncio.sleep(1)
    await asyncio.sleep(3)

    cards = await page.query_selector_all("div.job-card-container--clickable")
    print(f"Found {len(cards)} cards\n")

    if cards:
        card = cards[0]
        html = await card.inner_html()
        print("=== Card #0 inner HTML (first 5000 chars) ===")
        print(html[:5000])
        print("\n=== Card #0 inner text ===")
        txt = await card.inner_text()
        print(txt)

    await ctx.close()
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
