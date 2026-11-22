# Agent mode alongside the pipeline: design and findings

This is the design of agent mode, the reasons for each decision, and what building and measuring it found. It was written on 2026-11-21 as a plan, after reading the engine, the eval harness, the CLI and the current LangGraph docs. The plan was then carried out: increments 1 to 7 and 9 were built, increment 8's paid run was skipped, agent mode had one held-out run on BOX, and a hybrid mode was built and simulated. Sections 1 to 13 are the design, with changes made during the build noted where they apply; §14 records what each step found.

## 1. The short version

A second way to answer a question. In the pipeline, code picks the excerpts and the model answers once. In agent mode the model gets three read-only tools (search, read a chunk, list filings), calls them in a loop until it decides it has enough, then returns the same answer JSON as the pipeline. That JSON goes through the **same** quote verifier, so the trust rule does not move: no verified quote, no answer.

Everything after the answer row (presentation, memo, claim check, grading) is untouched, because the row has the same shape.

**Framework: LangGraph 1.2.24, using only its graph runtime, with the model called through the Anthropic SDK this project already uses.** Reasons and the alternatives are in section 2.

In one sentence: *a ReAct-style tool loop expressed as a small state machine, with a deterministic verifier as the last node and hard budgets enforced by the graph's routing, measured against a non-agentic baseline on the same answer key.*

## 2. Framework choice

### What I checked (docs and package index, 2026-11-21)

| | LangGraph | Pydantic AI | Anthropic SDK tool loop | Claude Agent SDK |
|---|---|---|---|---|
| Current version | 1.2.24 (released 2026-11-20) | 2.71.0 | already installed (1.8.0) | 0.2.187 |
| New packages installed | about 25 (20 today, 45 after) | about 4 | 0 | not resolved |
| Who writes the loop | project code, as nodes and edges | built in | project code (about 60 lines) or the SDK's beta tool runner | built in |
| Step and token limits | project code routes on counters in state; `recursion_limit` is a backstop | built-in `UsageLimits` | written in project code | not checked |
| Control flow as an explicit graph that can be drawn and inspected | yes | no (internal) | no | no |
| Multi-agent later | subgraphs, `Send`, `Command` | agents calling agents | hand-written | subagents |

### Why LangGraph

- **The control flow is explicit.** The graph is defined in the project's code as nodes and edges, so the control flow, the budgets and the stop conditions in section 3 are visible and can each be tested.
- **Its docs draw the line this project straddles.** LangGraph's own docs define the workflow-versus-agent distinction, and this project now has one of each: the pipeline is the workflow, agent mode the agent.
- **It is a widely used framework**, so the comparison against the hand-built pipeline is informative.
- **It does not force LangChain on the engine.** The docs say LangGraph does not require LangChain and that nodes are plain functions. So the model node can call `filingroom/llm.py`, which keeps the cost meter, the spend caps and the refusal handling in one place.
- **Phase 2 has a natural home.** Planner, researcher and verifier become nodes or subgraphs of the same graph.

### Is another framework clearly better? No, but two honest caveats

- **Pydantic AI would be less code and far fewer packages.** Its built-in loop, `UsageLimits` and output validators map almost one-to-one onto "tool loop, budgets, verify the quotes". If the goal were only the smallest correct agent, I would pick it. It loses on how widely it is used and on having a graph defined in the project's own code: its loop is internal. It would also need `anthropic>=1.15`, a bump from the locked 1.8.0.
- **No framework at all is the smallest change.** The Anthropic SDK can run this loop with zero new dependencies. That is the best fit for a three-dependency project. The problem does not need a framework: LangGraph is here to make the loop an explicit, testable state machine, not because the loop requires one. We use none of LangGraph's headline features (persistence, human-in-the-loop, streaming).
- **Claude Agent SDK is a poor fit.** It is the Claude Code harness as a library, built around file and shell tools. We want three narrow tools and tight control of every model call.

### What the dependency costs

- **About 25 new packages**, including `langchain-core`, `langsmith`, `pydantic` (already present), `requests`, and the older `httpx` alongside the `httpx2` the Anthropic SDK uses.
- **`langsmith` is a tracing client for a hosted service.** The docs say tracing is enabled by setting `LANGSMITH_TRACING=true` plus an API key; they do not state the default in so many words. Because this project is "local and private", increment 3 read the installed source to confirm, set `LANGSMITH_TRACING` and the other tracing variables to `false` explicitly in code, and added a test that an agent run opens no connection other than to the Anthropic API (details in §14).
- **Fast release cadence.** Four releases in nine days. The exact version is pinned, and every `langgraph` import is in one file.
- **The Anthropic SDK must not move.** An unconstrained resolve picks `anthropic` 2.12.0. The lock stays at 1.8.0 so the pipeline's SDK is unchanged; the `uv.lock` diff was checked and is additions only (§14).

### Not added: `langchain-anthropic`

The LangGraph quickstart calls Claude through LangChain (`init_chat_model(...).bind_tools(...)`), which needs two more direct dependencies (`langchain`, `langchain-anthropic`). They were **not** added, and Claude is called through `llm.py` instead:

- The model call would bypass `llm.py`, so cost metering and the spend caps would need a second implementation.
- The project's structured-output and effort settings go through `output_config`, which I have verified on the Anthropic SDK but not on the LangChain wrapper.

The cost of this choice: the code looks less like the tutorials. The node functions are the same shape, though, and the quickstart also hand-writes its tool node.

## 3. Graph design

One graph run answers one question for one company. The checklist run stays what it is today: a thread pool calling "answer one question" 40 times.

```mermaid
flowchart TD
    START --> agent
    agent -->|asked for tools, within budget| tools
    agent -->|asked for tools, tool-call cap or token budget spent| finalize
    agent -->|returned an answer| verify
    tools -->|calls left| agent
    tools -->|next call is the last one allowed| finalize
    finalize --> verify
    verify -->|no quote verified, one repair left| agent
    verify -->|otherwise| END
```

