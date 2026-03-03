const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  const page = await browser.newPage();
  
  // 设置视口大小为 1920x1080 方便对比
  await page.setViewportSize({ width: 1920, height: 1080 });

  console.log('Navigating to http://localhost:8501...');
  try {
    await page.goto('http://localhost:8501', { waitUntil: 'networkidle' });
    
    // 强制等待一会
    await page.waitForTimeout(2000);
    const screenshotPath0 = path.join(__dirname, 'debug_init.png');
    await page.screenshot({ path: screenshotPath0 });
    console.log('Init screenshot saved.');

    // 点击进入字幕设计标签
    console.log('Switching to Design tab...');
    const buttons = await page.$$('button');
    for (const btn of buttons) {
       const text = await btn.innerText();
       if (text.includes('字幕设计')) {
          await btn.click();
          break;
       }
    }
    
    // 等待引擎激活文字出现
    console.log('Waiting for engine status...');
    await page.waitForSelector('text=PHYSICAL ENGINE ACTIVE', { timeout: 10000 });
    
    // 增加一点渲染缓冲时间
    await page.waitForTimeout(3000);

    // 1. 获取 Canvas 状态 (适配 OffscreenCanvas)
    const canvasExists = await page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      if (!canvas) return 'NO_CANVAS';
      
      // 因为 JASSUB 使用了 OffscreenCanvas，直接 getContext 会报错
      // 我们通过计算属性和父级容器来判断
      const rect = canvas.getBoundingClientRect();
      const style = window.getComputedStyle(canvas);
      
      return {
        width: canvas.width,
        height: canvas.height,
        rect: { width: rect.width, height: rect.height },
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
        parentElement: canvas.parentElement.className
      };
    });
    console.log('Canvas State:', JSON.stringify(canvasExists, null, 2));

    // 截图进行视觉核查
    const screenshotPath = path.join(__dirname, 'debug_render_error.png');
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`Error screenshot saved to ${screenshotPath}`);
    
    // 强制尝试点击
    await page.evaluate(() => {
       const buttons = Array.from(document.querySelectorAll('button'));
       const designBtn = buttons.find(b => b.innerText.includes('字幕设计'));
       if (designBtn) designBtn.click();
    });
    await page.waitForTimeout(5000);
    await page.screenshot({ path: path.join(__dirname, 'debug_after_click.png'), fullPage: true });

    const content = await page.content();
    fs.writeFileSync(path.join(__dirname, 'debug_page.html'), content);
    console.log('Page content saved.');

    // 3. 检查控制台错误
    page.on('console', msg => console.log('BROWSER LOG:', msg.text()));
    page.on('pageerror', err => console.log('BROWSER ERR:', err.message));

  } catch (e) {
    console.error('Test Failed:', e.message);
  } finally {
    await browser.close();
  }
})();
