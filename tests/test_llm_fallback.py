"""Phase 17.4 — tests for the tool-use → complete()+JSON fallback.

Pure unit tests with full SDK client mocking — no network calls.
Cover the resilience path Phase 17.4 added: when the primary
tool-use call returns no tool block (Anthropic) or no tool_call /
wrong name / parse-fail (Marítaca), the wrapper retries once via
`complete()` with a JSON-mode prompt; on success, sets
`last_call_used_fallback = True` and emits the
`llm.tool_use_fallback` structured log event.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag_leis.llm import (
    AnthropicLLM,
    _build_fallback_prompt,
    _parse_fallback_json,
)


# ---------------------------------------------------------------------------
# Helpers — fabricate SDK response objects without touching network.
# ---------------------------------------------------------------------------


class _FakeUsage(SimpleNamespace):
    """Mimics anthropic.types.Usage with input/output token counts."""


def _fake_anthropic_resp(
    *, content: list, stop_reason: str = "end_turn",
    input_tokens: int = 10, output_tokens: int = 20,
):
    """Build a duck-typed response matching the bits AnthropicLLM reads:
    `.content`, `.stop_reason`, `.usage.{input,output}_tokens`."""
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=_FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _fake_tool_use_block(name: str, input_dict: dict):
    """Duck-types `anthropic.types.ToolUseBlock` enough for isinstance
    checks — we patch the import path so the real class is what
    `isinstance` compares against."""
    from anthropic.types import ToolUseBlock
    return ToolUseBlock(type="tool_use", id="t_1", name=name, input=input_dict)


def _fake_text_block(text: str):
    from anthropic.types import TextBlock
    return TextBlock(type="text", text=text, citations=None)


# ---------------------------------------------------------------------------
# Pure helpers — fallback prompt + JSON parsing
# ---------------------------------------------------------------------------


def test_fallback_prompt_embeds_schema():
    """The fallback prompt must (a) include the original user message
    and (b) embed the input_schema verbatim so the model has the same
    target shape as the tool path."""
    schema = {
        "name": "answer_tool",
        "input_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    }
    out = _build_fallback_prompt(schema, original_user="Original Q")
    assert "Original Q" in out
    assert "answer" in out
    # The schema fragment must be intact (allows the model to satisfy it).
    assert '"required"' in out
    # Defensive — instruction must say "JSON only", no fences.
    assert "JSON" in out
    assert "```json fences" in out  # the negative instruction is in there


def test_parse_fallback_json_clean_object():
    assert _parse_fallback_json('{"answer": "hi", "citations": []}') == {
        "answer": "hi", "citations": [],
    }


def test_parse_fallback_json_strips_code_fence():
    """Models often wrap JSON in ```json … ``` despite instructions."""
    raw = '```json\n{"answer": "hi"}\n```'
    assert _parse_fallback_json(raw) == {"answer": "hi"}


def test_parse_fallback_json_strips_prose_prefix():
    """Models sometimes prepend 'Aqui está:' or similar — the parser
    finds the first `{` and starts from there."""
    raw = "Claro, aqui está o JSON solicitado:\n{\"answer\": \"hi\"}"
    assert _parse_fallback_json(raw) == {"answer": "hi"}


def test_parse_fallback_json_rejects_non_object():
    """A bare string/array/number doesn't satisfy the tool's input
    schema (always `type: object`). Both the "no `{` found" and the
    "JSON parsed but not an object" branches are valid rejections;
    we just need to confirm SOMETHING raises."""
    with pytest.raises(RuntimeError):
        _parse_fallback_json('"just a string"')
    with pytest.raises(RuntimeError):
        _parse_fallback_json("[1, 2, 3]")


def test_parse_fallback_json_rejects_no_json():
    with pytest.raises(RuntimeError, match="no JSON object"):
        _parse_fallback_json("não tem JSON aqui")


def test_parse_fallback_json_rejects_malformed():
    with pytest.raises(RuntimeError, match="JSON parse failed"):
        _parse_fallback_json('{"answer": ')


# ---------------------------------------------------------------------------
# AnthropicLLM end-to-end — primary tool-use missing → fallback succeeds
# ---------------------------------------------------------------------------


SAMPLE_TOOL = {
    "name": "answer_tool",
    "description": "Submeta uma resposta.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "citations"],
    },
}


def _patch_client(llm: AnthropicLLM, primary_resp, fallback_resp=None):
    """Replace llm.client.messages.create with a side_effect that
    serves `primary_resp` first, `fallback_resp` second (if provided).
    """
    mock = MagicMock()
    if fallback_resp is None:
        mock.side_effect = [primary_resp]
    else:
        mock.side_effect = [primary_resp, fallback_resp]
    llm.client = MagicMock(messages=MagicMock(create=mock))


def _make_anthropic_llm(monkeypatch) -> AnthropicLLM:
    """Construct an AnthropicLLM with a fake API key so __init__
    doesn't fail when the local .env isn't loaded (e.g., CI)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    return AnthropicLLM(model="claude-test")


