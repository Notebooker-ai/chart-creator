"""chart-creator: an Open Notebook creator that turns notebook content into a chart.

The LLM designs it as an AntV Infographic DSL string using the ``chart-*`` templates
(line / column / bar / pie / wordcloud), emitted as ``infographic.v2`` and rendered
client-side to SVG by the ``@antv/infographic`` engine. Non-chart infographic
templates are produced by infographic-creator. Earlier versions emitted raw AntV G2
specs as ``chart_spec.v1``.
"""

import json
import re
from importlib import resources
from typing import ClassVar, Literal

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
from open_notebook_creator_sdk.schemas import InfographicV2
from pydantic import BaseModel, Field

__version__ = "0.3.0"


class ChartsConfig(BaseModel):
    # AntV Infographic theme applied client-side. "auto" follows the app's
    # light/dark mode; "hand-drawn" is a sketchy preset. The DSL's own palette
    # still layers colour on top of the base theme.
    theme: Literal["auto", "light", "dark", "hand-drawn"] = Field(
        default="auto", description="Chart theme"
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


def _valid_spec(spec: object) -> bool:
    """A usable AntV chart DSL: a non-empty string whose first non-blank line is
    ``infographic chart-...``. The DSL is the contract; validation stays loose so
    new AntV chart templates need no code change."""
    if not isinstance(spec, str):
        return False
    for line in spec.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped.startswith("infographic chart-")
    return False


class ChartCreator(BaseCreator):
    config_model: ClassVar[type] = ChartsConfig

    @property
    def manifest(self) -> CreatorManifest:
        return self.build_manifest(
            key="charts",
            name="Charts",
            version=__version__,
            description="LLM-designed AntV chart of the key quantitative insight.",
            sdk_compat=">=0.4,<1",
            emits=["infographic.v2"],
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
        )

    async def generate(self, request: CreationRequest) -> CreationResult:
        cfg = ChartsConfig.model_validate(request.config)
        role = request.models.get("text")
        if role is None:
            return CreationResult(
                status="FAILURE",
                schema_id="infographic.v2",
                data={},
                errors=[CreationError(phase="setup", message="missing 'text' model role")],
                user_message="No language model was provided for chart generation.",
            )

        prompts = resources.files("chart_creator.prompts")
        template = prompts.joinpath("charts.jinja").read_text()
        antv_syntax = prompts.joinpath("antv_syntax.md").read_text()
        prompt = Prompter(template_text=template).render(
            {
                "content": request.content.text,
                "antv_syntax": antv_syntax,
                "instructions": request.instructions,
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
                schema_id="infographic.v2",
                data={},
                errors=[CreationError(phase="parse", message=f"invalid JSON: {e}", retryable=True)],
                user_message="The model returned an unparseable response. Please retry.",
            )

        spec = parsed.get("spec") if isinstance(parsed, dict) else None
        if not _valid_spec(spec):
            return CreationResult(
                status="FAILURE",
                schema_id="infographic.v2",
                data={},
                errors=[CreationError(phase="generate", message="no valid chart spec", retryable=True)],
                user_message="No valid chart could be generated from this content.",
            )

        title = parsed.get("title")
        data = InfographicV2(
            title=title if isinstance(title, str) and title.strip() else None,
            spec=spec.strip(),
            theme=cfg.theme,
        ).model_dump()

        return CreationResult(
            status="SUCCESS",
            schema_id="infographic.v2",
            data=data,
        )
