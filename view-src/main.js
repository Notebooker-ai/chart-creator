// Self-contained view bundle for the chart-creator "flint.v1" artifact.
//
// Flint compiles one unified input into a native spec for Vega-Lite, ECharts, or
// Chart.js; this bundle ships all three renderers so it works fully offline. It
// speaks the Open Notebook host handshake: it listens for "open-notebook:artifact"
// postMessages and posts "open-notebook:ready" back to the parent frame.
//
// Built by build.mjs into ../src/chart_creator/view/index.html — do not edit the
// generated HTML by hand.
import {countChannels, vegaCountAxes, denominatorDomain} from "./axes.js";
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

// Size the chart to the card it lives in. Flint bakes canvasSize into the
// compiled spec as fixed pixels, so a hardcoded 640x400 renders as a tiny
// chart pinned to the corner of a wide card — measure the container instead.
function containerSize(el) {
  const width = Math.max(320, el.clientWidth || rootEl().clientWidth || 640);
  const height = Math.round(Math.min(480, Math.max(300, width * 0.55)));
  return { width: width, height: height };
}

async function renderFlint(data, theme) {
  const library = data && data.library;
  const input = data && data.input;
  freshRoot(data && data.title);
  if (typeof input?.caption === 'string' && input.caption.trim()) {
    const caption = document.createElement('p');
    caption.className = 'caption';
    caption.textContent = input.caption;
    rootEl().appendChild(caption);
  }

  const assemble = ASSEMBLE[library];
  if (!assemble || !input) {
    empty("No chart could be rendered for this artifact.");
    return;
  }

  const el = chartDiv();
  const size = containerSize(el);
  const counts = countChannels(input);
  const domains = Object.fromEntries(counts.map(({channel,field}) => [field,denominatorDomain(input,channel,field)]));
  if (input.chart_spec && typeof input.chart_spec === "object") {
    input.chart_spec.canvasSize = size;
  }

  if (library === "vega-lite") {
    const spec = vegaCountAxes(assemble(input), counts.map(c => c.field), domains);
    // Flint emits fixed pixel dimensions; hand layout back to Vega so the
    // chart tracks the container across resizes.
    spec.width = "container";
    if (!spec.hconcat && !spec.vconcat && !spec.concat && !spec.facet) spec.height = size.height;
    spec.autosize = { type: "fit", contains: "padding" };
    el.style.width = "100%";
    await embed(el, spec, {
      actions: false,
      renderer: "svg",
      config: vegaConfig(theme),
    });
    return;
  }

  if (library === "echarts") {
    const option = assemble(input);
    counts.forEach(({channel}) => {
      const axes = option[`${channel}Axis`];
      (Array.isArray(axes) ? axes : [axes]).filter(Boolean).forEach(axis => {
        if (axis.type === 'value') {
          axis.minInterval = 1;
          const field = counts.find(c => c.channel === channel).field;
          if (domains[field]) [axis.min,axis.max] = domains[field];
        }
      });
    });
    const chart = echarts.init(el, theme === "dark" ? "dark" : null, {
      renderer: "svg",
      width: size.width,
      height: size.height,
    });
    chart.setOption(option);
    chart.setOption({ backgroundColor: "transparent" });
    window.addEventListener("resize", function () {
      chart.resize({ width: el.clientWidth || size.width });
    });
    return;
  }

  if (library === "chartjs") {
    const config = assemble(input);
    counts.forEach(({channel,field}) => {
      config.options ||= {};
      config.options.scales ||= {};
      config.options.scales[channel] ||= {};
      if (domains[field]) [config.options.scales[channel].min,config.options.scales[channel].max] = domains[field];
      config.options.scales[channel].ticks = {...config.options.scales[channel].ticks, precision: 0};
    });
    const p = palette(theme);
    Chart.defaults.color = p.muted;
    Chart.defaults.borderColor = p.grid;
    el.style.height = size.height + "px";
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

// Surface the underlying error so a broken spec is diagnosable from the card
// instead of a bare "failed" with the detail lost inside the sandbox.
function renderFailureMessage(e) {
  const detail = e && e.message ? " (" + e.message + ")" : "";
  return "Failed to render this artifact." + detail;
}

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
      out.catch(function (e) {
        empty(renderFailureMessage(e));
      });
    }
  } catch (e) {
    empty(renderFailureMessage(e));
  }
}

window.addEventListener("message", function (e) {
  const d = e.data;
  if (d && d.type === "open-notebook:artifact") onArtifact(d);
});

try {
  parent.postMessage({ type: "open-notebook:ready" }, "*");
} catch (e) {}
