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
        # canvasSize is left to the view bundle, which sizes to its container —
        # a baked default rendered as a tiny fixed chart in the card's corner.
        assert "canvasSize" not in result.data["input"]["chart_spec"]
        assert result.data["input"]["options"] == {"addTooltips": True}
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


class _SequenceRole(ModelRole):
    """Returns each payload in turn — for exercising the corrective retry."""

    payloads: list = []

    def create_language(self, **_):
        payloads = list(self.payloads)

        class _LLM:
            async def ainvoke(self, _prompt):
                return _FakeResp(payloads.pop(0) if len(payloads) > 1 else payloads[0])

        return _LLM()


def _seq_req(payloads, **kw):
    return CreationRequest(
        content=ContentBundle(text="Some content"),
        config={},
        models={"text": _SequenceRole(provider="f", model="f", payloads=[json.dumps(p) for p in payloads])},
        **kw,
    )


@pytest.mark.asyncio
async def test_decline_when_content_has_no_quantities():
    """The honest way out: {"chart": null, "reason": ...} fails cleanly instead
    of charting invented numbers."""
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(
            _req({"chart": None, "reason": "The content is narrative history with no figures."}, {},
                 output_dir=td, artifact_id="a")
        )
        assert result.status == "FAILURE"
        assert result.errors[0].retryable is False
        assert "narrative history" in result.user_message


@pytest.mark.asyncio
async def test_rejects_encoding_field_missing_from_rows():
    creator = ChartCreator()
    bad = json.loads(json.dumps(_PAYLOAD))
    bad["input"]["chart_spec"]["encodings"]["y"] = {"field": "innovation"}
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(bad, {}, output_dir=td, artifact_id="a"))
        assert result.status == "FAILURE"
        assert "innovation" in result.errors[0].message


@pytest.mark.asyncio
async def test_rejects_duplicate_field_across_channels():
    """A color legend duplicating the x axis carries no information."""
    creator = ChartCreator()
    bad = json.loads(json.dumps(_PAYLOAD))
    bad["input"]["chart_spec"]["encodings"]["color"] = {"field": "region"}
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(bad, {}, output_dir=td, artifact_id="a"))
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_rejects_category_only_encodings():
    """Category-vs-category grids with no numeric measure are junk."""
    creator = ChartCreator()
    bad = {
        "title": "Wars by duration",
        "library": "vega-lite",
        "input": {
            "data": {"values": [
                {"conflict": "Kitos War", "duration": "115-117 AD"},
                {"conflict": "Bar Kokhba", "duration": "132-136 AD"},
            ]},
            "semantic_types": {"conflict": "Category", "duration": "Category"},
            "chart_spec": {
                "chartType": "Bar Chart",
                "encodings": {"x": {"field": "conflict"}, "y": {"field": "duration"}},
            },
        },
    }
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(bad, {}, output_dir=td, artifact_id="a"))
        assert result.status == "FAILURE"
        assert "numeric" in result.errors[0].message


@pytest.mark.asyncio
async def test_corrective_retry_recovers_from_bad_first_attempt():
    """The validation error is fed back and the second attempt succeeds."""
    creator = ChartCreator()
    bad = json.loads(json.dumps(_PAYLOAD))
    bad["input"]["chart_spec"]["encodings"]["y"] = {"field": "missing_field"}
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_seq_req([bad, _PAYLOAD], output_dir=td, artifact_id="a"))
        assert result.status == "SUCCESS"
        assert result.data["input"]["chart_spec"]["encodings"]["y"] == {"field": "revenue"}


# --- editable source + render -------------------------------------------------

from pathlib import Path  # noqa: E402

from open_notebook_creator_sdk import RenderRequest, SourceDoc  # noqa: E402

_SOURCE_NAME = "chart.json"


def test_manifest_declares_editable_source():
    m = ChartCreator().manifest
    assert m.editable_source is True


