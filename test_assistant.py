"""
Tests for Ask MedStock (assistant.py). The Claude API is replaced by a scripted fake, so these tests
cost nothing, need no API key and never touch your real data.
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
    run = assistant.run_turn(client, ctx, messages, "Why is Meropenem's ROP what it is?", user="tester",
                             on_tool=lambda name, i, err: seen.append(name))
    assert run["status"] == "ok" and str(rop) in run["answer"]
    assert seen == ["get_item_detail"]
    assert run["figures"] == 1 and run["ungrounded"] == []                 # the figure came from a tool
    # the second request carried the tool result back, and the conversation is append-only
    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    # model, caching, effort and fallback are set on every request
    req = client.requests[0]
    assert req["model"] == assistant.MODEL and req["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"effort": assistant.EFFORT} and req["fallbacks"] == "default"
    # audit log
    row = ctx.conn.execute("SELECT status, tool_calls, cost_usd, figures FROM ai_runs").fetchone()
    assert tuple(row)[:2] == ("ok", 1) and row["cost_usd"] > 0 and row["figures"] == 1
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
