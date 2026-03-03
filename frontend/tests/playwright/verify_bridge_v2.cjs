const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  console.log('Navigating to http://localhost:8501...');
  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    
    console.log('Typing dummy URL...');
    await page.fill('input[placeholder="PASTE YOUTUBE / BILIBILI LINK"]', 'https://www.youtube.com/watch?v=verify');
    
    console.log('Clicking Engage Engine button...');
    await page.click('button:has-text("Engage Engine")');
    
    console.log('Monitoring telemetry...');
    await page.waitForTimeout(3000);
    await page.screenshot({ path: path.join(__dirname, 'test_engage_final.png') });
    
    const statusText = await page.innerText('span:has-text("Status:")');
    console.log('Current UI Status:', statusText);
    
    const hasLog = await page.locator('text=Engine Hooked').isVisible();
    console.log('Backend logs appearing in UI:', hasLog);

  } catch (e) {
    console.error('Test Failed:', e.message);
    await page.screenshot({ path: path.join(__dirname, 'test_engage_error.png') });
  } finally {
    await browser.close();
  }
})();
