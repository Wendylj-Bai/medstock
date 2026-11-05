"""
Tests for Ask MedStock (assistant.py). Every AI provider (Gemini by default, Anthropic as a fallback) is
replaced by a scripted fake, so these tests cost nothing, need no API key, never call a real API and never
touch your real data.
"""

import json
from datetime import datetime
from types import SimpleNamespace as NS

import pytest

import assistant
import db
import planning
import purchasing as pu


@pytest.fixture
def ctx(tmp_path):
    conn = db.connect(tmp_path / "ai.db")
    today = db.today(conn)
    items, usage, deliveries, open_pos, lots = db.load_frames(conn, today)
    plan = planning.build_plan(items, usage, deliveries, open_pos=open_pos)
    plan = plan.join(pu.order_vendors(conn, plan, today))
    yield assistant.Context(conn, today, plan, lots=lots, po_list=pu.orders(conn, today))
    conn.close()


def usage(i=1000, o=200):
    return NS(input_tokens=i, output_tokens=o, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def text_reply(text):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=usage())


def tool_reply(name, tool_input, call_id="call_1"):
    return NS(content=[NS(type="tool_use", id=call_id, name=name, input=tool_input)], stop_reason="tool_use",
              usage=usage())


class FakeClient:
    """Plays back scripted responses and records every request."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs.get("messages", []))})   # snapshot
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def stock(conn):
    return conn.execute("SELECT COALESCE(SUM(qty), 0) FROM lots").fetchone()[0]


# --- Tools -------------------------------------------------------------------

@pytest.mark.parametrize("name, tool_input", [
    ("find_items", {"query": "saline"}),
    ("get_reorder_plan", {"status": "all", "criticality": "V", "at_risk_only": False, "limit": 10}),
    ("get_item_detail", {"item_id": "MED005"}),
    ("get_kpis", {"days": 90}),
    ("get_supply_risks", {}),
    ("get_purchase_orders", {"open_only": True}),
    ("trace_lot", {"lot_no": "NO-SUCH-LOT"}),
])
def test_every_tool_returns_json(ctx, name, tool_input):
    out, is_error = assistant.run_tool(ctx, name, tool_input)
    assert not is_error, out
    json.loads(out)


def test_tool_results_use_the_engines_numbers(ctx):
    out, _ = assistant.run_tool(ctx, "get_item_detail", {"item_id": "med005"})      # case-insensitive id
    detail = json.loads(out)
    row = ctx.plan[ctx.plan["item_id"] == "MED005"].iloc[0]
    assert detail["rop"] == round(float(row["rop"]), 2)
    assert detail["safety_stock"] == round(float(row["safety_stock"]), 2)


def test_bad_tool_input_comes_back_as_an_error_not_a_crash(ctx):
    out, is_error = assistant.run_tool(ctx, "get_item_detail", {"item_id": "NOPE"})
    assert is_error and "find_items" in out


def test_the_assistant_has_no_tool_that_changes_data():
    names = {t["name"] for t in assistant.TOOLS}
    assert names == set(assistant.HANDLERS)
    assert all(n.startswith(("get_", "find_", "trace_")) for n in names)
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in assistant.TOOLS)


# --- The agent loop ------------------------------------------------------------

def test_a_question_runs_a_tool_then_answers_and_is_logged(ctx):
    rop = round(float(ctx.plan.loc[ctx.plan["item_id"] == "MED005", "rop"].iloc[0]), 2)
    client = FakeClient(tool_reply("get_item_detail", {"item_id": "MED005"}),
                        text_reply(f"Meropenem's reorder point is {rop} vials."))
    before = stock(ctx.conn)
    messages, seen = [], []
    run = assistant.run_turn(assistant.AnthropicProvider(client), ctx, messages, "Why is Meropenem's ROP what it is?",
                             user="tester", on_tool=lambda name, i, err: seen.append(name))
    assert run["status"] == "ok" and str(rop) in run["answer"]
    assert seen == ["get_item_detail"]
    assert run["figures"] == 1 and run["ungrounded"] == []                 # the figure came from a tool
    # the second request carried the tool result back, and the conversation is append-only
    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    # model, caching, effort and fallback are set on every request
    req = client.requests[0]
    assert req["model"] == assistant.DEFAULT_MODELS["anthropic"] and req["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"effort": assistant.EFFORT} and req["fallbacks"] == "default"
    # audit log
    row = ctx.conn.execute("SELECT status, tool_calls, cost_usd, figures, provider, model FROM ai_runs").fetchone()
    assert tuple(row)[:2] == ("ok", 1) and row["cost_usd"] > 0 and row["figures"] == 1
    assert (row["provider"], row["model"]) == ("anthropic", assistant.DEFAULT_MODELS["anthropic"])
    assert ctx.conn.execute("SELECT tool FROM ai_tool_calls").fetchone()[0] == "get_item_detail"
    assert stock(ctx.conn) == before                                       # read-only


def test_a_made_up_figure_is_flagged(ctx):
    client = FakeClient(tool_reply("get_kpis", {"days": 90}), text_reply("Fill rate was 12345.6 units."))
    run = assistant.run_turn(client, ctx, [], "How are we doing?", user="tester")
    assert run["ungrounded"] == [12345.6]


def test_the_daily_budget_stops_calls_before_they_happen(ctx):
    client = FakeClient(text_reply("should not be called"))
    assistant.ensure_schema(ctx.conn)
    with ctx.conn:
        ctx.conn.execute("INSERT INTO ai_runs (created_at, user, status, cost_usd) VALUES (?, 'tester', 'ok', 5.0)",
                         (datetime.now().isoformat(timespec="seconds"),))
    run = assistant.run_turn(client, ctx, [], "Anything?", user="tester", budget=1.0)
    assert run["status"] == "budget" and client.requests == []


def test_an_api_failure_keeps_the_app_alive(ctx):
    run = assistant.run_turn(FakeClient(RuntimeError("network down")), ctx, [], "Hello?", user="tester")
    assert run["status"] == "error" and "try again" in run["answer"]
    assert ctx.conn.execute("SELECT status FROM ai_runs").fetchone()[0] == "error"


def test_a_refusal_is_handled(ctx):
    refused = NS(content=[], stop_reason="refusal", usage=usage())
    run = assistant.run_turn(FakeClient(refused), ctx, [], "Something off-topic", user="tester")
    assert run["status"] == "refused"


def test_tool_rounds_are_capped(ctx):
    loops = [tool_reply("get_supply_risks", {}, f"c{i}") for i in range(assistant.MAX_TOOL_ROUNDS + 1)]
    client = FakeClient(*loops, text_reply("Here is what I found."))
    run = assistant.run_turn(client, ctx, [], "Loop forever", user="tester")
    assert run["status"] == "ok"
    assert len(run["tools"]) <= assistant.MAX_TOOL_ROUNDS


def test_grounding_check_accepts_rounding_and_percent_of_fractions():
    figures, missing = assistant.grounding_check("Fill rate 97.3%, ROP 29.3, value $1,200, 3 lots",
                                                 ['{"fill_rate": 0.9731, "rop": 29.304, "value": 1200}'])
    assert figures == 3 and missing == []


# --- Gemini (the default provider) ------------------------------------------------
from google.genai import types as gt


def g_usage(prompt=800, out=120, thoughts=30, cached=0):
    return NS(prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts,
              cached_content_token_count=cached, tool_use_prompt_token_count=0)


def g_reply(parts, finish="STOP", usage=None):
    return NS(candidates=[NS(content=gt.Content(role="model", parts=parts), finish_reason=NS(name=finish))],
              usage_metadata=usage or g_usage(), prompt_feedback=None)


def g_text(text, finish="STOP"):
    return g_reply([gt.Part(text=text)], finish)


def g_call(name, args, call_id=None):
    return gt.Part(function_call=gt.FunctionCall(id=call_id, name=name, args=args))


class FakeGemini:
    """A scripted stand-in for google.genai.Client: records every generate_content request."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.models = NS(generate_content=self._generate)

    def _generate(self, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def gemini(*replies):
    client = FakeGemini(*replies)
    return assistant.GeminiProvider(client), client


def test_gemini_is_the_default_and_answers_plain_text(ctx):
    assert assistant.DEFAULT_PROVIDER == "gemini" and assistant.settings(None)["provider"] == "gemini"
    provider, client = gemini(g_text("MedStock tracks 150 fictional items."))
    run = assistant.run_turn(provider, ctx, [], "What is MedStock?", user="tester")
    assert run["status"] == "ok" and run["answer"] == "MedStock tracks 150 fictional items."
    assert run["input_tokens"] == 800 and run["output_tokens"] == 150              # thinking counted as output
    # always a paid-equivalent estimate, even on the (unverified) free-tier setting
    assert run["cost"] == pytest.approx((800 * 0.30 + 150 * 2.50) / 1e6)
    assert "Estimate" in run["cost_note"] and "expected charge is $0" in run["cost_note"]
    assert "cannot verify" in run["cost_note"]
    row = ctx.conn.execute("SELECT provider, model, status, cost_usd, cost_note FROM ai_runs").fetchone()
    assert tuple(row)[:3] == ("gemini", assistant.DEFAULT_MODELS["gemini"], "ok")
    assert row["cost_usd"] == pytest.approx(run["cost"], abs=1e-6) and row["cost_note"] == run["cost_note"]
    cfg = client.requests[0]["config"]
    assert client.requests[0]["model"] == "gemini-3.5-flash-lite"
    assert cfg.automatic_function_calling.disable is True                         # MedStock runs the tools itself
    assert [d.name for d in cfg.tools[0].function_declarations] == [x["name"] for x in assistant.TOOLS]
    assert len(cfg.tools) == 1 and not cfg.tools[0].google_search and not cfg.tools[0].url_context
    assert not cfg.tools[0].code_execution                                         # no Search grounding or others
    assert "fictional" in cfg.system_instruction


def test_gemini_runs_several_tool_rounds_and_sends_results_back(ctx):
    rop = round(float(ctx.plan.loc[ctx.plan["item_id"] == "MED005", "rop"].iloc[0]), 2)
    provider, client = gemini(
        g_reply([g_call("find_items", {"query": "meropenem"}, "a1")]),
        g_reply([g_call("get_item_detail", {"item_id": "MED005"}, "a2"), g_call("get_kpis", {"days": 30}, "a3")]),
        g_text(f"Its reorder point is {rop} vials."))
    before = stock(ctx.conn)
    messages = []
    run = assistant.run_turn(provider, ctx, messages, "Meropenem ROP?", user="tester")
    assert run["status"] == "ok" and run["rounds"] == 3
    assert [t["tool"] for t in run["tools"]] == ["find_items", "get_item_detail", "get_kpis"]
    assert run["ungrounded"] == [] and run["figures"] == 1
    # each round sends back one user turn with a function response for every call, matched by id and name
    second_round = client.requests[2]["contents"][-1]
    assert second_round.role == "user"
    assert [(p.function_response.id, p.function_response.name) for p in second_round.parts] == \
        [("a2", "get_item_detail"), ("a3", "get_kpis")]
    assert "output" in second_round.parts[0].function_response.response
    assert [m.role for m in messages] == ["user", "model", "user", "model", "user", "model"]   # append-only
    assert ctx.conn.execute("SELECT COUNT(*) FROM ai_tool_calls").fetchone()[0] == 3
    assert stock(ctx.conn) == before                                               # read-only


def test_gemini_bad_tool_arguments_come_back_as_errors(ctx):
    provider, client = gemini(g_reply([g_call("get_item_detail", {"sku": "MED005"})]),     # wrong argument name
                              g_reply([g_call("delete_everything", {})]),                   # not a tool
                              g_text("I could not look that up."))
    run = assistant.run_turn(provider, ctx, [], "Detail?", user="tester")
    assert run["status"] == "ok" and [t["is_error"] for t in run["tools"]] == [True, True]
    sent = client.requests[1]["contents"][-1].parts[0].function_response.response
    assert "error" in sent


def test_gemini_malformed_function_call_is_corrected_not_fatal(ctx):
    provider, client = gemini(g_reply([], finish="MALFORMED_FUNCTION_CALL"), g_text("Here is the answer."))
    run = assistant.run_turn(provider, ctx, [], "Anything?", user="tester")
    assert run["status"] == "ok" and run["answer"] == "Here is the answer."
    assert "could not be read" in client.requests[1]["contents"][-1].parts[0].text


@pytest.mark.parametrize("reply", [
    g_reply([], finish="SAFETY"),
    NS(candidates=[], usage_metadata=g_usage(), prompt_feedback=NS(block_reason="PROHIBITED_CONTENT")),
    NS(candidates=[], usage_metadata=None, prompt_feedback=None),
])
def test_gemini_refusals_and_blocked_prompts_are_handled(ctx, reply):
    provider, _ = gemini(reply)
    run = assistant.run_turn(provider, ctx, [], "Off-topic", user="tester")
    assert run["status"] == "refused" and "can't help" in run["answer"]


def test_gemini_errors_keep_the_app_alive_and_never_log_a_key(ctx):
    leaked = "AIza" + "x" * 35
    provider, _ = gemini(RuntimeError(f"400 API key not valid: {leaked}"))
    run = assistant.run_turn(provider, ctx, [], "Hello?", user="tester")
    assert run["status"] == "error" and "try again" in run["answer"]
    logged = ctx.conn.execute("SELECT error FROM ai_runs").fetchone()[0]
    assert leaked not in logged and "[redacted]" in logged


def test_gemini_tool_rounds_are_capped(ctx):
    loops = [g_reply([g_call("get_supply_risks", {}, f"c{i}")]) for i in range(assistant.MAX_TOOL_ROUNDS + 3)]
    provider, _ = gemini(*loops, g_text("Done."))
    run = assistant.run_turn(provider, ctx, [], "Loop forever", user="tester")
    assert run["status"] in ("ok", "limit") and len(run["tools"]) <= assistant.MAX_TOOL_ROUNDS
    assert run["rounds"] <= assistant.MAX_TOOL_ROUNDS + 2


def test_gemini_made_up_figure_is_flagged(ctx):
    provider, _ = gemini(g_reply([g_call("get_kpis", {"days": 90})]), g_text("Waste was 98765.4 dollars."))
    run = assistant.run_turn(provider, ctx, [], "Waste?", user="tester")
    assert run["ungrounded"] == [98765.4]


def test_gemini_cached_tokens_are_charged_once_at_the_cache_rate(ctx):
    """prompt_token_count already includes cached_content_token_count (google-genai field docs). Of 10,000
    prompt tokens, 6,000 are cached: 4,000 at $0.30, 6,000 at $0.03, and 500 output (incl. 100 thinking) at
    $2.50 per million."""
    reply = g_reply([gt.Part(text="ok")], usage=g_usage(prompt=10_000, out=400, thoughts=100, cached=6_000))
    provider = assistant.GeminiProvider(FakeGemini(reply), billing="paid")
    run = assistant.run_turn(provider, ctx, [], "Hi", user="tester")
    assert (run["input_tokens"], run["cache_read"], run["output_tokens"]) == (4_000, 6_000, 500)
    expected = (4_000 * 0.30 + 6_000 * 0.03 + 500 * 2.50) / 1_000_000
    assert expected == pytest.approx(0.00263)
    assert run["cost"] == pytest.approx(expected, rel=0, abs=1e-12)
    assert "free tier" not in run["cost_note"]                                    # configured as paid


def test_gemini_estimate_drives_the_daily_budget_even_on_free_setting(ctx):
    big = g_usage(prompt=2_000_000, out=200_000, thoughts=0)                       # $0.60 + $0.50 = $1.10 estimated
    provider, client = gemini(g_reply([gt.Part(text="one")], usage=big), g_text("two"))
    first = assistant.run_turn(provider, ctx, [], "Q1", user="tester", budget=1.00)
    assert first["status"] == "ok" and first["cost"] == pytest.approx(1.10)
    second = assistant.run_turn(provider, ctx, [], "Q2", user="tester", budget=1.00)
    assert second["status"] == "budget" and len(client.requests) == 1             # cap holds without verified billing


def test_daily_question_limit_applies_to_every_provider(ctx):
    provider, client = gemini(g_text("one"), g_text("two"))
    assistant.run_turn(provider, ctx, [], "Q1", user="tester", question_limit=1)
    run = assistant.run_turn(provider, ctx, [], "Q2", user="tester", question_limit=1)
    assert run["status"] == "quota" and len(client.requests) == 1


def test_keys_and_settings_come_only_from_secrets_or_environment(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert assistant.get_api_key({}, "gemini") is None and assistant.get_api_key(None, "anthropic") is None
    assert assistant.get_api_key({"GEMINI_API_KEY": "from-secrets"}, "gemini") == "from-secrets"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert assistant.get_api_key({}, "gemini") == "from-env"
    assert assistant.get_api_key({"GEMINI_API_KEY": "x"}, "anthropic") is None      # keys never cross providers
    cfg = assistant.settings({"ai": {"provider": "Anthropic", "daily_question_limit": 5}})
    assert cfg["provider"] == "anthropic" and cfg["model"] == assistant.DEFAULT_MODELS["anthropic"]
    assert cfg["daily_question_limit"] == 5
    assert assistant.settings({"ai": {"provider": "something-else"}})["provider"] == "gemini"


def test_old_audit_logs_get_the_provider_column(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE ai_runs (run_id INTEGER PRIMARY KEY, created_at TEXT, user TEXT, model TEXT, "
                 "cost_usd REAL, status TEXT)")
    assistant.ensure_schema(conn)
    assert "provider" in {r[1] for r in conn.execute("PRAGMA table_info(ai_runs)")}
    conn.close()


def test_tests_cannot_create_a_real_ai_client():
    with pytest.raises(RuntimeError, match="real AI client"):
        assistant.make_provider(assistant.settings(None), "not-a-key")
    from google import genai
    import anthropic
    for make in (lambda: genai.Client(api_key="not-a-key"), lambda: anthropic.Anthropic(api_key="not-a-key"),
                 lambda: anthropic.AsyncAnthropic(api_key="not-a-key")):
        with pytest.raises(RuntimeError, match="real AI client"):                  # the SDKs are blocked too
            make()
