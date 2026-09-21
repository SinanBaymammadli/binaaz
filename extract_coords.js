const { chromium } = require('/Users/sinan.baymammadli/dev/5-scm-front-apps/node_modules/playwright-core');

async function extractCoordinates(url) {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  });
  const page = await context.newPage();

  const coords = [];

  // Intercept network requests to catch map API calls
  page.on('request', (req) => {
    const reqUrl = req.url();
    if (reqUrl.includes('maps') || reqUrl.includes('lat') || reqUrl.includes('lng') || reqUrl.includes('coord')) {
      console.log('[REQUEST]', reqUrl);
    }
  });

  console.log('Loading page:', url);
  await page.goto(url, { waitUntil: 'load', timeout: 60000 });

  // Wait for either bina.az content or a long timeout for CF challenge to pass
  try {
    await page.waitForSelector('.item-description, .map-section, #map, [class*="map"], [id*="map"]', { timeout: 30000 });
  } catch (e) {
    console.log('Map/content selector not found, continuing anyway...');
  }

  await page.waitForTimeout(5000);

  // Try to extract coordinates from page source / JS variables
  const result = await page.evaluate(() => {
    const text = document.documentElement.innerHTML;
    const findings = {};

    // Look for lat/lng patterns
    const latLngPattern = /"lat(?:itude)?"\s*:\s*([-\d.]+).*?"lng|lon(?:gitude)?"\s*:\s*([-\d.]+)/gi;
    const matches = [...text.matchAll(/["']lat(?:itude)?["']\s*:\s*([-\d.]+)/gi)];
    const lngMatches = [...text.matchAll(/["']l(?:ng|on)(?:gitude)?["']\s*:\s*([-\d.]+)/gi)];
    findings.latMatches = matches.map(m => m[1]);
    findings.lngMatches = lngMatches.map(m => m[1]);

    // Look for coordinate pairs like [40.xxx, 49.xxx] (Baku area)
    const coordPairs = [...text.matchAll(/(4[0-1]\.\d{4,}),\s*(4[89]\.\d{4,})/g)];
    findings.coordPairs = coordPairs.map(m => ({ lat: m[1], lng: m[2] }));

    // Look in script tags for map initialization
    const scripts = [...document.querySelectorAll('script')].map(s => s.textContent);
    const mapScripts = scripts.filter(s => s.includes('lat') || s.includes('map') || s.includes('coord'));
    findings.mapScriptSnippets = mapScripts.map(s => {
      const latMatch = s.match(/(4[0-1]\.\d{4,})/);
      const lngMatch = s.match(/(4[89]\.\d{4,})/);
      if (latMatch || lngMatch) return { lat: latMatch?.[1], lng: lngMatch?.[1], snippet: s.slice(0, 300) };
      return null;
    }).filter(Boolean);

    // Check for Yandex/Google Maps iframes
    const iframes = [...document.querySelectorAll('iframe')].map(i => i.src);
    findings.iframes = iframes;

    // Check for data attributes
    const mapEl = document.querySelector('[data-lat], [data-lng], [data-latitude], [data-longitude], [data-coords]');
    if (mapEl) {
      findings.mapElement = {
        lat: mapEl.dataset.lat || mapEl.dataset.latitude,
        lng: mapEl.dataset.lng || mapEl.dataset.longitude || mapEl.dataset.lon,
        coords: mapEl.dataset.coords,
      };
    }

    // Try window variables
    try {
      findings.windowKeys = Object.keys(window).filter(k =>
        k.toLowerCase().includes('map') || k.toLowerCase().includes('lat') || k.toLowerCase().includes('coord')
      );
    } catch(e) {}

    return findings;
  });

  console.log('\n=== Extraction Results ===');
  console.log(JSON.stringify(result, null, 2));

  // Also get the page title to confirm we loaded the right page
  const title = await page.title();
  console.log('\nPage title:', title);

  // Save page source for manual inspection if needed
  const source = await page.content();
  const coordSection = source.match(/.{200}(4[0-1]\.\d{4,}).{200}/)?.[0] || 'No Baku-area lat found';
  console.log('\nContext around lat coord:', coordSection);

  await browser.close();
}

const url = process.argv[2] || 'https://bina.az/items/6441221';
extractCoordinates(url).catch(console.error);
