// Self-contained view bundle for the chart-creator "flint.v1" artifact.
//
// Flint compiles one unified input into a native spec for Vega-Lite, ECharts, or
// Chart.js; this bundle ships all three renderers so it works fully offline. It
// speaks the Open Notebook host handshake: it listens for "open-notebook:artifact"
// postMessages and posts "open-notebook:ready" back to the parent frame.
//
// Built by build.mjs into ../src/chart_creator/view/index.html — do not edit the
// generated HTML by hand.
import { assembleVegaLite, assembleECharts, assembleChartjs } from "flint-chart";
import embed from "vega-embed";
import * as echarts from "echarts";
import { Chart } from "chart.js/auto";

const ASSEMBLE = {
  "vega-lite": assembleVegaLite,
  echarts: assembleECharts,
  chartjs: assembleChartjs,
};

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function rootEl() {
  return document.getElementById("root");
}

function empty(message) {
  rootEl().innerHTML = '<div class="empty">' + esc(message) + "</div>";
}

// Clear the root and (optionally) render the headline; return the root element.
function freshRoot(title) {
  const root = rootEl();
  root.innerHTML = "";
  if (title && String(title).trim()) {
    const h = document.createElement("h3");
    h.textContent = title;
    root.appendChild(h);
  }
  return root;
}

function chartDiv() {
  const el = document.createElement("div");
  el.className = "chart";
  rootEl().appendChild(el);
  return el;
}

// Colours mirror the CSS custom properties in index.html so charts match the shell.
function palette(theme) {
  return theme === "dark"
    ? { fg: "#fafafa", muted: "#a1a1aa", grid: "#3f3f46" }
    : { fg: "#18181b", muted: "#71717a", grid: "#e4e4e7" };
}

function vegaConfig(theme) {
  const p = palette(theme);
  return {
    background: "transparent",
    view: { stroke: null },
    title: { color: p.fg },
    axis: {
      labelColor: p.muted,
      titleColor: p.fg,
      gridColor: p.grid,
      domainColor: p.grid,
      tickColor: p.grid,
    },
    legend: { labelColor: p.muted, titleColor: p.fg },
    header: { labelColor: p.muted, titleColor: p.fg },
  };
}

async function renderFlint(data, theme) {
  const library = data && data.library;
  const input = data && data.input;
  freshRoot(data && data.title);

  const assemble = ASSEMBLE[library];
  if (!assemble || !input) {
    empty("No chart could be rendered for this artifact.");
    return;
  }

  const el = chartDiv();

  if (library === "vega-lite") {
    const spec = assemble(input);
    await embed(el, spec, {
      actions: false,
      renderer: "svg",
      config: vegaConfig(theme),
    });
    return;
  }

  if (library === "echarts") {
    const option = assemble(input);
    const chart = echarts.init(el, theme === "dark" ? "dark" : null, {
      renderer: "svg",
      height: el.clientHeight || 360,
    });
    chart.setOption(option);
    chart.setOption({ backgroundColor: "transparent" });
    window.addEventListener("resize", function () {
      chart.resize();
    });
    return;
  }

  if (library === "chartjs") {
    const config = assemble(input);
    const p = palette(theme);
    Chart.defaults.color = p.muted;
    Chart.defaults.borderColor = p.grid;
    const canvas = document.createElement("canvas");
    el.appendChild(canvas);
    new Chart(canvas, config);
    return;
  }

  empty('Unknown chart library "' + esc(library) + '".');
}

// Per-schema renderers (keyed by CreationResult.schema_id).
const renderers = {
  "flint.v1": renderFlint,
};

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme === "dark" ? "dark" : "light");
}

// "auto" follows the host's light/dark mode; otherwise honour the stored theme.
function resolveTheme(msg) {
  let t = (msg.config && msg.config.theme) || (msg.data && msg.data.theme) || "auto";
  if (t === "auto") t = msg.theme === "dark" ? "dark" : "light";
  return t === "dark" ? "dark" : "light";
}

function onArtifact(msg) {
  const theme = resolveTheme(msg);
  applyTheme(theme);
  const r = renderers[msg.schema_id];
  if (!r) {
    empty('No renderer for "' + esc(msg.schema_id) + '".');
    return;
  }
  try {
    const out = r(msg.data || {}, theme);
    if (out && typeof out.catch === "function") {
      out.catch(function () {
        empty("Failed to render this artifact.");
      });
    }
  } catch (e) {
    empty("Failed to render this artifact.");
  }
}

window.addEventListener("message", function (e) {
  const d = e.data;
  if (d && d.type === "open-notebook:artifact") onArtifact(d);
});

try {
  parent.postMessage({ type: "open-notebook:ready" }, "*");
} catch (e) {}