### State

A `TypedDict` (the docs recommend it over Pydantic for speed). Fields that accumulate use a reducer, which is LangGraph's way of saying "append, don't overwrite".

| Field | Type | Purpose |
|---|---|---|
| `messages` | list, append reducer | The conversation in Anthropic's format, including tool calls and results. Assistant content is stored exactly as returned, because thinking blocks must be passed back unchanged. |
| `seen` | list of chunk ids, append-unique | Every chunk a tool has shown the model. Becomes the row's `retrieved`. |
| `model_calls`, `tool_calls` | int, add reducer | Step counters the router reads. |
| `tokens` | int, add reducer | Input plus output tokens so far, from each response's `usage`. |
| `draft` | dict or None | The model's answer JSON, before verification. |
| `repairs` | int | How many verify-then-retry rounds have run (0 or 1). |
| `stop` | str | Why the loop ended: `model_done`, `step_limit`, `token_limit`, `error`. |
| `row` | dict | The finished answer row. |

Things that are not data about the run (the ticker, the loaded `Index`, the `CostMeter`, the limits, the model-calling function) are passed as **runtime context** (`context_schema`), LangGraph's documented place for dependencies. That is also the seam for tests: a test passes a scripted fake in place of the model-calling function, the same pattern `present.py` already uses with `complete=`.

### Nodes

| Node | Kind | What it does |
|---|---|---|
| `agent` | model call | Sends system prompt, tools and messages. Either the model asks for tools, or it stops and its text is the answer JSON. |
| `tools` | plain code | Runs every requested tool, returns all results in one message, records `seen`. A bad argument comes back as an error result the model can read, not an exception. |
| `finalize` | model call | Used only when a budget ran out. Makes one call with tools switched off (`tool_choice: none`) so the model must answer from what it has seen or return `not_found`. Two entries: from `agent` when the turn's tool requests would pass the tool-call cap or the token budget is already spent (the requests get "limit reached" results); from `tools` after the last allowed tool round (the step limit), whose real results end with a note to answer now. *(Changed in increment 3: originally the step limit refused the second-to-last call's requests too, wasting that call.)* |
| `verify` | plain code | Runs the shared row builder: string-verifies each quote against the chunk it names, sets `unsupported` when none verify. No model involved. |

### Stop conditions, in the order they bite

