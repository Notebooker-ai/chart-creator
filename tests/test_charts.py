"""Tests for ChartCreator (flint.v1 / Flint chart input) with a stubbed model."""

from __future__ import annotations

import json
import tempfile

import pytest
from chart_creator import ChartCreator
from open_notebook_creator_sdk import ContentBundle, CreationRequest, ModelRole
from open_notebook_creator_sdk.testing import assert_creator_compliant, assert_result_compliant

_PAYLOAD = {
    "title": "Revenue by region",
    "library": "vega-lite",
    "input": {
        "data": {"values": [{"region": "North", "revenue": 120}, {"region": "South", "revenue": 90}]},
        "semantic_types": {"region": "Category", "revenue": "Quantity"},
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "region"}, "y": {"field": "revenue"}},
        },
    },
}


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, _):
        return _FakeResp(self._payload)


class _FakeRole(ModelRole):
    payload: str = ""

    def create_language(self, **_):
        return _FakeLLM(self.payload)


def _role(obj):
    return _FakeRole(provider="f", model="f", payload=json.dumps(obj))


def _req(payload, config=None, **kw):
    return CreationRequest(
        content=ContentBundle(text="Some content"),
        config=config or {},
        models={"text": _role(payload)},
        **kw,
    )


def test_static_compliance():
    assert_creator_compliant(ChartCreator())


@pytest.mark.asyncio
async def test_generate_valid_flint():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(_PAYLOAD, {"theme": "auto"}, output_dir=td, artifact_id="a"))
        assert result.status == "SUCCESS"
        assert_result_compliant(creator, result)
        assert result.schema_id == "flint.v1"
        assert result.data["library"] == "vega-lite"
        assert result.data["input"]["chart_spec"]["chartType"] == "Bar Chart"
        # rendering defaults are filled in for the view bundle
        assert "canvasSize" in result.data["input"]["chart_spec"]
        assert result.data["theme"] == "auto"


@pytest.mark.asyncio
async def test_config_pins_override_model_choice():
    """When the user pins a library + chart type in the modal, those win over the model."""
    creator = ChartCreator()
    cfg = {"theme": "dark", "engine": {"library": "echarts", "chart_type": "Line Chart"}}
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(_PAYLOAD, cfg, output_dir=td, artifact_id="a"))
        assert result.status == "SUCCESS"
        assert result.data["library"] == "echarts"
        assert result.data["input"]["chart_spec"]["chartType"] == "Line Chart"
        assert result.data["theme"] == "dark"


@pytest.mark.asyncio
async def test_auto_passthrough_keeps_model_choice():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(_PAYLOAD, {}, output_dir=td, artifact_id="a"))
        assert result.status == "SUCCESS"
        assert result.data["library"] == "vega-lite"
        assert result.data["input"]["chart_spec"]["chartType"] == "Bar Chart"


@pytest.mark.asyncio
async def test_failure_when_chart_type_unknown_for_library():
    creator = ChartCreator()
    bad = json.loads(json.dumps(_PAYLOAD))
    bad["input"]["chart_spec"]["chartType"] = "Not A Real Chart"
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(bad, {}, output_dir=td, artifact_id="a"))
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_failure_when_input_missing():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req({"title": "T", "library": "vega-lite"}, {}, output_dir=td, artifact_id="a"))
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_strips_markdown_fences():
    creator = ChartCreator()
    fenced = "```json\n" + json.dumps(_PAYLOAD) + "\n```"
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _FakeRole(provider="f", model="f", payload=fenced)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "SUCCESS"
        assert result.data["title"] == "Revenue by region"


@pytest.mark.asyncio
async def test_no_text_role_is_failure():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(content=ContentBundle(text="x"), output_dir=td, artifact_id="a")
        result = await creator.generate(req)
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "setup"


def test_config_schema_cascades_library_to_chart_type():
    """The creation modal is driven by this schema: a discriminated oneOf on library,
    each branch carrying its own chart-type enum, plus a gallery link."""
    from chart_creator import ChartsConfig

    schema = ChartsConfig.model_json_schema()
    engine = schema["properties"]["engine"]
    assert "discriminator" in engine and "oneOf" in engine
    assert set(engine["discriminator"]["mapping"]) == {"auto", "vega-lite", "echarts", "chartjs"}
    assert "microsoft.github.io/flint-chart" in engine["description"]
    vl = schema["$defs"]["VegaLiteEngine"]["properties"]["chart_type"]["enum"]
    assert "auto" in vl and "Bar Chart" in vl


def test_manifest_declares_view_bundle_and_it_ships():
    """The creator owns its UI: the manifest points at a shipped, self-contained HTML
    view bundle that renders flint.v1 across all three backends, fully offline."""
    from importlib import resources

    m = ChartCreator().manifest
    assert m.view is not None
    assert m.view.entry == "view/index.html"
    assert m.emits == ["flint.v1"]
    asset = resources.files("chart_creator").joinpath(m.view.entry)
    assert asset.is_file()
    html = asset.read_text()
    # self-contained + speaks the host handshake + renders the flint.v1 schema
    assert "open-notebook:ready" in html
    assert "open-notebook:artifact" in html
    assert "flint.v1" in html
    # all three renderers are bundled
    for lib in ("vega", "echarts", "chart"):
        assert lib in html.lower()
    # vendored offline: inline <script> blocks are fine, but nothing loads remotely
    assert 'src="http' not in html
