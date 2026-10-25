"""chart-creator: an Open Notebook creator that turns notebook content into a chart.

The LLM designs the chart as a **Flint** (microsoft/flint-chart) unified input — a
declarative ``{data, semantic_types, chart_spec}`` object — targeting one of three
rendering libraries: **Vega-Lite**, **ECharts**, or **Chart.js**. It is emitted as
``flint.v1`` and compiled + rendered client-side by the shipped self-contained view
bundle (``view/index.html``). The user picks a library and chart type in the creation
modal, or leaves either on "Auto" and lets the model choose the best fit for the data.

Browse chart examples: https://microsoft.github.io/flint-chart/#/gallery
"""

import json
import re
from importlib import resources
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Union

from ai_prompter import Prompter
from loguru import logger
from open_notebook_creator_sdk import (
    BaseCreator,
    CreationError,
    CreationFile,
    CreationRequest,
    CreationResult,
    CreatorManifest,
    CreatorView,
    ModelRoleSpec,
    RenderRequest,
)
from open_notebook_creator_sdk.schemas import FlintV1
from pydantic import BaseModel, ConfigDict, Field

from .chart_types import (
    CHART_CATALOG_MARKDOWN,
    CHART_TYPES_BY_LIBRARY,
    CHARTJS_TYPES,
    ECHARTS_TYPES,
    VEGA_LITE_TYPES,
)

__version__ = "0.6.1"

# The editable source: the final Flint unified input (``{data, semantic_types,
# chart_spec, options}``) as JSON, stored next to the artifact as a
# ``role="source"`` file. The host shows it in its source editor and hands it
# back through :meth:`ChartCreator.render`. The rendering ``library`` is not
# part of the Flint input; it is carried forward from the artifact's data.
SOURCE_FILENAME = "chart.json"
SOURCE_CONTENT_TYPE = "application/json"

LIBRARIES = ("vega-lite", "echarts", "chartjs")
GALLERY_URL = "https://microsoft.github.io/flint-chart/#/gallery"

# Chart-type enums per library, generated from Flint's own template defs (see
# chart_types.py). "auto" lets the model pick the best chart type for the data.
_VL_TYPES = Literal[("auto", *VEGA_LITE_TYPES)]  # type: ignore[valid-type]
_EC_TYPES = Literal[("auto", *ECHARTS_TYPES)]  # type: ignore[valid-type]
_CJS_TYPES = Literal[("auto", *CHARTJS_TYPES)]  # type: ignore[valid-type]


class AutoEngine(BaseModel):
    """Auto — the model picks both the rendering library and the chart type."""

    model_config = ConfigDict(title="Auto")
    library: Literal["auto"] = "auto"


class VegaLiteEngine(BaseModel):
    model_config = ConfigDict(title="Vega-Lite")
    library: Literal["vega-lite"] = "vega-lite"
    chart_type: _VL_TYPES = Field(default="auto", title="Chart type")


class EChartsEngine(BaseModel):
    model_config = ConfigDict(title="ECharts")
    library: Literal["echarts"] = "echarts"
    chart_type: _EC_TYPES = Field(default="auto", title="Chart type")


class ChartjsEngine(BaseModel):
    model_config = ConfigDict(title="Chart.js")
    library: Literal["chartjs"] = "chartjs"
    chart_type: _CJS_TYPES = Field(default="auto", title="Chart type")


Engine = Annotated[
    Union[AutoEngine, VegaLiteEngine, EChartsEngine, ChartjsEngine],
    Field(discriminator="library"),
]


