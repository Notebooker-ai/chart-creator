"""chart-creator: an Open Notebook creator that turns notebook content into
AntV G2 chart specs (emitted as ``chart_spec.v1``, rendered client-side).
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
    ModelRoleSpec,
)
from open_notebook_creator_sdk.schemas import ChartSpecV1
from pydantic import BaseModel, Field

__version__ = "0.1.1"

_ALLOWED_TYPES = {"interval", "line", "point", "area", "bar", "rect", "cell", "text"}


class ChartsConfig(BaseModel):
    max_charts: int = Field(default=3, ge=1, le=8, description="Maximum charts to generate")
    # Visual theme applied to the rendered AntV chart (client-side). "auto" follows
    # the app's light/dark mode. Values map to G2's official theme names.
    theme: Literal[
        "auto", "light", "dark", "classic", "classicDark", "academy"
    ] = Field(default="auto", description="Chart theme")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return text.strip()


def _valid_spec(spec: object) -> bool:
    if not isinstance(spec, dict):
        return False
    t = spec.get("type")
    if not isinstance(t, str) or t not in _ALLOWED_TYPES:
        return False
    data = spec.get("data")
    return isinstance(data, list) and len(data) > 0


class ChartCreator(BaseCreator):
    config_model: ClassVar[type] = ChartsConfig

    @property
    def manifest(self) -> CreatorManifest:
        return self.build_manifest(
            key="charts",
            name="Charts",
            version=__version__,
            description="LLM-generated AntV charts rendered in the browser.",
            sdk_compat=">=0.1,<1",
            emits=["chart_spec.v1"],
            model_roles=[
                ModelRoleSpec(
                    key="text",
                    kind="language",
                    requires=["structured_json"],
                    description="LLM that designs the chart specs.",
                )
            ],
            icon="bar-chart-3",
        )

    async def generate(self, request: CreationRequest) -> CreationResult:
        cfg = ChartsConfig.model_validate(request.config)
        role = request.models.get("text")
        if role is None:
            return CreationResult(
                status="FAILURE",
                schema_id="chart_spec.v1",
                data={},
                errors=[CreationError(phase="setup", message="missing 'text' model role")],
                user_message="No language model was provided for chart generation.",
            )

        template = resources.files("chart_creator.prompts").joinpath(
            "charts.jinja"
        ).read_text()
        prompt = Prompter(template_text=template).render(
            {
                "content": request.content.text,
                "max_charts": cfg.max_charts,
                "instructions": request.instructions,
            }
        )
        llm = role.create_language(structured={"type": "json"}, max_tokens=4000)
        resp = await llm.ainvoke(prompt)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        try:
            parsed = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            logger.error(f"charts: non-JSON response: {e}")
            return CreationResult(
                status="FAILURE",
                schema_id="chart_spec.v1",
                data={},
                errors=[CreationError(phase="parse", message=f"invalid JSON: {e}", retryable=True)],
                user_message="The model returned an unparseable response. Please retry.",
            )

        all_specs = parsed.get("specs", []) if isinstance(parsed, dict) else []
        good = [s for s in all_specs if _valid_spec(s)]
        dropped = len(all_specs) - len(good)
        good = good[: cfg.max_charts]

        warnings: list[str] = []
        errors: list[CreationError] = []
        if dropped > 0:
            warnings.append(f"Dropped {dropped} invalid chart spec(s).")
            errors.append(CreationError(phase="validate", message=f"{dropped} invalid specs"))

        if not good:
            return CreationResult(
                status="FAILURE",
                schema_id="chart_spec.v1",
                data={},
                warnings=warnings,
                errors=errors or [CreationError(phase="generate", message="no valid charts")],
                user_message="No valid charts could be generated from this content.",
            )

        data = ChartSpecV1(
            title=parsed.get("title") if isinstance(parsed, dict) else None,
            specs=good,
        ).model_dump()

        return CreationResult(
            status="PARTIAL" if errors else "SUCCESS",
            schema_id="chart_spec.v1",
            data=data,
            warnings=warnings,
            errors=errors,
        )
