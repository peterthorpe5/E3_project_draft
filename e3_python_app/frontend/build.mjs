/** Reproducible local viewer assets; never submit protein data to a CDN. */
import { build } from "esbuild";
import { readFile, writeFile, mkdir, readdir, copyFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import * as sass from "sass";
import { scssExports } from "./style-exports.mjs";
const destination = "../src/e3app/resources/research_viewers";
await mkdir(destination, { recursive: true });
for (const entry of ["alignment.jsx", "nightingale.js"]) {
  await build({ entryPoints: [entry], bundle: true, minify: true, legalComments: "eof",
    outfile: path.join(destination, entry === "alignment.jsx" ? "alignment.js" : entry),
    define: { "process.env.NODE_ENV": '"production"', "process.env": '{}' }, loader: { ".woff": "dataurl", ".woff2": "dataurl", ".ttf": "dataurl" },
    plugins: [{ name: "portable-upstream-icons", setup(builder) {
      builder.onLoad({ filter: /\.js$/ }, async (args) => {
        if (!args.path.includes("alignment-viewer-2")) return;
        const source = await readFile(args.path, "utf8");
        const icon = "data:image/svg+xml;base64," + Buffer.from(await readFile("close.svg")).toString("base64");
        return { contents: source.replaceAll('${process.env.PUBLIC_URL}/close.svg', icon),
          loader: "js", resolveDir: path.dirname(args.path) };
      });
    }}, { name: "upstream-sass-exports", setup(builder) {
      builder.onLoad({ filter: /\.scss$/ }, async (args) => ({
        contents: "export default " + JSON.stringify(scssExports(sass.compile(args.path, { logger: sass.Logger.silent }).css)), loader: "js"
      }));
    }}] });
}
const response = await fetch("https://unpkg.com/react-msaview@9.8.0/bundle/index.js");
if (!response.ok) throw new Error("Could not fetch pinned JBrowse MSA bundle");
const jbrowse = Buffer.from(await response.arrayBuffer());
const expected = (await readFile("jbrowse.sha256", "utf8")).trim();
if (createHash("sha256").update(jbrowse).digest("hex") !== expected) throw new Error("JBrowse bundle checksum differs");
await writeFile(path.join(destination, "jbrowse.js"), jbrowse);
const notices = ["Bundled upstream viewer packages. See the lockfile for exact dependency versions.\n"];
const pending = ["node_modules"];
while (pending.length) {
  const directory = pending.pop();
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const name = path.join(directory, entry.name);
    if (entry.isDirectory() && ![".bin", "dist", "build", "src", "lib", "test", "tests"].includes(entry.name)) pending.push(name);
    else if (entry.isFile() && /^(licen[cs]e|copying|notice)(\.|$)/i.test(entry.name)) {
      notices.push("\n===== " + name + " =====\n" + await readFile(name, "utf8"));
    }
  }
}
const licence = await fetch("https://unpkg.com/react-msaview@9.8.0/LICENSE");
if (!licence.ok) throw new Error("Could not fetch JBrowse licence");
notices.push("\n===== react-msaview 9.8.0 =====\n" + await licence.text());
await writeFile(path.join(destination, "THIRD_PARTY_NOTICES.txt"), notices.join("\n"));
const hashes = {};
for (const name of await readdir(destination)) {
  if (name !== "checksums.json") hashes[name] = createHash("sha256").update(await readFile(path.join(destination, name))).digest("hex");
}
await writeFile(path.join(destination, "checksums.json"), JSON.stringify(hashes, null, 2) + "\n");