class ChartsConfig(BaseModel):
    theme: Literal["auto", "light", "dark"] = Field(
        default="auto",
        title="Theme",
        description="Chart theme; 'auto' follows the app's light/dark mode.",
    )
    engine: Engine = Field(
        default_factory=AutoEngine,
        title="Chart engine",
        description=(
            "Rendering library and chart type. Selecting a library reveals its chart "
            f"types; leave on 'Auto' to let the model choose. Browse examples: {GALLERY_URL}"
        ),
    )
    count: int = Field(
        default=1,
        ge=1,
        le=6,
        title="Number to generate",
        description="How many to generate; each one uses a different design and emphasis.",
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def _flint_error(library: object, spec: object) -> str | None:
    """Why this Flint input is unusable, or None when it passes.

    Beyond the structural checks (known library, non-empty ``data.values``,
    supported ``chartType``), this rejects the degenerate designs the model
    slips into when the content has nothing quantitative: encodings that
    reference fields absent from the rows, two channels sharing one field
    (an x-duplicating legend), and specs where no encoded field carries
    numeric values (category-vs-category identity grids).
    """
    if library not in LIBRARIES:
        return f"unknown library {library!r}"
    if not isinstance(spec, dict):
        return "input is not an object"
    data = spec.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("values"), list) or not data["values"]:
        return "data.values must be a non-empty list of rows"
    rows = [row for row in data["values"] if isinstance(row, dict)]
    if len(rows) < 2:
        return "at least 2 data rows are required"
    chart_spec = spec.get("chart_spec")
    if not isinstance(chart_spec, dict):
        return "chart_spec is missing"
    chart_type = chart_spec.get("chartType")
    if chart_type not in CHART_TYPES_BY_LIBRARY[library]:
        return f"chartType {chart_type!r} is not valid for {library}"

    encodings = chart_spec.get("encodings")
    if not isinstance(encodings, dict) or not encodings:
        return "chart_spec.encodings is missing"
    goal = encodings.get("goal", {})
    goal_field = str(goal.get("field", "")) if isinstance(goal, dict) else ""
    if "bullet" in str(chart_type).lower() and re.search(r"total|denominator", goal_field, re.I):
        return "A denominator is not a performance target; use a neutral bar or line chart"
    row_keys = set().union(*(row.keys() for row in rows))
    fields: dict = {}
    for channel, enc in encodings.items():
        field = enc.get("field") if isinstance(enc, dict) else None
        if field is None:
            continue
        if field not in row_keys:
            return f"encoding {channel!r} references field {field!r} not present in data rows"
        if field in fields:
            return (
                f"channels {fields[field]!r} and {channel!r} both encode field "
                f"{field!r} — each channel must map to a different field"
            )
        fields[field] = channel
    if not fields:
        return "no encoding references a field"

    def _is_numeric(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    has_measure = any(
        sum(_is_numeric(row.get(field)) for row in rows) >= max(1, len(rows) // 2)
        for field in fields
    )
    if not has_measure:
        return (
            "no encoded field carries numeric values — charts need at least one "
            "real measure, not category-vs-category pairs"
        )
    return None


def _write_source(output_dir: str, spec: dict) -> CreationFile:
    """Write the final Flint input into ``output_dir`` and describe it as the
    artifact's editable source file."""
    (Path(output_dir) / SOURCE_FILENAME).write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return CreationFile(
        filename=SOURCE_FILENAME,
        content_type=SOURCE_CONTENT_TYPE,
        path=SOURCE_FILENAME,
        role="source",
        label="Source",
    )


class ChartCreator(BaseCreator):
    config_model: ClassVar[type] = ChartsConfig

    @property
    def manifest(self) -> CreatorManifest:
        return self.build_manifest(
            key="charts",
            name="Charts",
            version=__version__,
            description="LLM-designed Flint chart (Vega-Lite / ECharts / Chart.js) of the key insight.",
            sdk_compat=">=0.4,<1",
            emits=["flint.v1"],
            model_roles=[
                ModelRoleSpec(
                    key="text",
                    kind="language",
                    requires=["structured_json"],
                    description="LLM that designs the chart.",
                )
            ],
            icon="bar-chart-3",
            view=CreatorView(entry="view/index.html"),
            editable_source=True,
            suggestion_hint=(
                "which quantities, trends, or comparisons to chart, how to break them "
                "down, and which chart form best carries the point"
            ),
        )

    async def generate(self, request: CreationRequest) -> CreationResult:
        cfg = ChartsConfig.model_validate(request.config or {})
        role = request.models.get("text")
        if role is None:
            return CreationResult(
                status="FAILURE",
                schema_id="flint.v1",
                data={},
                errors=[CreationError(phase="setup", message="missing 'text' model role")],
                user_message="No language model was provided for chart generation.",
            )

        # Resolve what the user pinned in the modal (None == "auto", model chooses).
        engine = cfg.engine
        library_pin = None if engine.library == "auto" else engine.library
        chart_type_pin = getattr(engine, "chart_type", "auto")
        chart_type_pin = None if library_pin is None or chart_type_pin == "auto" else chart_type_pin

        prompts = resources.files("chart_creator.prompts")
        template = prompts.joinpath("charts.jinja").read_text()
        flint_syntax = prompts.joinpath("flint_syntax.md").read_text()
        prompt = Prompter(template_text=template).render(
            {
                "content": request.content.text,
                "flint_syntax": flint_syntax,
                "chart_catalog": CHART_CATALOG_MARKDOWN,
                "instructions": request.instructions,
                "library_pin": library_pin,
                "chart_type_pin": chart_type_pin,
            }
        )
        llm = role.create_language(structured={"type": "json"}, max_tokens=6000)

        # One corrective retry: validation failures are fed back verbatim so the
        # model can fix the specific defect instead of re-rolling blind.
        last_error: str | None = None
        for _attempt in range(2):
            ask = prompt if last_error is None else (
                prompt
                + f"\n\nYour previous answer was rejected: {last_error}. "
                + "Return only the corrected JSON."
            )
            resp = await llm.ainvoke(ask)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            try:
                parsed = json.loads(_strip_fences(raw))
            except json.JSONDecodeError as e:
                logger.warning(f"charts: non-JSON response: {e}")
                last_error = f"invalid JSON: {e}"
                continue

            if not isinstance(parsed, dict):
                last_error = "the response was not a JSON object"
                continue

            # The honest way out: content with nothing quantitative yields an
            # explicit decline, not a chart of invented numbers.
            if "chart" in parsed and parsed.get("chart") is None:
                reason = str(parsed.get("reason") or "").strip()
                return CreationResult(
                    status="FAILURE",
                    schema_id="flint.v1",
                    data={},
                    errors=[
                        CreationError(
                            phase="generate",
                            message=f"declined: {reason or 'no chartable quantities'}",
                            retryable=False,
                        )
                    ],
                    user_message=(
                        "This content has no genuine quantities to chart"
                        + (f": {reason}" if reason else ".")
                    ),
                )

            # Enforce the user's pins over whatever the model returned.
            library = library_pin or parsed.get("library")
            spec = parsed.get("input")
            if isinstance(spec, dict) and chart_type_pin and isinstance(spec.get("chart_spec"), dict):
                spec["chart_spec"]["chartType"] = chart_type_pin

            error = _flint_error(library, spec)
            if error:
                logger.warning(f"charts: rejected spec: {error}")
                last_error = error
                continue

            # canvasSize is intentionally NOT defaulted here — the view bundle
            # sizes the chart to its container; a baked 640x400 renders as a
            # tiny fixed chart in the corner of the card.
            spec.setdefault("options", {"addTooltips": True})

            title = parsed.get("title")
            data = {
                "title": title if isinstance(title, str) and title.strip() else None,
                "library": library,
                "input": spec,
                "theme": cfg.theme,
            }
            return CreationResult(
                status="SUCCESS",
                schema_id="flint.v1",
                data=data,
                files=[_write_source(request.output_dir, spec)],
            )

        return CreationResult(
            status="FAILURE",
            schema_id="flint.v1",
            data={},
            errors=[
                CreationError(
                    phase="generate",
                    message=last_error or "no valid chart",
                    retryable=True,
                )
            ],
            user_message="No valid chart could be generated from this content.",
        )

    async def render(self, request: RenderRequest) -> CreationResult:
        """Re-render from the (user-edited) Flint input. Deterministic — no LLM.

        The input goes through the same validation and post-processing as a
        freshly generated one, against the artifact's existing ``library``;
        everything the source does not encode (title, theme, library) is
        carried forward from the previous ``data``."""

        def failure(message: str, user_message: str) -> CreationResult:
            return CreationResult(
                status="FAILURE",
                schema_id="flint.v1",
                data=request.data,
                errors=[CreationError(phase="render", message=message, retryable=False)],
                user_message=user_message,
            )

        source = next((s for s in request.sources if s.filename == SOURCE_FILENAME), None)
        if source is None:
            return failure(
                f"source file '{SOURCE_FILENAME}' not provided",
                f"The chart source ('{SOURCE_FILENAME}') is missing, so it cannot be re-rendered.",
            )

        try:
            spec = json.loads(source.content.strip())
        except json.JSONDecodeError as e:
            return failure(
                f"invalid JSON: {e}",
                f"The edited chart source is not valid JSON: {e}.",
            )

        library = request.data.get("library", FlintV1().library)
        error = _flint_error(library, spec)
        if error:
            return failure(
                f"invalid Flint input: {error}",
                f"The edited chart source is not a valid Flint chart input: {error}.",
            )
        spec.setdefault("options", {"addTooltips": True})

        data = FlintV1.model_validate({**request.data, "input": spec}).model_dump()
        return CreationResult(
            status="SUCCESS",
            schema_id="flint.v1",
            data=data,
            files=[_write_source(request.output_dir, data["input"])],
        )
