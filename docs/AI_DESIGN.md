# Adding agentic AI to MedStock

Design document, v0.2. Author: Wendyl Jaca. Status: phase 1 built (Ask MedStock), on Gemini by default.

## Summary

**Today:** Ask MedStock is a Gemini-powered, tool-using, **read-only** assistant. It answers questions by
calling seven read-only tools, often several per question, and cannot place orders, change stock,
resolve alerts or carry out its suggestions. It is not an autonomous agent. The approval-based features
below are planned (marked "Coming later") and are not available.

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
Buyer in the app ──► agent runtime (assistant.run_turn) ◄──► provider adapter ◄──► Gemini API (default)
                         │                                                   └──► Anthropic API (optional)
                         ├─► read tools ─► planning, kpis, purchasing, events, db (existing code)
                         ├─► proposal tools ─► proposal queue (phase 2) ─► person approves ─► existing functions
                         └─► audit log (ai_runs, ai_tool_calls): question, tool calls, answer, tokens, estimated cost, time
```

## Phase 1: Ask MedStock (built)

| Part | Where | Notes |
|---|---|---|
| Tools | `assistant.TOOLS`, `assistant.HANDLERS` | 7 read-only tools: item search, reorder plan, item detail, KPIs, supply risks, purchase orders, lot trace. Strict JSON schemas, the same for every provider |
| Agent loop | `assistant.run_turn` | Manual tool loop, append-only conversation, all tool results returned in one message, at most 8 tool rounds per question. It only sees a shared `Reply` (text, tool calls, stop reason, token usage), never a provider's own format |
| Provider adapter | `assistant.GeminiProvider`, `assistant.AnthropicProvider` | Each turns one request and reply into the shared shape and back. Settings come from `assistant.settings()` |
| Model | `assistant.DEFAULT_MODELS` | Gemini (default): `gemini-3.5-flash-lite` through the official `google-genai` SDK, manual function calling, no Google Search grounding, URL context or code execution. Anthropic (optional): `claude-opus-5-5`, effort `medium`, refusal fallback and prompt caching on |
| Audit log | `ai_runs`, `ai_tool_calls` tables | Created on first use; every run records its provider and model. Shown under "Audit log and usage" on the page |
| Grounding check | `assistant.grounding_check` | Lists numbers in the answer that no tool returned (rounding and percent-of-fraction allowed) |
| Usage caps | `assistant.DAILY_QUESTION_LIMIT`, `assistant.DAILY_BUDGET_USD` | Per signed-in user per day: 40 questions for every provider, and a dollar limit on the estimated cost. The dollar limit is a pre-call guardrail: it blocks a new question once today's accumulated estimate has reached it, but the answer in progress can take the total slightly over |
| Cost | `assistant.PRICES`, `assistant.cost_note` | Every run gets an **estimated** cost from the provider's standard paid list prices, labelled as an estimate, not an invoice. Gemini 3.5 Flash-Lite: $0.30 per million normal input tokens, $0.03 per million cached input tokens, $2.50 per million output tokens including thinking. Gemini's `prompt_token_count` already includes the cached tokens, so they are taken out of normal input and priced once. A model with no price list records a blank cost ("provider-dependent") |
| Page | Ask MedStock in the sidebar | Example questions, "what it looked up" per answer, tokens, estimated cost and time per answer, provider and model |
| Tests | `test_assistant.py`, `test_app.py`, `conftest.py` | Scripted fake providers, so tests are free and offline. The Streamlit test runner reads the local secrets file, so `conftest.py` blocks client creation in every test at two levels: the app's factories (`make_provider`, `make_client`) and the SDK constructors (`google.genai.Client`, `anthropic.Anthropic`, `anthropic.AsyncAnthropic`) |

## Setup

**Provider and model.** Gemini is the default. To change it, add an `[ai]` section to the secrets (all
lines optional):

```toml
[ai]
provider = "gemini"                 # or "anthropic"
model = "gemini-3.5-flash-lite"     # any model of that provider that supports function calling
daily_question_limit = 40
daily_budget_usd = 2.00             # checked before each question against today's paid-rate estimate
gemini_billing = "free"             # a label only; it changes the wording, not the estimate
```

**API key.** Gemini needs `GEMINI_API_KEY` (Anthropic needs `ANTHROPIC_API_KEY`). Locally, put the line
`GEMINI_API_KEY = "your-key-here"` at the top of `.streamlit/secrets.toml`, above any `[section]`. On
Streamlit Community Cloud, open the app, then **Manage app > Settings > Secrets**, paste the same line at
the top (above `[auth.users]`), and save; the app restarts. The key is read only from the secrets or an
environment variable of the same name. It is never written to code, logs or the repository, and an
error message that contains something key-like is redacted before it is logged. Without a key the page
explains how to add one and the rest of the app works as before.

**Model choice.** `gemini-3.5-flash-lite` was chosen in November 2026 from Google's model list
(https://aistudio.google.com/docs/models): it is a stable model, supports function calling, is
described as the most cost-effective model for high-throughput work, has a free tier, and costs
$0.30 / $2.50 per million input / output tokens (and $0.03 for cached input) on the paid tier
(https://aistudio.google.com/docs/pricing). Model availability changes over time, so check Google's
official model and deprecation pages before changing models.

**Cost and billing status.** MedStock cannot tell whether a Gemini key belongs to a free-tier project or
a billed one; Google does not expose that to the app. So every Gemini run is priced at the
paid-equivalent rate, and that **estimate** is what the daily dollar limit counts, even when
`gemini_billing = "free"`. With the free setting, the page also says the expected charge is $0 while the
project stays within an eligible free tier, and that MedStock has not verified the billing status. The
real charge is whatever Google's billing console shows. The daily question limit applies either way.

## Privacy

- On Gemini's **free tier, Google may use submitted content to improve its products** (Google's
  pricing page, "Used to improve our products: Yes"). The paid tier does not.
- MedStock contains **fictional data only**: the hospital, items, usage, vendors and people are made up.
- The free-tier configuration must **never** be used with real hospital, patient, vendor-confidential or
  personal information. A real deployment would need a paid or enterprise agreement, a review of data
  handling, and no protected health information in prompts.
- The page shows this note above the chat.

## Guardrails

- No stock-changing tools. The assistant cannot issue, receive, write off, recall or order.
- Tool results are data. The system prompt says text inside them (vendor notes, recall reasons)
  can never change the rules.
- A daily question limit per user for every provider, a cap on tool rounds per question, and a daily
  dollar limit on the estimated cost. The dollar limit is checked before each new question: once today's
  estimate has reached it, no new question is sent, but the answer already in progress can take the
  total slightly over the limit, so it is a guardrail, not an exact hard cap.
- Only MedStock's own tools are offered: no Google Search grounding, URL context or code execution, so
  answers can only use the app's fictional data.
- Every run is logged with its provider, model, tool calls, tokens, estimated cost (with a note on how to
  read it) and time.
- API failures, refusals, blocked prompts and malformed tool calls return a plain message or a retry;
  the app keeps working.

## Evaluation plan

The simulator lets the agents be measured instead of described. The same seeded period is run
three ways: rules only, agent proposals approved automatically, and agent proposals reviewed by a
person. Measures: fill rate and Vital stockouts, inventory value and waste, backup-vendor spend,
grounding rate (target 100%), proposal acceptance rate, cost and time per answer, and resistance to
instructions planted in vendor notes.

## Delivery plan

1. **Foundation and Ask MedStock:** built and live (read-only).
2. **Coming later: proposal queue and buyer assistant.** Daily order proposals with written justifications, approved by a person on a new page.
3. **Coming later: disruption responder.** On a recall or vendor outage, proposes replacement orders and ward notices for a person to approve.
4. **Coming later: scenario comparison, then a policy analyst.** Runs two policies over the same period and recommends one.
5. **Coming later: agent scorecard.** A page with the evaluation results.

None of these will change data on their own: every proposal waits for a person to approve it.

## Open questions

- On the live site all visitors share one database, so later phases may need a workspace per
  signed-in user, or a replay mode for visitors.
- Model updates can change answers; a fixed question set should run before adopting a new model or
  switching provider. Gemini and Claude can phrase the same figures differently.
- Whether the buyer agent may ever send low-risk orders without review. The default is no.
