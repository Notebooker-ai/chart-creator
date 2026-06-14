# chart-creator

An [Open Notebook](https://open-notebook.ai) **creator** plugin: turns notebook
content into [AntV G2](https://g2.antv.antgroup.com/) charts.

- Emits the `chart_spec.v1` artifact schema (rendered client-side by `@antv/g2`).
- Partial-failure aware: invalid specs are dropped with a warning; valid charts still render.
- Implements the [`open-notebook-creator-sdk`](https://github.com/Notebooker-ai/open-notebook-creator-sdk) `BaseCreator` contract; registers under `open_notebook.creators`.

## Model roles

| role | kind | requires |
|------|------|----------|
| `text` | language | `structured_json` |

## Config

| field | default | notes |
|-------|---------|-------|
| `max_charts` | 3 | 1–8 |
| `theme` | "auto" | auto/light/dark/classic/classicDark/academy |

## Dev

```bash
uv sync --extra dev
uv run pytest
```

MIT licensed.
