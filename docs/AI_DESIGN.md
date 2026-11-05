# Adding agentic AI to MedStock

Design document, v0.1. Author: Wendyl Jaca. Status: phase 1 built (Ask MedStock).

## Summary

MedStock already has a deterministic planning engine, a full stock ledger and a simulation clock.
AI agents are added on top of that engine. They read the app's numbers through tools, propose
actions and explain their reasoning. They never calculate reorder points themselves and never
change stock. Anything they suggest waits for a person to approve it, and every tool call is logged.

## Design principles

1. **The engine calculates.** Reorder points, safety stock and forecasts come from the existing
   code. The model reads them through tools and does no inventory math.
2. **Agents propose, people approve.** A tool that would change data only writes a proposal; a
   person approves it and the existing, validated functions make the change.
3. **Every number has a source.** Answers quote figures returned by tools. The app checks each
   answer and lists any figure no tool returned.
4. **Earn each extra agent.** Start with one assistant; split into specialists only when the
   simulator shows the split improves results.

## Architecture

```
Buyer in the app ──► agent runtime (assistant.run_turn) ◄──► Claude API (tool use)
                         │
                         ├─► read tools ─► planning, kpis, purchasing, events, db (existing code)
                         ├─► proposal tools ─► proposal queue (phase 2) ─► person approves ─► existing functions
                         └─► audit log (ai_runs, ai_tool_calls): question, tool calls, answer, tokens, cost, time
```

## Phase 1: Ask MedStock (built)

| Part | Where | Notes |
|---|---|---|
| Tools | `assistant.TOOLS`, `assistant.HANDLERS` | 7 read-only tools: item search, reorder plan, item detail, KPIs, supply risks, purchase orders, lot trace. All use `strict: true` schemas |
| Agent loop | `assistant.run_turn` | Manual tool loop, append-only conversation, all tool results returned in one message, at most 8 tool rounds per question |
| Model | `assistant.MODEL` | `claude-opus-5-5`, effort `medium`, server-side refusal fallback on, prompt caching on |
| Audit log | `ai_runs`, `ai_tool_calls` tables | Created on first use; shown under "Audit log and spending" on the page |
| Grounding check | `assistant.grounding_check` | Lists numbers in the answer that no tool returned (rounding and percent-of-fraction allowed) |
| Spending cap | `assistant.DAILY_BUDGET_USD` | Per signed-in user per day; set `[ai] daily_budget_usd` in secrets to change it |
| Page | Ask MedStock in the sidebar | Example questions, "what it looked up" per answer, cost and time per answer |
| Tests | `test_assistant.py`, `test_app.py` | A scripted fake model, so tests are free and offline |

**API key.** Put `ANTHROPIC_API_KEY = "..."` in `.streamlit/secrets.toml` locally, or in the
app's Secrets on Streamlit Cloud. It is never written to code or committed. Without a key the page
explains how to add one and the rest of the app works as before.

## Guardrails

- No stock-changing tools. The assistant cannot issue, receive, write off, recall or order.
- Tool results are data. The system prompt says text inside them (vendor notes, recall reasons)
  can never change the rules.
- A daily dollar cap per user and a cap on tool rounds per question.
- Every run is logged with its tool calls, tokens, cost and time.
- API failures and refusals return a plain message; the app keeps working.

## Evaluation plan

The simulator lets the agents be measured instead of described. The same seeded period is run
three ways: rules only, agent proposals approved automatically, and agent proposals reviewed by a
person. Measures: fill rate and Vital stockouts, inventory value and waste, backup-vendor spend,
grounding rate (target 100%), proposal acceptance rate, cost and time per answer, and resistance to
instructions planted in vendor notes.

## Delivery plan

1. **Foundation and Ask MedStock:** built.
2. **Proposal queue and buyer agent:** daily order proposals with written justifications, approved on a new page.
3. **Disruption responder:** runs on a recall or vendor outage; proposes replacement orders and ward notices.
4. **Scenario comparison, then the policy analyst:** the agent runs two policies over the same period and recommends one.
5. **Agent scorecard:** a page with the evaluation results.

## Open questions

- On the live site all visitors share one database, so later phases may need a workspace per
  signed-in user, or a replay mode for visitors.
- Model updates can change answers; a fixed question set should run before adopting a new model.
- Whether the buyer agent may ever send low-risk orders without review. The default is no.
