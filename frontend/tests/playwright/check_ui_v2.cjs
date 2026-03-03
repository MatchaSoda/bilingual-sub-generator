const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  
  page.on('console', msg => console.log(`[BROWSER ${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => console.log(`[BROWSER ERROR] ${err.message}`));

  await page.setViewportSize({ width: 1920, height: 1080 });

  console.log('Step 1: Navigating...');
  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(__dirname, 'debug_1_home.png') });

    console.log('Step 2: Clicking Design Tab...');
    // Look for button by text
    const designBtn = page.locator('button', { hasText: '字幕设计' });
    await designBtn.click();
    
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(__dirname, 'debug_2_after_click.png') });

    console.log('Step 3: Checking for Design Panel Content...');
    const mainTitle = page.locator('h2', { hasText: '字幕大师设计' });
    if (await mainTitle.isVisible()) {
      console.log('Design Panel Title is visible!');
    } else {
      console.log('Design Panel Title NOT found.');
    }

    await page.waitForTimeout(5000);
    await page.screenshot({ path: path.join(__dirname, 'debug_3_final.png') });
    console.log('Test Finished.');

  } catch (e) {
    console.error('Test FAILED:', e.message);
    await page.screenshot({ path: path.join(__dirname, 'debug_fail.png') });
  } finally {
    await browser.close();
  }
})();
