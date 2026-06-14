"""Tests for ChartCreator with a stubbed language model (no network)."""

from __future__ import annotations

import json
import tempfile

import pytest
from chart_creator import ChartCreator
from open_notebook_creator_sdk import ContentBundle, CreationRequest, ModelRole
from open_notebook_creator_sdk.testing import assert_creator_compliant, assert_result_compliant


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
async def test_generate_valid_specs():
    creator = ChartCreator()
    payload = {
        "title": "Sales",
        "specs": [
            {"type": "interval", "data": [{"category": "A", "value": 3}], "encode": {"x": "category", "y": "value"}}
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="Some content"),
            config={"max_charts": 3},
            models={"text": _role(payload)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "SUCCESS"
        assert_result_compliant(creator, result)
        assert len(result.data["specs"]) == 1


@pytest.mark.asyncio
async def test_partial_on_some_invalid_specs():
    creator = ChartCreator()
    payload = {
        "title": "Mixed",
        "specs": [
            {"type": "interval", "data": [{"category": "A", "value": 3}]},
            {"type": "nonsense"},          # invalid type
            {"type": "line", "data": []},  # empty data -> invalid
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _role(payload)},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "PARTIAL"
        assert len(result.data["specs"]) == 1
        assert result.warnings


@pytest.mark.asyncio
async def test_failure_when_all_invalid():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _role({"specs": [{"type": "bogus"}]})},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_strips_markdown_fences():
    creator = ChartCreator()
    obj = {"title": "T", "specs": [{"type": "interval", "data": [{"category": "A", "value": 1}]}]}
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
async def test_empty_specs_is_failure():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            models={"text": _role({"specs": []})},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "FAILURE"


@pytest.mark.asyncio
async def test_respects_max_charts():
    creator = ChartCreator()
    specs = [
        {"type": "interval", "data": [{"category": "A", "value": i}]} for i in range(5)
    ]
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(
            content=ContentBundle(text="x"),
            config={"max_charts": 2},
            models={"text": _role({"specs": specs})},
            output_dir=td,
            artifact_id="a",
        )
        result = await creator.generate(req)
        assert result.status == "SUCCESS"
        assert len(result.data["specs"]) == 2


@pytest.mark.asyncio
async def test_no_text_role_is_failure():
    creator = ChartCreator()
    with tempfile.TemporaryDirectory() as td:
        req = CreationRequest(content=ContentBundle(text="x"), output_dir=td, artifact_id="a")
        result = await creator.generate(req)
        assert result.status == "FAILURE"
        assert result.errors[0].phase == "setup"
