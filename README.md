# chart-creator

An [Open Notebook](https://open-notebook.ai) **creator** plugin: turns notebook
content into a chart, designed as an [AntV Infographic](https://infographic.antv.vision/)
DSL string using the `chart-*` templates (line / column / bar / pie / wordcloud).

- Emits the `infographic.v2` artifact schema (rendered client-side to SVG by `@antv/infographic`).
- Uses only `chart-*` templates; non-chart infographic templates live in
  [`infographic-creator`](https://github.com/Notebooker-ai/infographic-creator) (also `infographic.v2`).
- Implements the [`open-notebook-creator-sdk`](https://github.com/Notebooker-ai/open-notebook-creator-sdk) `BaseCreator` contract; registers under `open_notebook.creators`.

## Model roles

| role | kind | requires |
|------|------|----------|
| `text` | language | `structured_json` |

## Config

| field | default | notes |
|-------|---------|-------|
| `theme` | "auto" | auto/light/dark/hand-drawn (AntV theme) |

## Dev

```bash
uv sync --extra dev
uv run pytest
```

MIT licensed.
