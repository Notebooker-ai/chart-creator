## Flint input reference

A Flint input is a single JSON object that Flint compiles into a native chart spec for
the chosen library. Shape:

```json
{
  "data": { "values": [ { "region": "North", "revenue": 120 }, ... ] },
  "semantic_types": { "region": "Category", "revenue": "Quantity" },
  "chart_spec": {
    "chartType": "Bar Chart",
    "encodings": { "x": { "field": "region" }, "y": { "field": "revenue" } },
    "canvasSize": { "width": 640, "height": 400 }
  }
}
```

### data.values
An array of flat row objects (like Vega-Lite `data.values`). Every field you reference in
`encodings` must exist as a key on these rows. Keep rows small and focused (typically 3–20).

### semantic_types
Map **every field used in encodings** to one Flint semantic type. This is how Flint makes
smart layout/scale/colour decisions, so choose the most specific type that fits:

- Measures: `Quantity`, `Count`, `Amount`, `Price`, `Percentage`, `Profit`,
  `PercentageChange`, `Score`, `Rank`, `Temperature`, `Number`
- Time: `Year`, `Quarter`, `Month`, `Week`, `Day`, `Date`, `DateTime`, `YearMonth`
- Categorical / labels: `Category`, `Name`, `Status`, `Boolean`, `Direction`
- Geography: `Country`, `State`, `City`, `Region`, `Latitude`, `Longitude`

### chart_spec
- `chartType` — must be one of the chosen library's chart types (see the catalog).
- `encodings` — map visual channels to fields, e.g. `{ "x": {"field":"month"},
  "y": {"field":"sales"}, "color": {"field":"category"} }`. Only use channels the chart
  type supports (the catalog lists each chart's channels). Common channels: `x`, `y`,
  `color`, `size`, `column`, `row`, `detail`, `theta`. For part-to-whole charts (Pie,
  Doughnut, Rose) use `color` for the category and `size`/`theta` for the value.
- `canvasSize` — `{ "width": 640, "height": 400 }` is a good default.

### Worked examples

Trend over time (ECharts line):
```json
{ "library": "echarts", "input": {
  "data": { "values": [ {"month":"Jan","users":30}, {"month":"Feb","users":55}, {"month":"Mar","users":80} ] },
  "semantic_types": { "month": "Month", "users": "Count" },
  "chart_spec": { "chartType": "Line Chart", "encodings": { "x": {"field":"month"}, "y": {"field":"users"} } } } }
```

Category comparison (Vega-Lite bar):
```json
{ "library": "vega-lite", "input": {
  "data": { "values": [ {"region":"North","revenue":120}, {"region":"South","revenue":90} ] },
  "semantic_types": { "region": "Category", "revenue": "Quantity" },
  "chart_spec": { "chartType": "Bar Chart", "encodings": { "x": {"field":"region"}, "y": {"field":"revenue"} } } } }
```

Part-to-whole (Chart.js pie):
```json
{ "library": "chartjs", "input": {
  "data": { "values": [ {"brand":"A","share":45}, {"brand":"B","share":30}, {"brand":"C","share":25} ] },
  "semantic_types": { "brand": "Category", "share": "Percentage" },
  "chart_spec": { "chartType": "Pie Chart", "encodings": { "color": {"field":"brand"}, "size": {"field":"share"} } } } }
```
