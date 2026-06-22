"""Tests for ChartCreator (infographic.v2 / AntV chart DSL) with a stubbed model."""

from __future__ import annotations

import json
import tempfile

import pytest
from chart_creator import ChartCreator
from open_notebook_creator_sdk import ContentBundle, CreationRequest, ModelRole
from open_notebook_creator_sdk.testing import assert_creator_compliant, assert_result_compliant

_SPEC = (
    "infographic chart-column-simple\n"
    "data\n"
    "  title Revenue by region\n"
    "  values\n"
    "    - label North\n"
    "      value 120\n"
    "    - label South\n"
    "      value 90\n"
)


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


def test_static_compliance():
    assert_creator_compliant(ChartCreator())


@pytest.mark.asyncio
async def test_generate_valid_spec():
    creator = ChartCreator()
    payload = {"title": "Sales", "spec": _SPEC}
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="Some content"),
            config={"theme": "auto"},
            models={"text": _role(payload)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "SUCCESS"
        assert_result_compliant(creator, result)
        assert result.schema_id == "infographic.v2"
        assert result.data["spec"].startswith("infographic chart-")
        assert result.data["library"] == "antv-infographic"


@pytest.mark.asyncio
async def test_failure_when_not_a_chart_template():
    creator = ChartCreator()
    # a valid infographic DSL, but a non-chart template -> rejected by charts creator
    payload = {"title": "T", "spec": "infographic list-grid-simple\ndata\n  lists\n    - label x"}
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _role(payload)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_failure_when_spec_missing():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _role({"title": "T"})},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_strips_markdown_fences():
    creator = ChartCreator()
    obj = {"title": "T", "spec": _SPEC}
    fenced = "```json\n" + json.dumps(obj) + "\n```"
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _FakeRole(provider="f", model="f", payload=fenced)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "SUCCESS"
        assert result.data["title"] == "T"


@pytest.mark.asyncio
async def test_no_text_role_is_failure():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(content=ContentBundle(text="x"), output_dir=td, artifact_id="a")
        result = await creator.generate(req)
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "setup"


def test_manifest_declares_view_bundle_and_it_ships():
    """The creator owns its UI: the manifest points at a shipped HTML view bundle
    that renders both the current and the legacy schema, fully offline."""
    from importlib import resources

    m = ChartCreator().manifest
    assert m.view is not None
    assert m.view.entry == "view/index.html"
    asset = resources.files("chart_creator").joinpath(m.view.entry)
    assert asset.is_file()
    html = asset.read_text()
    # self-contained + speaks the host handshake + dispatches both schemas
    assert "open-notebook:ready" in html
    assert "open-notebook:artifact" in html
    assert "infographic.v2" in html
    assert "chart_spec.v1" in html  # legacy artifacts still render
    # vendored offline: inline <script> blocks are fine, but nothing loads remotely
    assert 'src="http' not in html