def test_primary_tool_use_succeeds_no_fallback(monkeypatch):
    """Happy path: primary returns a tool_use block → no fallback path,
    `last_call_used_fallback` stays False."""
    llm = _make_anthropic_llm(monkeypatch)
    primary = _fake_anthropic_resp(content=[
        _fake_tool_use_block("answer_tool", {"answer": "ok", "citations": []}),
    ])
    _patch_client(llm, primary)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "ok", "citations": []}
    assert llm.last_call_used_fallback is False
    # Only the primary call should have run.
    assert llm.client.messages.create.call_count == 1


def test_primary_missing_tool_use_triggers_fallback(monkeypatch):
    """Primary returns ONLY text blocks (no tool_use). Wrapper must
    fall back to complete() + parse, and set last_call_used_fallback."""
    llm = _make_anthropic_llm(monkeypatch)
    primary = _fake_anthropic_resp(
        content=[_fake_text_block("Acho que a resposta é…")],
        stop_reason="end_turn",
        input_tokens=10, output_tokens=5,
    )
    fallback = _fake_anthropic_resp(
        content=[_fake_text_block('{"answer": "fallback ok", "citations": ["urn:x"]}')],
        stop_reason="end_turn",
        input_tokens=20, output_tokens=8,
    )
    _patch_client(llm, primary, fallback)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "fallback ok", "citations": ["urn:x"]}
    assert llm.last_call_used_fallback is True
    # Both calls should have run.
    assert llm.client.messages.create.call_count == 2
    # Token accounting must include BOTH primary + fallback.
    assert llm.last_call_usage == {
        "input_tokens": 10 + 20, "output_tokens": 5 + 8,
    }


def test_primary_missing_and_fallback_unparseable_raises(monkeypatch):
    """If primary tool-use missing AND fallback returns garbage that
    doesn't parse as JSON, raise — operator sees combined failure."""
    llm = _make_anthropic_llm(monkeypatch)
    primary = _fake_anthropic_resp(
        content=[_fake_text_block("…")], stop_reason="max_tokens",
    )
    fallback = _fake_anthropic_resp(
        content=[_fake_text_block("desculpa, não consigo")],
        stop_reason="end_turn",
    )
    _patch_client(llm, primary, fallback)

    with pytest.raises(RuntimeError) as exc_info:
        llm.complete_structured(
            system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
        )
    # Error message includes BOTH signals.
    assert "did not return a tool_use block" in str(exc_info.value)
    assert "Fallback complete()+JSON also failed" in str(exc_info.value)
    assert llm.last_call_used_fallback is False  # never flipped on failure


def test_fallback_strips_markdown_fence_on_real_response(monkeypatch):
    """Real-world failure mode: model wraps JSON in ```json … ```
    despite the instruction not to. The fallback parse must handle it."""
    llm = _make_anthropic_llm(monkeypatch)
    primary = _fake_anthropic_resp(content=[])
    fallback = _fake_anthropic_resp(content=[
        _fake_text_block('```json\n{"answer": "fenced", "citations": []}\n```'),
    ])
    _patch_client(llm, primary, fallback)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "fenced", "citations": []}
    assert llm.last_call_used_fallback is True