@pytest.mark.asyncio
async def test_generate_attaches_source_file_with_flint_input():
    """The final Flint input is written to output_dir as JSON and declared as a
    role='source' file so the host can offer edit -> re-render."""
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        result = await creator.generate(_req(_PAYLOAD, {}, output_dir=td, artifact_id="a"))
        assert result.status == "SUCCESS"
        assert_result_compliant(creator, result)
        sources = [f for f in result.files if f.role == "source"]
        assert len(sources) == 1
        src = sources[0]
        assert src.filename == _SOURCE_NAME
        assert src.path == _SOURCE_NAME
        assert src.content_type == "application/json"
        assert src.label == "Source"
        assert json.loads((Path(td) / src.path).read_text()) == result.data["input"]


def _render_req(td: str, sources: list, data: dict) -> RenderRequest:
    return RenderRequest(sources=sources, data=data, output_dir=td, artifact_id="a")


def _source(content: str) -> SourceDoc:
    return SourceDoc(filename=_SOURCE_NAME, content_type="application/json", content=content)


def _previous() -> dict:
    return {
        "library": "vega-lite",
        "title": "Revenue by region",
        "input": {**_PAYLOAD["input"], "options": {"addTooltips": True}},
        "theme": "dark",
    }


@pytest.mark.asyncio
async def test_render_with_edited_input_updates_data_and_carries_fields():
    creator = ChartCreator()
    edited = json.loads(json.dumps(_PAYLOAD["input"]))
    edited["data"]["values"].append({"region": "East", "revenue": 42})
    edited["chart_spec"]["chartType"] = "Line Chart"
    text = json.dumps(edited, indent=2)
    with tempfile.TemporaryDirectory() as td:
        # The host writes the edited source into output_dir before render.
        (Path(td) / _SOURCE_NAME).write_text(text)
        result = await creator.render(_render_req(td, [_source(text)], _previous()))
        assert result.status == "SUCCESS", result.errors
        assert_result_compliant(creator, result)
        assert result.schema_id == "flint.v1"
        assert result.data["input"]["chart_spec"]["chartType"] == "Line Chart"
        assert len(result.data["input"]["data"]["values"]) == 3
        # generate()'s post-processing applies to edited sources too.
        assert result.data["input"]["options"] == {"addTooltips": True}
        assert result.data["title"] == "Revenue by region"
        assert result.data["theme"] == "dark"
        assert result.data["library"] == "vega-lite"
        # The source is re-declared so the host keeps it for the next edit,
        # and what sits on disk is the processed input.
        sources = [f for f in result.files if f.role == "source"]
        assert [f.filename for f in sources] == [_SOURCE_NAME]
        assert json.loads((Path(td) / _SOURCE_NAME).read_text()) == result.data["input"]


@pytest.mark.asyncio
async def test_render_rejects_invalid_flint_input():
    creator = ChartCreator()
    bad = json.loads(json.dumps(_PAYLOAD["input"]))
    bad["chart_spec"]["chartType"] = "Not A Real Chart"
    text = json.dumps(bad)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / _SOURCE_NAME).write_text(text)
        result = await creator.render(_render_req(td, [_source(text)], _previous()))
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "render"
        assert result.errors[0].retryable is False
        assert "Not A Real Chart" in result.errors[0].message
        assert "not a valid Flint chart input" in result.user_message
        # Previous data is handed back untouched so the host can keep it.
        assert result.data == _previous()


@pytest.mark.asyncio
async def test_render_rejects_malformed_json():
    creator = ChartCreator()
    text = '{"data": {"values": [}'
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / _SOURCE_NAME).write_text(text)
        result = await creator.render(_render_req(td, [_source(text)], _previous()))
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "render"
        assert "JSON" in result.user_message


@pytest.mark.asyncio
async def test_render_without_source_is_failure():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = _render_req(
            td,
            [SourceDoc(filename="other.txt", content_type="text/plain", content="x")],
            _previous(),
        )
        result = await creator.render(req)
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "render"
        assert _SOURCE_NAME in result.user_message
