const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    
    console.log('Switching to Design tab...');
    await page.click('button:has-text("视觉实验室")');
    await page.waitForTimeout(4000);
    
    // 取一张图
    await page.screenshot({ path: path.join(__dirname, 'final_design_check.png') });
    console.log('Screenshot saved.');

  } catch (e) {
    console.error('Test failed:', e.message);
  } finally {
    await browser.close();
  }
})();
