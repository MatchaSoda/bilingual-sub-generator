const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1920, height: 1080 });

  const logs = [];
  page.on('console', msg => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
    console.log(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', err => {
    logs.push(`[ERROR] ${err.message}`);
    console.log(`[ERROR] ${err.message}`);
  });

  console.log('Navigating to http://localhost:8501...');
  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(__dirname, 'debug_init.png') });

    console.log('Switching to Design tab...');
    const designTab = await page.locator('button:has-text("字幕设计")');
    await designTab.click();
    
    await page.waitForTimeout(5000);
    await page.screenshot({ path: path.join(__dirname, 'debug_design_tab.png') });

    fs.writeFileSync(path.join(__dirname, 'browser_full.log'), logs.join('\n'));
    console.log('Test Done.');

  } catch (e) {
    console.error('Test Failed:', e.message);
    await page.screenshot({ path: path.join(__dirname, 'debug_error.png') });
  } finally {
    await browser.close();
  }
})();
