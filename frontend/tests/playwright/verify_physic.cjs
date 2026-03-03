const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1920, height: 1080 });

  page.on('console', msg => console.log(`[BROWSER ${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => console.log(`[BROWSER ERROR] ${err.message}`));

  try {
    console.log('Connecting to server...');
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    
    console.log('Navigating to Visual Lab...');
    await page.click('button:has-text("视觉实验室")');
    
    console.log('Awaiting CORE ACTIVE status...');
    // 改为匹配新状态
    const status = await page.waitForSelector('text=CORE ACTIVE', { timeout: 20000 });
    
    if (status) {
      console.log('✅ Core Activated.');
      await page.waitForTimeout(5000);
      await page.screenshot({ path: path.join(__dirname, 'debug_physic_final.png') });
      console.log('Final screenshot saved.');
    }

  } catch (e) {
    console.error('❌ Test Failed:', e.message);
    await page.screenshot({ path: path.join(__dirname, 'debug_physic_error.png') });
  } finally {
    await browser.close();
  }
})();
