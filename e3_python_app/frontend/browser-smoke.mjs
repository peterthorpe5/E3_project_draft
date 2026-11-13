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
  for (const name of [
    "alignment", "jbrowse", "nightingale", "nightingale-recorded", "jbrowse-species",
    "nightingale-linked",
  ]) {
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
      const track = page.locator("nightingale-track").first();
      assert.equal(await track.getAttribute("length"), expectedLength);
      assert.ok(await page.locator("nightingale-track svg rect").count() > 0);
      await page.evaluate(() => document.querySelector("nightingale-navigation").dispatchEvent(
        new CustomEvent("change", { bubbles: true, detail: { "display-start": 2, "display-end": 10 } })));
      assert.equal(await track.getAttribute("display-start"), "2");
      assert.equal(await track.getAttribute("display-end"), "10");
      if (name === "nightingale-recorded")
        assert.equal(await page.locator("nightingale-sequence").count(), 0);
      await page.locator("nightingale-track").last().locator("rect.feature").first().click();
      assert.match(await page.locator(".feature-selection-detail").innerText(), /2–10/);
      if (name === "nightingale-linked") {
        const trace = page.locator("canvas.linked-trace");
        const graph = page.locator("nightingale-linegraph-track");
        assert.equal(await trace.getAttribute("data-selected-count"), "9");
        assert.equal(await graph.getAttribute("highlight"), "2:10");
        assert.equal(await graph.getAttribute("display-start"), "2");
        assert.equal(await graph.evaluate(track => track.data[0].values[9].value), null);
        await page.getByRole("button", { name: "Pocket 4 · rank 1" }).click();
        assert.equal(await trace.getAttribute("data-selected-count"), "2");
        assert.equal(await graph.getAttribute("highlight"), "3:3,5:5");
        const graphPoint = await graph.evaluate(track => ({
          x: track.getXFromSeqPosition(4.5), y: 40,
        }));
        await graph.click({ position: graphPoint });
        assert.match(await page.locator(".feature-selection-detail").innerText(), /E4 · pLDDT 68/);
        const position = await trace.evaluate(canvas => {
          const az = .55, el = -.28;
          const cy = Math.cos(az), sy = Math.sin(az);
          const cx = Math.cos(el), sx = Math.sin(el);
          const { clientWidth: width, clientHeight: height } = canvas;
          const rows = JSON.parse(document.getElementById("protein-data").textContent).model;
          const mean = axis => rows.reduce((sum, row) => sum + row[axis] / rows.length, 0);
          const centre = ["x", "y", "z"].map(mean);
          const radius = Math.max(...rows.map(row =>
            Math.hypot(row.x - centre[0], row.y - centre[1], row.z - centre[2])));
          const scale = Math.min(width, height) * .44 / radius;
          const row = rows[11];
          const x = row.x - centre[0], y = row.y - centre[1], z = row.z - centre[2];
          return { x: width / 2 + (x * cy + z * sy) * scale,
            y: height / 2 - (y * cx - (z * cy - x * sy) * sx) * scale };
        });
        await trace.click({ position });
        assert.match(await page.locator(".feature-selection-detail").innerText(), /N12/);
        assert.equal(await graph.getAttribute("highlight"), "12:12");
        await page.getByRole("button", { name: "Clear selection" }).click();
        assert.equal(await trace.getAttribute("data-selected-count"), "0");
        await page.setViewportSize({ width: 620, height: 1000 });
        assert.ok(await trace.isVisible());
      }
    }
    assert.deepEqual(errors, [], name + " JavaScript errors after interactions");
    assert.deepEqual(outbound, [], name + " must remain offline during interactions");
    console.log(JSON.stringify({ viewer: name, drawn, status: await page.locator("#status").innerText() }));
  }
} finally { await browser.close(); }
