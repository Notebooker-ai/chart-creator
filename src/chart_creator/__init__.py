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
from typing import Annotated, ClassVar, Literal, Union

from ai_prompter import Prompter
from loguru import logger
from open_notebook_creator_sdk import (
    BaseCreator,
    CreationError,
    CreationRequest,
    CreationResult,
    CreatorManifest,
    CreatorView,
    ModelRoleSpec,
)
from pydantic import BaseModel, ConfigDict, Field

from .chart_types import (
    CHART_CATALOG_MARKDOWN,
    CHART_TYPES_BY_LIBRARY,
    CHARTJS_TYPES,
    ECHARTS_TYPES,
    VEGA_LITE_TYPES,
)

__version__ = "0.4.0"

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


def _valid_flint(library: object, spec: object) -> bool:
    """A usable Flint artifact: a known library plus a ``{data.values, chart_spec.chartType}``
    input whose chart type is one the chosen library supports."""
    if library not in LIBRARIES or not isinstance(spec, dict):
        return False
    data = spec.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("values"), list) or not data["values"]:
        return False
    chart_spec = spec.get("chart_spec")
    if not isinstance(chart_spec, dict):
        return False
    chart_type = chart_spec.get("chartType")
    return chart_type in CHART_TYPES_BY_LIBRARY[library]


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
        resp = await llm.ainvoke(prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        try:
            parsed = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            logger.error(f"charts: non-JSON response: {e}")
            return CreationResult(
                status="FAILURE",
                schema_id="flint.v1",
                data={},
                errors=[CreationError(phase="parse", message=f"invalid JSON: {e}", retryable=True)],
                user_message="The model returned an unparseable response. Please retry.",
            )

        if not isinstance(parsed, dict):
            return self._invalid_result()

        # Enforce the user's pins over whatever the model returned.
        library = library_pin or parsed.get("library")
        spec = parsed.get("input")
        if isinstance(spec, dict) and chart_type_pin and isinstance(spec.get("chart_spec"), dict):
            spec["chart_spec"]["chartType"] = chart_type_pin

        if not _valid_flint(library, spec):
            return self._invalid_result()

        # Fill client-side rendering defaults the model may omit.
        chart_spec = spec["chart_spec"]
        chart_spec.setdefault("canvasSize", {"width": 640, "height": 400})
        spec.setdefault("options", {"addTooltips": True})

        title = parsed.get("title")
        data = {
            "title": title if isinstance(title, str) and title.strip() else None,
            "library": library,
            "input": spec,
            "theme": cfg.theme,
        }
        return CreationResult(status="SUCCESS", schema_id="flint.v1", data=data)

    @staticmethod
    def _invalid_result() -> CreationResult:
        return CreationResult(
            status="FAILURE",
            schema_id="flint.v1",
            data={},
            errors=[CreationError(phase="generate", message="no valid chart", retryable=True)],
            user_message="No valid chart could be generated from this content.",
        )
