/** Assert that the three real libraries render without network requests or JS errors. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
const directory = process.argv[2];
if (!directory) throw new Error("Supply the synthetic viewer-document directory");
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.CHROMIUM_EXECUTABLE || undefined,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
try {
  for (const name of ["alignment", "jbrowse", "nightingale", "nightingale-recorded", "jbrowse-species"]) {
    const nightingale = name.startsWith("nightingale");
    const page = await browser.newPage({ viewport: { width: 1300, height: 800 } });
    const errors = [], failed = [], outbound = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("requestfailed", request => failed.push(request.url()));
    page.on("request", request => { if (/^https?:/.test(request.url())) outbound.push(request.url()); });
    await page.goto(pathToFileURL(path.resolve(directory, name + ".html")).href);
    await page.waitForFunction(() => !document.getElementById("status").textContent.startsWith("Loading"));
    await page.waitForTimeout(1500);
    assert.deepEqual(errors, [], name + " JavaScript errors");
    assert.deepEqual(failed, [], name + " failed resources");
    assert.deepEqual(outbound, [], name + " must remain offline");
    const drawn = await page.locator(nightingale ? "svg" : "canvas").count();
    assert.ok(drawn > 0, name + " must draw the actual data");
    if (nightingale) {
      const expectedLength = name === "nightingale-recorded" ? "100" : "20";
      assert.equal(await page.locator("nightingale-track").getAttribute("length"), expectedLength);
      assert.ok(await page.locator("nightingale-track svg rect").count() > 0);
      await page.evaluate(() => document.querySelector("nightingale-navigation").dispatchEvent(
        new CustomEvent("change", { bubbles: true, detail: { "display-start": 2, "display-end": 10 } })));
      assert.equal(await page.locator("nightingale-track").getAttribute("display-start"), "2");
      assert.equal(await page.locator("nightingale-track").getAttribute("display-end"), "10");
      if (name === "nightingale-recorded")
        assert.equal(await page.locator("nightingale-sequence").count(), 0);
    }
    console.log(JSON.stringify({ viewer: name, drawn, status: await page.locator("#status").innerText() }));
  }
} finally { await browser.close(); }
