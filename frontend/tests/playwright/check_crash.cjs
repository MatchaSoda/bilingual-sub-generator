const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  
  // Capture console logs
  const logs = [];
  page.on('console', msg => {
    const text = `[${msg.type()}] ${msg.text()}`;
    logs.push(text);
    console.log(text);
  });
  page.on('pageerror', err => {
    const text = `[ERROR] ${err.message}`;
    logs.push(text);
    console.log(text);
  });

  await page.setViewportSize({ width: 1920, height: 1080 });

  console.log('Navigating...');
  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    await page.waitForTimeout(5000);
    await page.screenshot({ path: path.join(__dirname, 'debug_crash.png') });
    
    fs.writeFileSync(path.join(__dirname, 'browser.log'), logs.join('\n'));
    console.log('Done.');
  } catch (e) {
    console.error('Crash:', e.message);
  } finally {
    await browser.close();
  }
})();
