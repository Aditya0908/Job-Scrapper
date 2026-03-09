import asyncio
from utils.stealth import StealthBrowser

async def main():
    browser = StealthBrowser(headless=True)
    await browser.start()
    ctx = await browser.new_context("linkedin")
    page = await browser.new_page(ctx)
    
    await page.goto("https://www.linkedin.com/jobs/view/4380681259/")
    await asyncio.sleep(4)
    
    # 1. Click Easy Apply
    await page.locator(".jobs-apply-button").first.click()
    await asyncio.sleep(4)
    
    # 2. Click Next on Page 1
    next_btn = page.locator("button[aria-label='Continue to next step']").first
    if await next_btn.count() > 0:
        await next_btn.click()
        await asyncio.sleep(4)
    else:
        print("Could not find Next on page 1")
        return
        
    # 3. Dump footer on Page 2
    footer = page.locator("footer, .jobs-easy-apply-modal__footer, .artdeco-modal__actionbar")
    if await footer.count() > 0:
        html = await footer.first.evaluate('el => el.outerHTML')
        print("FOOTER HTML:", html)
    else:
        print("No modal footer found!")
        
    await browser.stop()

asyncio.run(main())
