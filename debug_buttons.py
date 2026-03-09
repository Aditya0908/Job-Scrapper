import asyncio
import sys
from utils.stealth import StealthBrowser
from auto_apply.html_cleaner import detect_navigation_buttons

async def main():
    url = "https://www.linkedin.com/jobs/view/4380681259/"
    browser = StealthBrowser(headless=False)
    await browser.start()
    ctx = await browser.new_context("linkedin")
    page = await browser.new_page(ctx)
    
    print("Navigating to job...")
    await page.goto(url)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(4)
    
    print("Clicking Easy Apply...")
    btn = page.locator(".jobs-apply-button")
    if await btn.count() > 0:
        await btn.first.click()
    else:
        print("No Easy Apply button found")
        await browser.stop()
        return

    await asyncio.sleep(4)
    
    print("Dumping modal HTML for buttons...")
    html = await page.content()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    
    buttons = soup.find_all(["button", "input"])
    print(f"Found {len(buttons)} buttons on page.")
    for b in buttons:
        cls = b.get('class', [])
        if "artdeco-button" in cls or b.name == "input":
            print(f"---\ntype: {b.get('type')}\ntext: {b.get_text(strip=True)}\naria-label: {b.get('aria-label')}\nclass: {cls}\n")
            
    print("\nTesting detect_navigation_buttons:")
    res = detect_navigation_buttons(html)
    print(res)
    
    await browser.stop()

asyncio.run(main())
