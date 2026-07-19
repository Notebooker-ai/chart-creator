// Bundles main.js (Flint + Vega-Lite + ECharts + Chart.js) into a single, fully
// offline HTML file at ../src/chart_creator/view/index.html. Run via `npm run build`.
import esbuild from "esbuild";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const outHtml = resolve(here, "../src/chart_creator/view/index.html");

const result = await esbuild.build({
  entryPoints: [resolve(here, "main.js")],
  bundle: true,
  format: "iife",
  minify: true,
  platform: "browser",
  target: ["es2019"],
  legalComments: "none",
  loader: { ".css": "text" },
  write: false,
});

const js = result.outputFiles[0].text;
const shell = readFileSync(resolve(here, "index.html"), "utf8");
// Function replacement avoids `$&`/`$1` interpretation in the bundled JS.
const html = shell.replace("/*__BUNDLE__*/", () => js);

if (html.includes("/*__BUNDLE__*/")) {
  throw new Error("Bundle placeholder not found in index.html shell");
}
if (/src\s*=\s*["']https?:/i.test(html)) {
  throw new Error("Output is not offline: found a remote src= reference");
}

writeFileSync(outHtml, html);
console.log(`Wrote ${outHtml} (${(html.length / 1024).toFixed(0)} KB)`);
