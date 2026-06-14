AntV Infographic DSL — syntax & chart template catalog.
Adapted from AntV Infographic's `infographic-creator` skill (MIT, v0.2.x,
https://github.com/antvis/Infographic). Refresh via AntV's `infographic-template-updater` skill.

## Grammar

- The first line must be `infographic <template-name>` (a `chart-*` template).
- Then a `data` block, and an optional `theme` block. Inside a block, indent with TWO spaces per level.
- Key/value pairs are written `key value`. Arrays use `-` to start each object item.
- The single main data field for charts is `values`: one ordered series of points.
  - Each point uses `label` for the category/word and `value` for the number.
  - `value` is a bare number; put units in `title`/`desc`.
  - Line/bar/column order follows the order of the `values` entries.
- `title` and optional `desc` are top-level data fields.
- Do NOT add `icon` to chart data points.

### Theme (optional)

```
theme
  palette #4f46e5 #db2777 #14b8a6
```

- `palette` colours are bare hex values — no quotes, no commas.

## Available chart templates

- `chart-line-plain-text` — trend over an ordered axis (single series)
- `chart-bar-plain-text` — horizontal category comparison
- `chart-column-simple` — vertical category comparison
- `chart-pie-plain-text` — part-to-whole (few slices)
- `chart-pie-compact-card` — part-to-whole, compact card style
- `chart-pie-donut-plain-text` — donut part-to-whole
- `chart-pie-donut-pill-badge` — donut with pill badges
- `chart-pie-donut-compact-card` — donut, compact card style
- `chart-pie-pill-badge` — pie with pill badges
- `chart-wordcloud` — word/term frequency (label = word, value = weight)
- `chart-wordcloud-rotate` — word cloud with rotated words

## Template selection guide

- Trend / change over an ordered sequence → `chart-line-plain-text`
- Compare quantities across categories → `chart-column-simple` (vertical) or `chart-bar-plain-text` (horizontal)
- Share of a total / proportions → `chart-pie-*` / `chart-pie-donut-*`
- Relative frequency of terms/themes → `chart-wordcloud` / `chart-wordcloud-rotate`

## Worked examples

line:
```
infographic chart-line-plain-text
data
  title Model A accuracy over weeks
  desc Biggest jump in week 4
  values
    - label Week1
      value 86.5
    - label Week2
      value 87.3
    - label Week3
      value 89.1
    - label Week4
      value 91.2
theme
  palette #4f46e5 #db2777 #14b8a6
```

column:
```
infographic chart-column-simple
data
  title Revenue by region
  values
    - label North
      value 120
    - label South
      value 90
    - label East
      value 75
    - label West
      value 110
```

pie:
```
infographic chart-pie-donut-plain-text
data
  title Traffic sources
  values
    - label Organic
      value 52
    - label Paid
      value 28
    - label Referral
      value 20
```

wordcloud:
```
infographic chart-wordcloud
data
  title Key themes
  values
    - label resilience
      value 40
    - label recovery
      value 32
    - label aid
      value 25
```

## Self-check before output

- First line is `infographic chart-...`.
- Exactly one main data field: `values`, a single ordered series.
- Each point has `label` and a bare numeric `value`; no `icon`.
- `palette` values are bare hex (no quotes/commas).
- Derive numbers from the content; prefer qualitative/relative values when you cannot support precise figures.
