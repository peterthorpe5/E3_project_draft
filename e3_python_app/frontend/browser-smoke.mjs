/** Assert that the three real libraries render without network requests or JS errors. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { readFile } from "node:fs/promises";
const directory = process.argv[2];
if (!directory) throw new Error("Supply the synthetic viewer-document directory");

/** Count exact colour pixels to check the rendered model as well as the UI state. */
async function assertTraceColours(trace, ...colours) {
  const counts = await trace.evaluate((canvas, values) => {
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    const counts = Object.fromEntries(values.map(value => [Number.parseInt(value.slice(1), 16), 0]));
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] < 220) continue;
      const rgb = (pixels[i] << 16) | (pixels[i + 1] << 8) | pixels[i + 2];
      if (Object.hasOwn(counts, rgb)) counts[rgb] += 1;
    }
    return values.map(value => counts[Number.parseInt(value.slice(1), 16)]);
  }, colours);
  for (const [index, count] of counts.entries()) {
    assert.ok(count > 0, `${colours[index]} is drawn on the trace`);
  }
}

/** Check that the view creates a PDF containing the current colour key. */
async function assertViewPdf(page, button, ...labels) {
  const pending = page.waitForEvent("download");
  await button.click();
  const download = await pending;
  assert.match(download.suggestedFilename(), /_3d_view\.pdf$/);
  const contents = await readFile(await download.path());
  assert.match(contents.subarray(0, 8).toString("ascii"), /^%PDF-1.4/);
  assert.ok(contents.includes("/Subtype /Image"), "the current model image is embedded");
  for (const label of labels) assert.ok(contents.includes(label), `PDF contains ${label}`);
  if (process.env.E3_VIEWER_PDF_QA && labels.includes("Synthetic model")) {
    await download.saveAs(process.env.E3_VIEWER_PDF_QA);
  }
}

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
    if (name !== "nightingale-linked") assert.equal(await page.locator('input[type="color"]').count(), 0);
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
      if (name === "nightingale-linked") {
        for (const label of ["Domain colour", "Pocket colour"]) {
          assert.ok(await page.getByLabel(label).isDisabled());
        }
      }
      await page.locator("nightingale-track").first().locator("rect.feature").first().click();
      assert.match(await page.locator(".feature-selection-detail").innerText(), /2–10/);
      if (name === "nightingale-linked") {
        const trace = page.locator("canvas.linked-trace");
        const graph = page.locator("nightingale-linegraph-track");
        const domain = page.getByRole("button", { name: "SYNTHETIC_DOMAIN", exact: true });
        const recorded = page.getByRole("button", { name: /RECORDED_DOMAIN/ });
        const pocket = page.getByRole("button", { name: "Pocket 4 · rank 1" });
        const otherPocket = page.getByRole("button", { name: "Pocket 2 · rank 2" });
        const domainColour = page.getByLabel("Domain colour");
        const pocketColour = page.getByLabel("Pocket colour");
        const reset = page.getByRole("button", { name: "Reset colours" });
        const pocketTrack = page.locator("nightingale-track").nth(2);
        const selected = page.locator(".feature-selection-detail");
        assert.equal(await domain.getAttribute("aria-pressed"), "true");
        assert.equal(await trace.getAttribute("data-domain-count"), "9");
        assert.equal(await track.getAttribute("highlight"), "2:10");
        assert.equal(await track.getAttribute("highlight-color"), "#182554");
        assert.equal(await domainColour.inputValue(), "#182554");
        assert.ok(await pocketColour.isDisabled());
        assert.ok(await reset.isDisabled());
        assert.equal(await graph.getAttribute("display-start"), "2");
        assert.equal(await graph.evaluate(track => track.data[0].values[9].value), null);
        await pocket.click();
        assert.equal(await trace.getAttribute("data-pocket-count"), "2");
        assert.equal(await trace.getAttribute("data-domain-count"), "9");
        await assertTraceColours(trace, "#182554", "#c24e00");
        assert.equal(await pocketTrack.getAttribute("highlight"), "3:3,5:5");
        assert.equal(await pocketColour.inputValue(), "#c24e00");
        await domainColour.fill("#a62bd0");
        await pocketColour.fill("#097a30");
        await assertTraceColours(trace, "#a62bd0", "#097a30");
        assert.equal(await track.getAttribute("highlight-color"), "#a62bd0");
        assert.equal(await track.locator("path.feature").first().getAttribute("stroke"), "#a62bd0");
        assert.equal(await pocketTrack.getAttribute("highlight-color"), "#097a30");
        assert.equal(await pocketTrack.locator("path.feature").first().getAttribute("stroke"), "#097a30");
        assert.equal(await pocket.evaluate(node => node.style.getPropertyValue("--selection-colour")), "#097a30");
        assert.equal(await domain.getAttribute("aria-pressed"), "true");
        await otherPocket.click();
        assert.equal(await pocketColour.inputValue(), "#007d7c");
        await assertTraceColours(trace, "#a62bd0", "#007d7c");
        assert.equal(await trace.getAttribute("data-pocket-count"), "3");
        await pocket.click();
        assert.equal(await pocketColour.inputValue(), "#097a30");
        await assertTraceColours(trace, "#a62bd0", "#097a30");
        await page.locator("nightingale-track").first().locator("rect.feature").first().click();
        assert.equal(await domain.getAttribute("aria-pressed"), "false");
        assert.equal(await trace.getAttribute("data-domain-count"), "0");
        assert.ok(await domainColour.isDisabled());
        assert.equal(await trace.getAttribute("data-pocket-count"), "2");
        assert.match(await page.locator(".domain-provenance").innerText(), /overlay is approximate/);
        assert.match(await recorded.locator("..").innerText(), /4–7 · Recorded coordinates/);
        assert.equal(await page.locator("nightingale-track").nth(1).locator("rect.feature").count(), 1);
        await recorded.press("Enter");
        assert.equal(await domainColour.inputValue(), "#182554");
        assert.equal(await trace.getAttribute("data-domain-count"), "4");
        assert.equal(await trace.getAttribute("data-pocket-count"), "2");
        await recorded.click();
        assert.equal(await trace.getAttribute("data-domain-count"), "0");
        await domain.click();
        assert.equal(await domainColour.inputValue(), "#a62bd0");
        await reset.click();
        assert.equal(await domainColour.inputValue(), "#182554");
        assert.equal(await pocketColour.inputValue(), "#c24e00");
        assert.ok(await reset.isDisabled());
        await assertTraceColours(trace, "#182554", "#c24e00");
        const query = page.getByRole("textbox", { name: "Amino-acid sequence" });
        const mode = page.getByLabel("Highlight", { exact: true });
        const matchColour = page.getByLabel("Match colour");
        await query.fill("ac d");
        await query.press("Enter");
        assert.equal(await trace.getAttribute("data-sequence-count"), "6");
        await assertTraceColours(trace, "#182554", "#c24e00", "#e32860");
        await mode.selectOption("one");
        await page.getByLabel("Match number").fill("2");
        await page.getByLabel("Match number").press("Tab");
        assert.equal(await trace.getAttribute("data-sequence-count"), "3");
        assert.match(await page.locator(".sequence-search p").innerText(), /Match 2 of 2 · 18–20/);
        await matchColour.fill("#f019aa");
        await page.getByRole("button", { name: "Zoom in", exact: true }).click();
        await assertTraceColours(trace, "#f019aa");
        await assertViewPdf(page, page.getByRole("button", { name: "Download 3D view (PDF)" }),
          "Synthetic model", "SYNTHETIC_DOMAIN", "Pocket 4", "Matches: ACD", "Match 2 of 2");
        await page.getByRole("button", { name: "Fit model" }).click();
        await query.fill("A.D");
        await query.press("Enter");
        assert.equal(await trace.getAttribute("data-sequence-count"), "0");
        assert.match(await page.locator(".sequence-search p").innerText(), /Use amino-acid/);
        await query.fill("QWFAA");
        await query.press("Enter");
        assert.match(await page.locator(".sequence-search p").innerText(), /No exact matches/);
        await page.getByRole("button", { name: "Clear matches" }).click();
        await reset.click();
        assert.equal(await matchColour.inputValue(), "#e32860");
        assert.equal(await trace.getAttribute("data-domain-count"), "9");
        const graphPoint = await graph.evaluate(track => ({
          x: track.getXFromSeqPosition(4.5), y: 40,
        }));
        await graph.click({ position: graphPoint });
        assert.match(await selected.innerText(), /E4 · pLDDT 68/);
        assert.equal(await trace.getAttribute("data-domain-count"), "9");
        assert.equal(await trace.getAttribute("data-pocket-count"), "2");
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
        assert.match(await selected.innerText(), /N12/);
        assert.equal(await graph.getAttribute("highlight"), "12:12");
        await page.getByRole("button", { name: "Clear selection" }).click();
        for (const kind of ["domain", "pocket", "residue", "sequence"])
          assert.equal(await trace.getAttribute(`data-${kind}-count`), "0");
        await page.setViewportSize({ width: 620, height: 1000 });
        assert.ok(await trace.isVisible());
        assert.ok(await domainColour.isVisible());
        assert.ok(await pocketColour.isVisible());
      }
    }
    assert.deepEqual(errors, [], name + " JavaScript errors after interactions");
    assert.deepEqual(outbound, [], name + " must remain offline during interactions");
    console.log(JSON.stringify({ viewer: name, drawn, status: await page.locator("#status").innerText() }));
  }
  for (const name of ["review-group", "review-pair"]) {
    const page = await browser.newPage({ viewport: { width: 1240, height: 900 } });
    const errors = [];
    const outbound = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", request => {
      if (/^https?:/.test(request.url())) outbound.push(request.url());
    });
    await page.goto(pathToFileURL(path.join(directory, name + ".html")).href);
    const trace = page.locator("#viewer");
    const domain = page.getByLabel("Protein domain", { exact: true });
    await domain.selectOption("0");
    assert.equal(await trace.getAttribute("data-domain-count"), "3");
    const query = page.getByRole("textbox", { name: "Amino-acid sequence" });
    await query.fill("QWFAA");
    await query.press("Enter");
    assert.equal(await trace.getAttribute("data-sequence-count"), "10");
    await page.getByLabel("Match colour").fill("#f019aa");
    await page.getByLabel("Domain colour").fill("#a8deff");
    await assertTraceColours(trace, "#f019aa", "#a8deff");
    await assertViewPdf(page, page.getByRole("button", { name: "Download 3D view (PDF)" }),
      "N0.HOG1", "Domain: PF00001", "Matches: QWFAA",
      name === "review-pair" ? "Reference pocket" : "Pocket rank 1");
    if (name === "review-pair") {
      await page.getByLabel("Structure to highlight").selectOption("mobile");
      assert.equal(await trace.getAttribute("data-domain-count"), "0");
      assert.equal(await trace.getAttribute("data-sequence-count"), "10");
      await page.locator("#showMobile").uncheck();
      assert.equal(await trace.getAttribute("data-sequence-count"), "0");
      await page.locator("#showMobile").check();
    } else {
      await page.locator("#proteinSelect").selectOption("Q12345");
      assert.equal(await trace.getAttribute("data-domain-count"), "0");
      assert.equal(await trace.getAttribute("data-sequence-count"), "10");
    }
    await page.getByRole("button", { name: "Clear matches" }).click();
    assert.equal(await trace.getAttribute("data-sequence-count"), "0");
    assert.deepEqual(errors, [], name + " JavaScript errors");
    assert.deepEqual(outbound, [], name + " must remain offline");
    console.log(JSON.stringify({ viewer: name, highlights: true, pdf: true }));
    await page.close();
  }
} finally { await browser.close(); }
