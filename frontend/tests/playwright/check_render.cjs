const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('🚀 Checking font accessibility...');
  const response = await page.goto('http://localhost:8501/fonts/NotoSansCJK-Regular.ttc');
  console.log(`📊 Font load status: ${response.status()}`);

  await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
  await page.click('text=字幕设计');
  await page.waitForTimeout(5000); // 增加等待时间给 WASM 渲染字体

  // 检查渲染错误
  const logs = [];
  page.on('console', msg => logs.push(msg.text()));

  const canvasState = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    if (!canvas) return 'NO_CANVAS';
    // 检查 canvas 是否有像素内容 (不仅仅是空白)
    const ctx = canvas.getContext('2d');
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const hasPixels = data.some(p => p !== 0);
    return hasPixels ? 'RENDERED' : 'BLANK';
  });

  console.log(`📊 Final Canvas State: ${canvasState}`);
  await page.screenshot({ path: 'physical_check.png' });
  await browser.close();
})();
