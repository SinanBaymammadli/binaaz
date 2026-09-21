const { chromium } = require('/Users/sinan.baymammadli/dev/5-scm-front-apps/node_modules/playwright-core');

async function readListing(url) {
  // Use real Chrome with your actual profile — CF recognizes returning users
  const context = await chromium.launchPersistentContext(
    '/tmp/bina-chrome-profile',
    {
      headless: false,
      executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      args: ['--no-first-run', '--no-default-browser-check'],
    }
  );

  const page = await context.newPage();

  console.log('Opening:', url);
  await page.goto(url, { waitUntil: 'load', timeout: 60000 });

  // Wait for CF challenge to pass and real page to load
  try {
    await page.waitForFunction(
      () => document.title !== 'Just a moment...',
      { timeout: 30000 }
    );
    console.log('Page loaded. Title:', await page.title());
  } catch (e) {
    console.log('Still on CF challenge page. Title:', await page.title());
  }

  await page.waitForTimeout(3000);

  const result = await page.evaluate(() => {
    // Try common price selectors on bina.az
    const selectors = [
      '.price-val',
      '.product-price',
      '[class*="price"]',
      '.item-price',
      'span.price',
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return { selector: sel, price: el.innerText.trim() };
    }
    // Fallback: search page text for AZN price pattern
    const match = document.body.innerText.match(/[\d\s]+\s*AZN/);
    return { selector: 'text-search', price: match?.[0]?.trim() || 'not found' };
  });

  console.log('Price result:', result);

  await context.close();
}

const url = process.argv[2] || 'https://bina.az/items/6441221';
readListing(url).catch(console.error);