# ---------------------------------------------------------------------------
# MaritacaLLM — three failure surfaces, same fallback
# ---------------------------------------------------------------------------


def _make_maritaca_llm(monkeypatch):
    from rag_leis.maritaca import MaritacaLLM
    monkeypatch.setenv("MARITACA_API_KEY", "test-key-not-real")
    return MaritacaLLM(model="sabia-test")


def _fake_openai_resp(*, tool_call=None, finish_reason: str = "stop",
                      content: str | None = None,
                      prompt_tokens: int = 5, completion_tokens: int = 7,
                      text_for_fallback: str | None = None):
    """Build a duck-typed openai-compat ChatCompletion response.

    `tool_call` is a (name, arguments_str) tuple or None for "no
    tool_call". `text_for_fallback` populates `choices[0].message.content`
    on a subsequent `complete()` call.
    """
    if tool_call is not None:
        tc = SimpleNamespace(
            function=SimpleNamespace(name=tool_call[0], arguments=tool_call[1])
        )
        tool_calls = [tc]
    else:
        tool_calls = None
    msg = SimpleNamespace(tool_calls=tool_calls, content=content)
    if text_for_fallback is not None:
        msg.content = text_for_fallback
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _patch_maritaca_client(llm, primary, fallback=None):
    mock = MagicMock()
    if fallback is None:
        mock.side_effect = [primary]
    else:
        mock.side_effect = [primary, fallback]
    llm.client = MagicMock(chat=MagicMock(completions=MagicMock(create=mock)))


def test_maritaca_no_tool_call_triggers_fallback(monkeypatch):
    """Marítaca returns no tool_call → fallback to JSON parse."""
    llm = _make_maritaca_llm(monkeypatch)
    primary = _fake_openai_resp(tool_call=None, finish_reason="stop", content=None)
    fallback = _fake_openai_resp(
        tool_call=None, text_for_fallback='{"answer": "via fallback", "citations": []}',
    )
    _patch_maritaca_client(llm, primary, fallback)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "via fallback", "citations": []}
    assert llm.last_call_used_fallback is True


def test_maritaca_wrong_tool_name_triggers_fallback(monkeypatch):
    """Marítaca returns a tool_call for a DIFFERENT tool — semantically
    wrong, recoverable via fallback."""
    llm = _make_maritaca_llm(monkeypatch)
    primary = _fake_openai_resp(
        tool_call=("not_my_tool", '{"x": 1}'), finish_reason="tool_calls",
    )
    fallback = _fake_openai_resp(
        text_for_fallback='{"answer": "ok via fallback", "citations": []}',
    )
    _patch_maritaca_client(llm, primary, fallback)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "ok via fallback", "citations": []}
    assert llm.last_call_used_fallback is True


def test_maritaca_invalid_json_arguments_triggers_fallback(monkeypatch):
    """Marítaca returns the right tool_call but with unparseable JSON
    in `arguments` — the third failure surface 17.4 recovers from."""
    llm = _make_maritaca_llm(monkeypatch)
    primary = _fake_openai_resp(
        tool_call=("answer_tool", '{"answer": not-json'),
        finish_reason="tool_calls",
    )
    fallback = _fake_openai_resp(
        text_for_fallback='{"answer": "rescued", "citations": []}',
    )
    _patch_maritaca_client(llm, primary, fallback)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "rescued", "citations": []}
    assert llm.last_call_used_fallback is True


def test_maritaca_clean_tool_call_no_fallback(monkeypatch):
    """Happy path: well-formed tool_call → no fallback fires."""
    llm = _make_maritaca_llm(monkeypatch)
    primary = _fake_openai_resp(
        tool_call=("answer_tool", '{"answer": "clean", "citations": []}'),
        finish_reason="tool_calls",
    )
    _patch_maritaca_client(llm, primary)

    out = llm.complete_structured(
        system="s", user="u", tool_schema=SAMPLE_TOOL, max_tokens=512,
    )
    assert out == {"answer": "clean", "citations": []}
    assert llm.last_call_used_fallback is False
    assert llm.client.chat.completions.create.call_count == 1