1. **The model decides it is done.** It stops calling tools and returns the answer. This is the "genuinely agentic" part: nothing in code tells it how many searches to run.
2. **Step limit.** Default 6 model calls (the forced final answer included) and 8 tool calls per question. The tool-call cap is checked by the edge out of `agent`; the model-call limit by the edge out of `tools`, so the last tool round still runs and the final call answers from it.
3. **Token limit.** Default 100,000 tokens per question (30,000 at first; raised after increment 4's spike, see §14). The final answer call is always allowed, so the true ceiling is that plus one call; the measured maximum was 80,494 on the 80 tuning items and 81,237 on BOX (§14). For scale, the pipeline uses about 10,100 input tokens per question today.
4. **Existing spend caps.** Every call goes through `llm.py`, so `CostMeter.limit` and `FILINGROOM_MAX_USD` still stop the whole command.
5. **`recursion_limit` backstop.** Set to a little over twice the model-call limit. If a routing bug ever loops, LangGraph raises `GraphRecursionError`; it is caught and the row becomes `status: error`.
6. **Request timeout** on the SDK client. LangGraph's own node timeouts apply only to async nodes, and this code is sync.

Why counters in state and not just `recursion_limit`: the docs do not say what happens to state when `GraphRecursionError` is raised. I want a limit to produce a normal, verified row, so the graph routes to `finalize` itself and the framework limit is only a safety net.

### How the final answer is produced

Each model call sends both `tools` and `output_config.format` set to the existing `ANSWER_SCHEMA`. The Anthropic docs show the two used together. When the model stops calling tools, its text is schema-valid JSON, exactly like the pipeline's.

How the format constraint behaves on turns where the model calls a tool was left to the first paid spike (planned at about one cent), with a fallback if it misbehaved: a fourth tool, `submit_answer`, with `strict: true` and the same schema. The spike in increment 4 found it behaves cleanly, and the fallback was not needed (§14).

### The repair edge

If `verify` finds an answered draft with zero verified quotes, the model gets one message naming the quotes that failed and the chunks they were claimed from, and one more turn inside the same budgets. The row is still built by the same verifier afterwards, so this can only turn `unsupported` into `answered` by producing a quote that really is in the filing.

It is its own increment behind a switch, off at first, so that its effect would be measured, not assumed. Its trigger never occurred in the measured runs, so it is still off and its effect is unmeasured (§14, increment 8).

## 4. Tools

All three are read-only and bound in code to the one company being screened. The ticker is not a parameter, so the model cannot wander into another company's filings. Each is a plain function in `filingroom/agent/tools.py` with no framework import, which is what makes them testable with the stdlib.

### `search_filings`

| | |
|---|---|
| Wraps | `Index.search` in [index.py](filingroom/index.py) (BM25, forms as a hard filter, topics and periods as boosts) |
| Inputs | `query` (string, required); `forms` (subset of `10-K`, `10-Q`, `8-K`, `DEF 14A`); `topics` (subset of the index's topic tags, such as `financials`, `mdna`, `risk_factors`, `proxy`); `periods` (labels such as `FY2026`, `Q3 FY2026`); `k` (1 to 8, default 5) |
| Output | Ranked hits: `chunk_id`, form, period, filing date, section heading, subheading, score, and the full chunk text |
| Notes | A chunk already shown in this question comes back as its id marked "already shown", not the text again. Unknown form or topic returns an error listing the valid values. |

Full text and not snippets, because the model must copy quotes verbatim and a snippet would force a second call for every hit. The price is tokens, which the small `k` and the already-shown rule keep down.

### `get_chunk`

| | |
|---|---|
| Wraps | `Index.by_id` and `Index.neighbors` |
| Inputs | `chunk_id` (required); `neighbors` (0 or 1, default 1) |
| Output | The chunk, and with `neighbors: 1` the chunks immediately before and after it in the same section, in reading order |
| Notes | Unknown id returns an error result. |

This is the pipeline's `expand` step turned into a choice: the pipeline always adds neighbours of the top two hits; the agent asks for them when an answer seems to run across a boundary.

### `list_filings`

| | |
|---|---|
| Wraps | `edgar.manifest` and `checklist.periods` |
| Inputs | none |
| Output | One line per filing in the current set (doc id, form, period, period end, filing date, sections with chunk counts), plus the resolved labels: latest fiscal year, prior fiscal year, latest quarter release, latest proxy |

### What the agent is and is not told

- **Told:** the same question text, answer type and "Target period" line the pipeline sends, and the same answering rules (use only the filings, quote verbatim, scale notes, `not_found` when absent). These go in a new `prompts/agent.md`; `prompts/answer.md` is not edited.
- **Not told:** the checklist's hand-tuned `where` and `search` hints. Those are the pipeline's retrieval knowledge. Withholding them is the experiment: can the model find the passage without them? It also matches the app's free-text questions, which have no hints at all and are where I expect agent mode to help most.

## 5. Where it plugs in

The seam is one function. Today everything calls `answer.answer_question(ticker, q, ix, meter, ...)` and gets a row. Agent mode adds `agent.answer_question` with the same signature and the same return shape, and a tiny chooser picks between them.

| File | Change |
|---|---|
| `filingroom/agent/tools.py` (new) | The three tools as pure functions. |
| `filingroom/agent/graph.py` (new) | State, nodes, edges. The only file that imports `langgraph`, and it is imported lazily so pipeline mode never loads it. |
| `filingroom/agent/__init__.py` (new) | `answer_question(...)`: builds the first message, invokes the graph, returns the row. |
| `prompts/agent.md` (new) | System prompt for agent mode. |
| [llm.py](filingroom/llm.py) | New function `complete_tools(...)` beside `complete_json`, sharing the meter, caps and refusal handling. `complete_json` is not edited. |
| [answer.py](filingroom/answer.py) | Lines 130 to 149 (verify quotes, set status, build the row) move into a function `build_row(...)` that both modes call. Behaviour-preserving; guarded by a test written first. |
| [pipeline.py](filingroom/pipeline.py) | `run_checklist` gains `mode="pipeline"`; records it in the run file's `meta`. |
| [evaluate.py](filingroom/evaluate.py) | `run` gains `mode="pipeline"`; a new free `compare` function. |
| [cli.py](filingroom/cli.py) | `--mode pipeline\|agent` on `ask`, `run`, `eval`; new `compare` command; `--max-steps`, `--max-tokens-per-question`. |
| `pyproject.toml`, `uv.lock` | `langgraph==1.2.24`. |

### The answer row

Agent rows carry every key a pipeline row has, with the same types, so [present.py](filingroom/present.py), [memo.py](filingroom/memo.py), [findings.py](filingroom/findings.py) and the judge read them unchanged. Mapping of the keys that need a decision:

- `retrieved`: every chunk id a tool showed the model. This keeps the "was the number in what the model saw" check meaningful.
- `k`, `expand`: `None` in agent mode.
- `seconds`: wall time for the whole loop.
- Two additive keys, on agent rows only: `mode: "agent"` and `agent: {model_calls, tool_calls, tokens, usd, stop, repairs, trace}`. `trace` is the ordered list of tool calls with their arguments and returned chunk ids, so any answer can be replayed by eye.

Pipeline rows get no new keys, so their output is identical to today's.

### Not in the first phase: the app

`server.py` keeps calling the pipeline. Putting agent mode in the app means a cost estimate shown before the run, resume rules for half-finished runs in a different mode, and UI copy, all of which CLAUDE.md asks to be designed. It is listed as a later increment.

## 6. Keeping the trust guarantees

- **Same verifier, literally.** Both modes call `answer.build_row`, which calls the existing `verify_quote`. There is one implementation of "does this quote appear in the chunk it names".
- **Same rule.** Answered with zero verified quotes becomes `unsupported`.
- **One extra diagnostic.** For each citation, record whether the cited chunk was ever shown to the model in this run. A verified quote from a never-shown chunk would mean the model answered from memory and got lucky; it should never happen, and the comparison reports the count.
- **Filing text is data.** Tool results are excerpts from SEC filings. The tools cannot write, fetch or act, and are scoped to one company, so text in a filing has nothing to hijack.

## 7. Evaluation: both modes, one answer key

### Running

- `./fr eval --mode agent --label <name>` answers the same golden items through the agent and grades them with the same grader and judge.
- Agent results are written to `results/agent/`, with their own changelog file. The existing Evaluation area and `latest_result` read only `results/*.json`, so the pipeline's history, trend and changelog stay clean.

### Comparing

`./fr compare <pipeline result> <agent result>` is free (no API calls) and prints:

| Metric | Source |
|---|---|
| Accuracy, overall and by grade type, with 95% Wilson intervals | `correct` on each row; `evalstats.py` |
| Items that flipped each way, with an exact sign test | paired by golden id; `evalstats.py` |
| Unsupported rate | existing `unsupported_claim_rate` |
| False "not found" and abstention precision | existing metrics |
| Verified-but-wrong (the app's trust metric) | `findings.derive_status`, as the Evaluation area does |
| Cost, total and per question | each run's meter |
| Latency: mean, median, 90th percentile | `seconds` on each row |
| Model calls and tool calls per question; share of questions that hit a limit | `agent` block (pipeline is 1 and 0 by definition) |

The pipeline side is the recorded run `results/2026-09-27_1616_recency.json` (93.6% on 80 items, $1.91 answering, 4.5 s mean per question), which costs nothing. Its latency was measured on a different day, so a fair latency comparison would run both modes in one session; the comparison in §14 did not, and its caveats say so.

### Two limits of the comparison

- **80 paired items cannot detect a small accuracy difference.** If agent mode lands within a few points, the honest finding is "no detectable difference in accuracy; here is what it cost". Cost, latency and tool calls will be unambiguous.
- **An agent run is one sample.** The model's path varies between runs. The intervals are there for that reason.

BOX stayed untouched during development. It was the pipeline's held-out company and unseen by agent mode, so one `--final` agent run at the very end gave a real held-out number; that run is in §14.

## 8. Tests

Stdlib `unittest`, like the existing suite; no pytest. The graph is tested with a scripted fake model, so every test is free and deterministic.

- **Pipeline unchanged.** Written before the refactor: with a stubbed model reply, `answer.answer_question` returns exactly the same row before and after `build_row` is extracted. Importing the CLI and running a pipeline answer does not load `langgraph`.
- **Tools.** Forms filter excludes other forms; topic and period boosts reorder; `k` is clamped; unknown form, topic or chunk id returns an error result; neighbours come back in reading order; an already-shown chunk is returned by id only; `list_filings` matches the manifest.
- **Loop and limits.** A fake model that always asks for tools is stopped at the step limit, `finalize` is called once with tools off, and a row comes out with `stop: step_limit`. Same for the token limit. The `recursion_limit` backstop yields an `error` row.
- **Verification.** A fabricated quote gives `unsupported`; a real quote gives `answered`; `not_found` passes through; with repair on, exactly one extra round runs.
- **Row shape.** An agent row has every key of a pipeline row with matching types, and passes through `present.eligible`, `memo.usable` and `findings.derive_status`.
- **Compare.** Fixed synthetic results in, expected table out.

## 9. Main risks

| Risk | Why it is real here | Handling |
|---|---|---|
| Cost grows with every step | Each loop turn resends the transcript so far. | Small `k`, already-shown rule, per-question token budget, prompt caching on the stable prefix, spot checks before any full run. Estimates in section 11. |
| Agent mode is less accurate than the tuned pipeline | The pipeline's retrieval was tuned and measured (100% retrieval recall on numeric items). The agent starts without those hints. | That is a result, not a failure. Report it. A "with hints" variant is a cheap follow-up experiment. |
| More false answers on "should be not found" items | An agent that keeps searching may find something loosely related and answer. Abstention precision is already the pipeline's weakest number (61.5%). | Same abstention wording in the prompt; watch the 8 abstain items in the first spot check. |
| The format-plus-tools behaviour differs from what I expect | Verified in docs as supported together, not yet exercised on this model. | One-cent spike in increment 4; `submit_answer` strict tool as fallback. |
| Framework surprises | Step counting per "super-step", thread safety of one compiled graph across six worker threads, and state on recursion error are not spelled out in the docs I read. | Increment 3 is a free spike with a fake model that pins each of these down with a test. Fallback for thread safety: compile one graph per worker. |
| Tracing leaves the machine | `langsmith` arrives as a transitive dependency. | Confirm default in source, force it off, test for it. |
| Eval history gets muddied | Agent results mixed into `results/` would bend the trend chart and "previous run" comparisons. | Separate folder and changelog. |
| Spend-cap accounting | `_command_spend` in `llm.py` counts only uncached input tokens. Harmless today because the pipeline never caches; wrong once agent mode caches. | `complete_tools` counts cached tokens at their real rates. Pipeline accounting is unaffected. |

## 10. Increments

Each ends with the full test suite passing and is small enough to review in one sitting. Paid steps are marked; each needed its cost confirmed before it ran.

1. **Guard the pipeline.** Characterisation test for `answer_question`, then extract `build_row`. No behaviour change. Free.
2. **Tools.** `agent/tools.py` and its tests. No framework yet. Free.
3. **Add LangGraph; graph skeleton with a fake model.** State, four nodes, edges, limits, backstop. Tests for limits and verification. Confirms step counting, thread safety and tracing-off. Free.
4. **Real model.** `llm.complete_tools`, `prompts/agent.md`, `./fr ask --mode agent`. Try three questions (a number, a list, one that should be not found). **Paid, about $0.20.**
5. **Whole checklist and spot checks.** `--mode` on `run` and `eval --only`; trace in the row. Spot-check five golden items. **Paid, about $0.40.**
6. **Comparison tooling.** `eval --mode agent` to `results/agent/`, `./fr compare`, tests. Free (compare runs against recorded files).
7. **Measure.** A 20-item stratified subset first. **Paid, about $1.50.** Then a separate decision on whether a full 80-item run is worth it (**estimated $4 to $6**, above the $3 per-command cap, so it needs an explicit raise). It was run; see §14.
8. **Repair edge.** Turn it on, rerun the subset, keep or drop on the numbers. **Paid, about $1.50.**
9. **Write it up.** README section with the comparison table; update CLAUDE.md (architecture, the dependency line, the eval notes) and the `pyproject.toml` description.

Later, each its own plan: agent mode in the app; the held-out BOX run (since made, §14); phase 2.

## 11. Cost estimate (made before the build; measured costs are in §14)

- **Pipeline today:** $0.024 and about 10,100 input tokens per question (from the recorded 80-item run).
- **Agent, typical guess:** two searches and one chunk read, four model calls, roughly $0.04 to $0.07 per question, so 1.5 to 3 times the pipeline. Prompt caching should pull this toward the low end; whether the prefix is long enough to cache on this model is checked in increment 4.
- **Agent, ceiling:** bounded by the per-question token budget at roughly $0.10.
- **Total to reach a first comparison (increments 4 to 7, subset only):** about $2.10.

## 12. Phase 2: multiple agents (noted, not built)

The single loop splits along lines the graph already has:

- **Planner** sits between `START` and `agent`. It reads the question and `list_filings` and writes a short plan into state: which filings, which sub-questions (for example "revenue this year" and "revenue last year" for a growth rate).
- **Researcher** is today's `agent` plus `tools` loop, wrapped as a subgraph. With a planner, one researcher can run per sub-question in parallel using LangGraph's `Send`.
- **Verifier** is today's `verify` node, extended. The string check stays deterministic and stays the gate. A model-based verifier could be added beside it to judge whether the quotes actually support the answer, which today only the eval judge and the memo claim check do.

Hand-off is through state: plan in, evidence out, verdict out. A further step is one orchestrator across the whole checklist, so a passage found for one question is available to the next; today the 40 questions are independent.

## 13. Decisions

1. **Framework:** LangGraph 1.2.24, pinned, over Pydantic AI or no framework (reasons in section 2). It was expected to bring about 25 transitive packages; it added 26 (§14).
2. **Model access:** Claude is called through the project's own `llm.py` (`llm.complete_tools`), not through `langchain` and `langchain-anthropic` as in the tutorials, so the cost meter, the spend caps and the refusal handling stay in one place (section 2).
3. **Model:** `claude-sonnet-5` at medium effort, the same as the pipeline, so the comparison isolates "who chooses the excerpts". A newer model would be a separate experiment.
4. **Hints:** the checklist's `where` and `search` hints are withheld from the agent. Withholding them is the experiment, and it matches the app's free-text questions, which have no hints (section 4).
5. **Spend:** about $2.10 across increments 4 to 7 for a first comparison, each step confirmed before it ran. The measured spend is in §14: $0.113 for increment 4, $0.177 for increment 5, and $3.70 for increment 7, which added the full 80-item run ($2.92) to the subset ($0.78).

Later decisions are recorded in §14 where they were made: the token budget raised from 30,000 to 100,000 after increment 4, the full 80-item run with the per-command cap raised to $4 for that one command, increment 8's paid run skipped, and the single held-out run on BOX.

## 14. What is verified and what is not

**Read in current docs or package metadata:** LangGraph version and dependencies; `StateGraph`, `TypedDict` state with reducers, `add_node`, `add_conditional_edges`, `START`/`END`; `recursion_limit` in the invoke config and `GraphRecursionError` from `langgraph.errors`; runtime context via `context_schema`; node timeouts are async-only; LangGraph does not require LangChain; the quickstart's hand-written tool node; Pydantic AI's built-in loop and `UsageLimits`; Anthropic tool use together with `output_config.format`, `strict` tools, and `tool_choice: none`.

**Not yet verified:** nothing assigned to increments 3 and 4 remains open; see the two sections below.

### Found in increment 3 (2026-11-21, langgraph 1.2.24, langsmith 0.16.0, langchain-core 1.8.4)

Each finding is pinned by a test in `tests/test_agent_graph.py` (class `SpikeTest` unless noted).

- **Dependency.** `uv add langgraph==1.2.24` added 26 packages and changed none: the `uv.lock` diff is additions only, and `anthropic` stays 1.8.0, `pydantic` 2.13.5. `httpx` 0.28.1 now sits beside the SDK's `httpx2`.
- **LangSmith tracing default: off, but easy to turn on by accident.** From the installed source: `langsmith.utils.tracing_is_enabled()` checks, in order, a context variable, an active run tree, a process-wide switch set by `langsmith.configure(enabled=...)`, and only then the environment. In the environment it reads `LANGSMITH_TRACING_V2`, then `LANGCHAIN_TRACING_V2`, then falls back to `LANGSMITH_TRACING` and `LANGCHAIN_TRACING`; the value must be exactly `"true"`. With none set, it is off. Two traps: (1) `LANGSMITH_TRACING=false` alone does **not** switch off a `LANGCHAIN_TRACING_V2=true` (the `_V2` names are checked first); (2) the environment lookup is cached (`functools.lru_cache`), so changing a variable after langsmith has read it does nothing. `langchain-core` adds tracers only when that same function says yes. **What the code does:** `graph.py`, before importing langgraph, sets all four variables to `false`, clears the cache, and calls `langsmith.configure(enabled=False)`, which takes precedence over the environment. **Tests:** with every tracing variable set to `true` and a LangSmith API key present, an agent run (fake model) makes zero socket connections and zero DNS lookups, builds no `langsmith.Client`, and `tracing_is_enabled()` is `False`. A control test shows the same environment does turn tracing on without the switch, and that `LANGSMITH_TRACING=false` alone does not.
- **How super-steps count against `recursion_limit`.** Each node run is one super-step (our nodes never run in parallel). Writing the input also counts as one, and the limit is checked *before* the "nothing left to run" check, so a path of n node steps needs `recursion_limit >= n + 1`: at exactly n, every node, `verify` included, has run and LangGraph still raises `GraphRecursionError`. Measured: the 12-step step-limit path (agent and tools five times each, finalize, verify) completes at 13 and raises at 12 after all 12 nodes ran. `graph.run` handles that edge (if `verify` had finished, its row is returned). The backstop is `2 * max_model_calls + 3`: at most M model calls run and every other step directly follows one, so a legal run is at most 2M steps. An exhaustive test over all 162 scripts at M = 4 (tool turns, fabricated answers, good answers; repair on and off) finds the longest legal path is exactly 2M (tool rounds all the way, then finalize and verify) and none reaches the backstop. Default `recursion_limit` is 10,007 (`LANGGRAPH_DEFAULT_RECURSION_LIMIT`).
- **Concurrent `invoke` from several threads: safe for this graph.** One compiled graph, six worker threads, twelve questions, a barrier so all six runs are inside the graph at the same time, and a fake model that asserts it sees only its own question and echoes the question id into its search queries and answer. Every row's `qid`, answer text, trace queries and counters match its own question (`GraphTest.test_one_compiled_graph_six_threads_no_state_crosses`). This fits how it is built (no checkpointer, so each call starts from fresh channels; the runtime context is passed per call), though I did not audit the scheduler's internals. So `compiled()` caches one graph per process; the fallback (one graph per worker) is not needed.
- **State after `GraphRecursionError`.** `invoke` raises and returns nothing; without a checkpointer the run's state is gone (the docs are silent, and there is nothing to read back). `graph.run` therefore uses `stream(stream_mode="values")`, which yields the full state after every super-step, and keeps the last one. On the error it builds an `error` row that still reports the model calls, tool calls, tokens, spend, trace and seen chunks up to the last completed step (`GraphTest.test_recursion_backstop_gives_an_error_row_with_partial_counts`).
- **Pipeline mode never loads the framework.** Importing `filingroom.cli`, `answer`, `pipeline`, `evaluate`, `filingroom.agent` and `filingroom.agent.tools`, then answering a question in pipeline mode, leaves `langgraph`, `langsmith` and `langchain_core` out of `sys.modules` (subprocess test).
- **A bug the tests caught in my own routing, not in the framework.** With the repair edge on, a repair round that started with one model call left could ask for tools and then `finalize` would make call M + 1. A repair now needs two calls of budget left. Repair stays off by default.

### Found in increment 4 (2026-11-21, `claude-sonnet-5`, effort medium, anthropic 1.8.0; paid, $0.113 in total)

Three BILL questions through `agent.answer_question` and `llm.complete_tools`, logged turn by turn (scratch script, not in the repo): `rev_total` (a number), then `debt_instruments` (a list) and `na_gross_retention` (should be not found) in a second process a few minutes later.

| Question | Result | Model calls | Tool calls | Tokens (budget measure) | Cost | Wall time |
|---|---|---|---|---|---|---|
| rev_total | answered, $1,653,160K, 1/1 quotes verified; matches the answer key | 3 | 2 | 17,807 | $0.0299 | 8.2 s |
| debt_instruments | answered, four instruments, 9/9 quotes verified; matches the answer key | 6 | 4 | 59,150 | $0.0588 | 25.6 s |
| na_gross_retention | not_found, notes the disclosed net retention rate instead; correct | 3 | 2 | 19,521 | $0.0240 | 7.8 s |

- **`anthropic` 1.8.0 accepts every parameter used**: `tools`, `output_config` (format and effort), a top-level `cache_control`, a `cache_control` on the system block, `tool_choice: none`, and a per-request `timeout` via `with_options`.
- **Assistant content sent back as dicts is accepted.** Blocks are dumped with `model_dump(mode="json", exclude_none=True)`; thinking blocks (empty text, as `display` defaults to omitted, plus a signature) went back unchanged on every later turn with no error. The SDK-object fallback is not needed.
- **The format constraint and tools together behave cleanly.** On every tool-calling turn the response held only `thinking` and `tool_use` blocks, with no text at all. Every final turn was a single `text` block of schema-valid JSON. `_parse_draft` joining text blocks is therefore safe, and the `submit_answer` fallback is not needed.
- **Prompt caching engages, within a question and across questions.** The tools-plus-system prefix is 2,778 tokens (more than my 1,500 estimate: the API adds its own tool-use preamble), above the 1,024 minimum. Within a question each call read the previous call's whole prompt from cache. The first call of each later question read exactly the 2,778-token prefix and wrote only the new question (225 to 283 tokens). The second process, started within five minutes of the first, also found the prefix warm.
- **Conversation caching pays even on three-call questions.** Cost with only the system-prompt breakpoint (everything after the prefix at the plain input rate), from the same usage: rev_total $0.0302 vs $0.0299 actual; na_gross_retention $0.0284 vs $0.0240; debt_instruments $0.1037 vs $0.0588. A two-call question (search, then answer) would lose a little; none occurred. Automatic caching stays on.
- **The token budget as defined binds early.** It sums input, cached input and output over calls, and each call resends the conversation, so it grows roughly with the square of the number of turns. debt_instruments passed 30,000 after its fifth call (cumulative 43,036) and its last tool request was refused; the forced answer was still complete. Effective cost was about $1.0 to $1.7 per million budget tokens. **Default raised to 100,000** (2026-11-21): none of the three questions would have reached it, the six-call limit binds first, and at the measured rate it caps a question at about $0.10 to $0.17. Re-checked on the increment 5 spot check and the 80-item run, since three questions are not a distribution (both below).
- **Behaviour worth watching.** The model made one tool call per turn throughout, never several, despite the prompt's advice. It opened two of three questions with `list_filings`, spending a turn on it. It passed `topics` once as a bare string, which the tool accepts. No question cited a chunk it had not been shown.

### Found in increment 5 (2026-11-21; paid, $0.177)

`./fr eval --only RPD:rev_nrr,BILL:na_cac,RPD:rev_customers,BILL:comp_ceo_total,RPD:op_nongaap_quarter --mode agent`: two expected not-found items, a "current" question, a proxy number and an earnings-release figure, three of them RPD. Graded by eye against the answer key (`--only` does not grade); the recorded pipeline run got all five right too.

| Item | Agent result | Calls / tools | Tokens | Cost | Time |
|---|---|---|---|---|---|
| BILL:comp_ceo_total | $16,139,836, correct | 2 / 1 | 11,946 | $0.026 | 5.7 s |
| BILL:na_cac | not_found, correct (notes S&M includes customer acquisition costs) | 2 / 1 | 10,527 | $0.015 | 5.0 s |
| RPD:rev_nrr | not_found, correct (names the metrics RPD does disclose) | 4 / 5 | 54,642 | $0.069 | 9.8 s |
| RPD:rev_customers | 11,772 with the definition, correct | 3 / 4 | 29,791 | $0.044 | 8.8 s |
| RPD:op_nongaap_quarter | $28.9M from the Q2 FY2026 release, correct | 3 / 2 | 19,885 | $0.022 | 7.2 s |

- **Eight agent questions so far** (increments 4 and 5): all correct; no limit hit at the 100,000 default. Budget tokens 10,527 to 59,150 (median about 19,700); cost $0.015 to $0.069, mean $0.036 per question against the pipeline's $0.024; wall time 5.0 to 25.6 s (median about 8 s) against the pipeline's 4.5 s mean.
- **Parallel tool calls do happen.** In the spike every turn held one call; here the two RPD questions with several searches put two in each turn.
- **The not-found guidance is followed loosely.** RPD:rev_nrr ran five searches over three turns before answering not_found, more than the prompt's "two or three", at $0.069 the costliest question here. It was right, and it would have hit the old 30,000 budget.
- **One wasted call:** RPD:op_nongaap_quarter asked `get_chunk` with no neighbours for a chunk it had just been shown, and got the "already shown" stub. Harmless here; worth counting in the subset.

### Found in increment 7 (2026-11-21; paid, $3.70: subset $0.78, full run $2.92)

**Subset.** 20 items drawn at random, stratified by company and grade (seed 20261121; `golden/agent-subset-20.txt`). Agent 19/20, the recorded pipeline run 20/20 on the same items (by chance none of the pipeline's five misses was drawn). The one miss, RPD:rev_customers, cited the press release's "over 11,500 customers" instead of the 10-Q's 11,772, which the same prompt had found in the increment 5 spot check.

**Full run.** `./fr eval --mode agent --full` on all 80 BILL and RPD items (run with `FILINGROOM_MAX_USD=4` for that one command, above the default $3 cap). Compared with the recorded pipeline run `results/2026-09-27_1616_recency.json` by `./fr compare` (`results/agent/2026-11-21_1047_agent80_compare.md`):

| Metric | Pipeline (recorded 2026-09-27) | Agent mode (2026-11-21) |
|---|---|---|
| Accuracy | 93.6% (73/78; 85.9–97.2) | 94.9% (74/78; 87.5–98.0) |
| Numeric / judged / abstain | 28/29 · 37/41 · 8/8 | 29/29 · 37/41 · 8/8 |
| Citation support (judge: yes, of answered) | 94.0% (63/67; 85.6–97.7) | 88.6% (62/70; 79.0–94.1) |
| Abstention precision | 61.5% (8/13) | 80.0% (8/10) |
| False not found (answerable items) | 6.9% (5/72) | 2.8% (2/72) |
| Verified but wrong (the app's status) | 3.1% (2/65) | 4.4% (3/68) |
| Answer cost per question | $0.0239 | $0.0295 |
| Latency mean / median / p90 | 4.5 / 3.8 / 7.3 s | 7.9 / 6.8 / 14.3 s |
| Model calls / tool calls per question | 1 / 0 | 2.92 / 2.24 |

- **Accuracy: no detectable difference.** Five items flipped, 3 to agent mode and 2 to the pipeline (sign test p = 1.00); the intervals overlap almost entirely.
- **What agent mode changed.** It recovered three of the pipeline's five false not-founds by searching again (BILL:rev_international, found on its sixth and last call; RPD:comp_sayonpay; RPD:gov_activist). It added one premature stop and one reading error. BILL:rev_customers is the premature stop: six chunks in BILL's index contain the 479,300 total, the agent was shown none of them (two searches in one turn with weak query words), took the 21,400 overlap figure from a passage it did see, and answered at high confidence after two calls; the pipeline, with the checklist's search words, was shown one of the six. RPD:gov_board is the reading error (it miscounted the directors). Both kept verified quotes, so the app would show both as Verified. The two misses both modes share (RPD:mgmt_ceo, RPD:cap_buyback_spend) are interpretation errors, not retrieval.
- **Citation support moved the other way.** The judge marked 8 of 70 agent answers only partly supported, against 4 of 67 for the pipeline. The pattern: the answer states things its quotes do not cover (the SOFR margins in BILL:debt_instruments, the US/international split in RPD:emp_count, AI-native entrants in BILL:comp_competitors), and RPD:op_income has the right number but says "up from $35.035 million" when the figure fell. The agent reads more passages and writes more than it quotes. Too few items to call significant; the direction and the mechanism are clear.
- **Cost depends on caching.** Agent mode read 2.14 times the pipeline's input tokens (1,729,997 against 808,017) but cost 1.23 times as much, because nearly all of it was cache reads and writes. The same calls with no caching would have cost about $3.99 (against the $2.36 paid), which is about 2.1 times the pipeline's $1.91 for answering: 2.1 times the tokens, 2.1 times the cost.
- **Run-to-run variation.** One of the 20 subset items changed grade between the two agent runs, minutes apart (RPD:rev_customers, right in the full run).
- **Budgets.** Budget tokens per question: median 17,972, 90th percentile 44,680, maximum 80,494, all under the 100,000 default, which stays. One question stopped at the step limit and was still right. No question cited a chunk it had not been shown; no repair round ran; no errors. 20 of 80 questions made several searches in one turn; 28 of 80 spent a model call on `list_filings`.
- **Caveats.** The pipeline side is one recorded run from 2026-09-27 and the agent side one run on 2026-11-21, so the latency ratio is indicative. BILL and RPD are the companies the pipeline's retrieval was tuned on, while the agent prompt was written once and not tuned on them; if anything that favours the pipeline. Neither number is held out (BOX was not used). The judge is a model, and four of the five flips are judged items.

**Increment 8 (repair edge): paid run skipped.** The repair round fires only on an answered draft with no verified quote. That happened 0 times in 80 questions and 0 in 20, so a paid run would have measured nothing. The edge stays built, off by default, and tested; its effect is unmeasured because its trigger never occurred, not shown to be nil.

**Follow-up ideas, unmeasured and not done:**
- Put the `list_filings` output in the first message, since 28 of 80 questions spent a model call on it.
- An answering rule that `answer` may state only what a quote backs, aimed at the drop in citation support.
- (Both change what the model is sent, so each would be a measured change, with `prompts/agent.md`'s "last moved" header updated.)

### The held-out run on BOX (2026-11-21; paid, $1.43; build total $5.41)

Run once, with `prompts/agent.md` as frozen at commit `62d729c` and the default budgets:

`./fr eval --mode agent --final --companies BOX --full --label HOLDOUT-box --note "held-out company, first and only agent-mode run; prompts/agent.md and budgets unchanged since the 80-item tune-set run"`

Cost $1.43 ($1.18 answering, $0.25 judging). Compared with the pipeline's held-out run `results/2026-09-27_1635_HOLDOUT-box.json` (`results/agent/2026-11-21_1100_HOLDOUT-box_compare.md`):

| Metric | Pipeline (2026-09-27) | Agent mode (2026-11-21) |
|---|---|---|
| Accuracy | 89.7% (35/39; 76.4–95.9) | 97.4% (38/39; 86.8–99.5) |
| Numeric / judged / abstain | 12/13 · 19/22 · 4/4 | 13/13 · 21/22 · 4/4 |
| Citation support (judge: yes, of answered) | 100% (33/33) | 97.1% (33/34) |
| False not found | 3/36 | 2/36 |
| Verified but wrong | 1/32 | 0/33 |
| Answer cost per question | $0.0248 | $0.0294 |
| Latency mean / median / p90 | 4.3 / 3.6 / 7.0 s | 7.2 / 6.0 / 12.0 s |
| Model calls / tool calls per question | 1 / 0 | 2.98 / 2.27 |

- **Flips: 3 better, 0 worse** (sign test p = 0.25). BOX:bs_cash and BOX:rev_customers were pipeline false not-founds (rev_customers found on the sixth call, at the step limit); BOX:gov_structure was a pipeline wrong answer. The one agent miss, BOX:ma_recent (the Alphamoon acquisition), is a false not-found in both modes, after five agent calls.
- **One step-limit stop**, no repairs triggered, no verified quote from an unseen chunk, no errors. Budget tokens: mean 22,478, maximum 81,237.
- **Citation support:** the tuning set's weaker support for agent answers (62/70 fully supported, against 63/67) did not show on BOX (33/34, against 33/33). Both are recorded; the difference is not explained.
- **Both sets together:** pipeline 108/117, agent mode 112/117; 6 flips better and 2 worse, exact two-sided sign test p = 0.29 (`evalstats.sign_test(6, 2)`). The same direction on both sets and a larger gap on the held-out company, mostly from questions where the pipeline's one search missed, but still short of a detectable accuracy difference.
- **BOX is now used** for agent mode: a later change to `prompts/agent.md` or the budgets cannot be validated on it as a held-out company again.

### Hybrid mode: the pipeline first, agent mode on its non-answers (2026-11-22; simulated, free)

**The rule.** `--mode hybrid` (`filingroom/hybrid.py`, CLI only) answers each question with the pipeline, called exactly as in pipeline mode. If that row's final status, after quote verification, is `not_found` or `unsupported`, agent mode answers the same question with the same meter and the agent budget flags, and its row replaces the pipeline's unless it is an `error` (then the pipeline's row is kept). A pipeline `error` is not escalated. The agent package, and langgraph with it, is imported only at the point of escalation (subprocess test). Rows have every pipeline key plus `mode: "hybrid"` and `hybrid` (escalated, the pipeline's status and time, and when escalated the agent's status and time and which answer was used); escalated rows also keep the agent's `agent` block, and their `seconds` is both steps. Evals follow the agent-mode rules: `--ids` or `--full`, results in `results/agent/` and `CHANGELOG-agent-evals.md`, BOX only with `--final`.

**Simulated result, not a live run.** From the recorded files `results/2026-09-27_1616_recency.json` and `results/agent/2026-11-21_1047_agent80.json` (BILL and RPD) and `results/2026-09-27_1635_HOLDOUT-box.json` and `results/agent/2026-11-21_1100_HOLDOUT-box.json` (BOX), taking the pipeline's row unless its status was `not_found`, in which case the agent's row. 117 graded items across the three companies:

| Metric | Pipeline | Agent mode | Hybrid (simulated) |
|---|---|---|---|
| Correct | 108 | 112 | 112 |
| "Not found" graded wrong | 6 | 2 | 2 |
| Citation support (judge: yes, of answered) | 96/100 | 95/104 | 101/105 |
| Answer cost per question, against the pipeline | 1.00x | 1.22x | 1.30x |
| Mean latency, against the pipeline | 1.00x | 1.74x | 1.37x |

- **Against the pipeline: 4 better, 0 worse** (BILL:rev_international, RPD:comp_sayonpay, BOX:bs_cash, BOX:rev_customers); exact sign test p = 0.125, so not a detectable difference.
- **Escalations: 20 of 120 questions** (6 BILL, 7 RPD, 7 BOX), all pipeline `not_found`. No pipeline row was `unsupported` or `error`, so that part of the trigger is unmeasured.
- **Abstention held.** On the 12 items where not disclosed is the right answer, the agent also returned not found on all 12.
- **Cost.** Not-found questions are the agent's most expensive (about $0.043 each, against its $0.030 average), so 20 escalations in 120 questions cost more than their share suggests: 1.30x the pipeline, roughly $0.29 extra per company.
- **What it cannot fix.** A wrong answer the pipeline returns as answered is never escalated, which is why the hybrid misses RPD:gov_activist and BOX:gov_structure, both of which agent mode got right.
- **Caveats.** The rule was chosen after both modes' results, BOX included, had been seen, so this is an in-sample estimate and not a held-out result. Each escalated item reuses one agent sample. The recorded agent costs assume the shared prompt prefix was cached; with only 6 or 7 escalations per company, the cost of writing that cache is spread over fewer questions, so the real cost could be slightly higher. The latencies combine runs from September and November. Hybrid mode itself has not been run live.
