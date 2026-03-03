const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1440, height: 900 });

  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });

    // 1. Check Library
    console.log('Testing Library...');
    await page.click('button:has-text("媒体库")');
    await page.waitForTimeout(2000);
    await page.screenshot({ path: 'test_final_library.png' });
    const libraryItems = await page.locator('.grid').count();
    console.log(`Library items found: ${libraryItems}`);

    // 2. Check UI Scale
    console.log('Testing UI Scale...');
    await page.click('button:has-text("制作任务")');
    await page.waitForTimeout(1000);
    const h2Size = await page.locator('h2').first().evaluate(el => window.getComputedStyle(el).fontSize);
    console.log(`H2 font size: ${h2Size}`);
    
    // 3. Check Position Decoupling
    console.log('Testing Position Decoupling...');
    await page.click('button:has-text("视觉实验室")');
    await page.waitForTimeout(2000);
    // Move main to top
    await page.locator('input[type=range]').nth(1).fill('60');
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'test_final_pos1.png' });
    // Move sub to bottom
    await page.locator('input[type=range]').nth(3).fill('2');
    await page.waitForTimeout(500);
    await page.screenshot({ path: 'test_final_pos2.png' });
    console.log('Position tests complete.');

  } catch (e) {
    console.error('Final verification failed:', e.message);
  } finally {
    await browser.close();
  }
})();
