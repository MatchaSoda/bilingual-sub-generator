const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    console.log('Clicking Library tab...');
    await page.click('button:has-text("媒体库")');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(__dirname, 'test_library_tab.png') });
    
    const hasItems = await page.locator('.grid').isVisible();
    console.log('Library items visible:', hasItems);
  } catch (e) {
    console.error('Library test failed:', e.message);
  } finally {
    await browser.close();
  }
})();
