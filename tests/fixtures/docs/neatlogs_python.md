<!-- Source: https://docs.neatlogs.com/sdk/python | Scraped: 2026-10-10 -->

![](https://docs.neatlogs.com/_next/image?url=%2F_next%2Fstatic%2Fmedia%2Fai-search-bg.167zcr41zs-bg.webp&w=3840&q=75&dpl=dpl_AEK4uzZMSGiTh9Xt85bE4DU7XPHH)

[![Neatlogs](https://docs.neatlogs.com/_next/image?url=%2F_next%2Fstatic%2Fmedia%2Flogo.0052vjd_bglpj.webp&w=256&q=75&dpl=dpl_AEK4uzZMSGiTh9Xt85bE4DU7XPHH)docs](https://docs.neatlogs.com/docs)

Search
`⌘`  `K`

[GitHub](https://github.com/NeatLogs/neatlogs)

[Documentation](https://docs.neatlogs.com/docs) [Ask AI](https://docs.neatlogs.com/ask) [Guides](https://docs.neatlogs.com/guides) [SDK Reference](https://docs.neatlogs.com/sdk) [Integrations](https://docs.neatlogs.com/integrations) [Public API](https://docs.neatlogs.com/api-reference) [CLI](https://docs.neatlogs.com/cli)

SDK Reference

[SDK Overview](https://docs.neatlogs.com/sdk)

SDKs

[Python SDK](https://docs.neatlogs.com/sdk/python) [TypeScript SDK](https://docs.neatlogs.com/sdk/typescript) [Go SDK](https://docs.neatlogs.com/sdk/go) [SDK Doctor](https://docs.neatlogs.com/sdk/doctor) [Browser SDK](https://docs.neatlogs.com/sdk/browser) [HTTP Trace Injection](https://docs.neatlogs.com/sdk/http-injection) [OpenTelemetry (OTLP)](https://docs.neatlogs.com/sdk/opentelemetry) [Distributed Tracing](https://docs.neatlogs.com/sdk/distributed-tracing)

Configuration

[Sessions](https://docs.neatlogs.com/sdk/sessions) [Tags](https://docs.neatlogs.com/sdk/tags) [Workflow Name](https://docs.neatlogs.com/sdk/workflow-name) [Multiple Workflows in One Codebase](https://docs.neatlogs.com/sdk/multiple-workflows) [Secondary Clients](https://docs.neatlogs.com/sdk/secondary-clients) [Flush and Shutdown](https://docs.neatlogs.com/sdk/lifecycle) [Custom Attributes](https://docs.neatlogs.com/sdk/custom-attributes) [Prompt Templates and Managed Prompts](https://docs.neatlogs.com/sdk/prompt-templates) [PII Redaction](https://docs.neatlogs.com/sdk/pii-redaction) [End-User Identity](https://docs.neatlogs.com/sdk/end-user-identity)

Concepts

[Span Kinds](https://docs.neatlogs.com/sdk/span-kinds) [Python Auto-Instrumentation](https://docs.neatlogs.com/sdk/supported-libraries)

[GitHub](https://github.com/NeatLogs/neatlogs)

Python SDKInstall

# Python SDK

Copy PageCopied!

Install, initialize, and instrument Python LLM and agent apps with Neatlogs.

The Python SDK installs from PyPI as `neatlogs`. Use the latest published stable release. Wrap the AI clients you already use, add spans to your own functions, and track prompt templates — every call is captured as a trace in your dashboard. This page covers everything from install to the full `init()` reference; use the contents on the right to jump around.

Note

New to tracing? A **trace** is the record of one run of your app; a **span** is one step inside it (an LLM call, a tool call). You **instrument** once, then read traces in the dashboard. See [Introduction](https://docs.neatlogs.com/docs/quickstart/introduction).

## [Install](https://docs.neatlogs.com/sdk/python\#install)

pip

poetry

uv

```
pip install -U neatlogs
```

To auto-instrument a specific library, install its extra (same `-U` rule applies):

```
pip install -U "neatlogs[openai]"      # OpenAI
pip install -U "neatlogs[anthropic]"   # Anthropic
pip install -U "neatlogs[langchain]"   # LangChain / LangGraph
pip install -U neatlogs                # CrewAI (instrument with neatlogs.wrap(crew))
```

Requires Python ≥ 3.10, < 3.14. See [Supported Libraries](https://docs.neatlogs.com/sdk/python#supported-libraries) for every key.

## [Check the installed SDK with Doctor](https://docs.neatlogs.com/sdk/python\#check-the-installed-sdk-with-doctor)

From the application root, run the network-free check before changing
instrumentation:

```
python -m neatlogs doctor --local --json
```

After instrumenting and running your normal checks, set the project key through
your environment or secret manager and run the authenticated probe separately:

```
python -m neatlogs doctor --probe --json
```

Use the active project interpreter; do not download or invoke a different
Doctor binary. Require Doctor v2 format, Python runtime, and schema `2`. If the
installed package lacks that capability, check PyPI for the latest published
stable release and ask before upgrading. Accept newer compatible releases and
never downgrade one. A local pass validates controlled in-process capture only.
A probe pass additionally proves exact finalized readback of its own four-span
trace, but neither replaces testing your real workflow. See [SDK Doctor](https://docs.neatlogs.com/sdk/doctor)
for the full pass criteria, reason codes, and safe troubleshooting steps.

## [Your first trace](https://docs.neatlogs.com/sdk/python\#your-first-trace)

Call `neatlogs.init()` once, then wrap your AI client with `neatlogs.wrap(...)`. From then on every call that client makes is recorded — you use the client exactly as before.

Note

**EU projects:** add `endpoint="https://eu.ingest.neatlogs.com"` to `neatlogs.init(...)`. Use the base URL, without `/v1/traces`.

```
neatlogs.init(
    api_key=os.environ["NEATLOGS_API_KEY"],
    endpoint="https://eu.ingest.neatlogs.com",
    workflow_name="my-first-app",
)
```

OpenAI

Anthropic

Google Gemini

```
import os
import neatlogs

neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], workflow_name="my-first-app")

from openai import OpenAI

client = neatlogs.wrap(OpenAI())

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
)
print(response.choices[0].message.content)

neatlogs.flush()
neatlogs.shutdown()
```

Run the script — a trace appears in your dashboard under `my-first-app` within a few seconds. The parentless `LLM` span is a valid trace root and shows the prompt, response, token counts, latency, and model name. No blank `WORKFLOW` wrapper is added. Standalone non-root operations such as `TOOL` receive one automatic workflow parent.

Note

`neatlogs.wrap()` auto-detects the client type and works for OpenAI, Anthropic, Google GenAI, Azure OpenAI, Bedrock, Vertex AI, OpenRouter, and agent frameworks like CrewAI, Pydantic AI, DSPy, Agno, Google ADK. You can wrap the client wherever you build it — order doesn't matter. See [Integrations](https://docs.neatlogs.com/integrations) for every supported client, with runnable examples.

Extra keyword arguments to `wrap()` are stamped on the resulting trace root as `neatlogs.workflow.<key>` attributes, so they show in the metadata drawer and are searchable:

```
client = neatlogs.wrap(OpenAI(), project_id="p_123", route="/api/chat", surface="copilot")
```

Session and end-user identity are the exception — those go through `neatlogs.identify(...)`, not `wrap()` kwargs. See [Sessions](https://docs.neatlogs.com/sdk/sessions).

## [flush() and shutdown()](https://docs.neatlogs.com/sdk/python\#flush-and-shutdown)

The SDK batches spans and exports them in the background every few seconds. A short-lived script can exit before that fires, losing spans — so `neatlogs.flush()` forces an immediate export and `neatlogs.shutdown()` stops the background thread cleanly.

```
neatlogs.flush()
neatlogs.shutdown()
```

Always call both at the end of **scripts and CLI tools**. In **long-running servers** (FastAPI, Flask, …) the background thread exports continuously, so don't flush per request — call `flush()` \+ `shutdown()` **once at server shutdown** (for example, in a FastAPI lifespan handler). Reused serverless handlers should flush each invocation without shutting down a warm process. See [Flush and Shutdown](https://docs.neatlogs.com/sdk/lifecycle) for workers, streams, tests, secondary clients, and bounded teardown.

## [Auto-instrumentation](https://docs.neatlogs.com/sdk/python\#auto-instrumentation)

Instead of `wrap()`, you can patch a library by name with `instrumentations=[...]` in `init()`. This works for providers that create clients internally.

```
neatlogs.init(
    api_key=os.environ["NEATLOGS_API_KEY"],
    workflow_name="my-app",
    instrumentations=["openai"],
)
```

For **LangChain / LangGraph**, use the callback handler — it's the only supported path, and works identically across Python and TypeScript. `instrumentations=["langchain"]` has no self-rooting (confirmed root cause of production trace loss) and is not offered as an alternative:

```
neatlogs.init(api_key=os.environ["NEATLOGS_API_KEY"], workflow_name="my-app")

from langchain_openai import ChatOpenAI

handler = neatlogs.langchain_handler()
llm = ChatOpenAI(model="gpt-4o")
result = llm.invoke("Hello", config={"callbacks": [handler]})
```

See [LangChain](https://docs.neatlogs.com/integrations/langchain) for the full picture, including the LangGraph-specific attachment rule (graph invocation, not per-node).

Warning

**The one rule for `instrumentations=[...]`:** call `neatlogs.init()` **before** you import that library — auto-instrumentation patches it at init time, so a library imported first is missed. (`neatlogs.wrap()` has no such rule; it patches the specific client object you hand it.) If you use `load_dotenv()`, call it before `init()`. Google GenAI is stricter still: construct `genai.Client()` _after_`init()`.

`init()` creates an SDK-private tracer provider and never installs it as the process-global provider. Call it once per active SDK generation; after `shutdown()` you may explicitly initialize a new generation.

## [Instrument your own code with @span](https://docs.neatlogs.com/sdk/python\#instrument-your-own-code-with-span)

`wrap()` and auto-instrumentation only see library calls. To make **your own functions** (custom agents, pipelines, tools) appear as steps, put `@neatlogs.span(...)` on the line directly above the function.

```
import neatlogs

@neatlogs.span(kind="WORKFLOW")
def handle_request(user_input: str) -> str:
    return support_agent(user_input)

@neatlogs.span(kind="AGENT", name="support_agent")
def support_agent(message: str) -> str:
    ...

@neatlogs.span(kind="TOOL", tool_name="get_order_status")
def get_order_status(order_id: str) -> dict:
    return orders_db.get(order_id)
```

Works on sync and async functions. The decorator captures the arguments as `input.value` and the return value as `output.value`.

Note

**Grouping calls into one trace.** A single `wrap()`-ed call renders on its own — `wrap()` opens a `WORKFLOW` root automatically. But each call with no surrounding context becomes its _own_ trace, so when a run makes several calls (or mixes provider calls with your own functions), decorate the entry point with `@neatlogs.span(kind="WORKFLOW")` (or `AGENT`/`CHAIN`). That function becomes the single root and everything nests under it; the automatic root steps aside.

### [The WORKFLOW root](https://docs.neatlogs.com/sdk/python\#the-workflow-root)

A `WORKFLOW` span is the entry point of a trace — the outermost function you call to process one request or task. Decorating it makes that function the trace's single, meaningfully-named root, and everything it calls (your own `@span` functions, wrapped provider calls, auto-instrumented libraries) nests underneath in the order it ran:

```
@neatlogs.span(kind="WORKFLOW")
def handle_customer_request(message: str) -> str:
    intent = classify_intent(message)
    if intent == "order_status":
        return check_order_agent(message)
    return general_support_agent(message)
```

If you don't add one, Neatlogs opens a `WORKFLOW` root automatically so a lone instrumented call still renders cleanly. Decorate your own entry point when you want the root to carry a specific name and group several steps under it.

> Running several independent features in one process (a copilot, a summarizer, a background job)? Give each its own named `WORKFLOW` root at its entry point so they appear as distinct workflows in the dashboard — see [Multiple Workflows in One Codebase](https://docs.neatlogs.com/sdk/multiple-workflows).

### [A complete multi-span example](https://docs.neatlogs.com/sdk/python\#a-complete-multi-span-example)

```
import os
import json
import neatlogs

neatlogs.init(
    api_key=os.environ["NEATLOGS_API_KEY"],
    workflow_name="support-bot",
)

from openai import OpenAI

client = neatlogs.wrap(OpenAI())

@neatlogs.span(kind="TOOL", tool_name="get_order_status")
def get_order_status(order_id: str) -> dict:
    return {"order_id": order_id, "status": "shipped", "eta": "2025-01-20"}

@neatlogs.span(kind="AGENT", name="support_agent")
def support_agent(message: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[\
            {"role": "system", "content": "You are a support agent."},\
            {"role": "user", "content": message},\
        ],
        tools=[{\
            "type": "function",\
            "function": {\
                "name": "get_order_status",\
                "description": "Get the status of an order",\
                "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}},\
            }\
        }],
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        args = json.loads(msg.tool_calls[0].function.arguments)
        return str(get_order_status(**args))
    return msg.content

@neatlogs.span(kind="WORKFLOW")
def handle_request(user_input: str) -> str:
    return support_agent(user_input)

handle_request("Where is my order #12345?")

neatlogs.flush()
neatlogs.shutdown()
```

The nesting reflects the actual call hierarchy at runtime — each decorated function appears exactly where it ran, with its inputs, outputs, and timing:

```
WORKFLOW  handle_request           0.8s
  AGENT   support_agent            0.8s
    LLM   gpt-4o                   0.6s
    TOOL  get_order_status         0.0s
```

### [Decorator ordering](https://docs.neatlogs.com/sdk/python\#decorator-ordering)

When you stack `@neatlogs.span` with a framework decorator that **transforms** the function (`@function_tool`, `@tool`, `@task`), put `@neatlogs.span` **below** it — closest to `def` — so it wraps the real function:

```
# CORRECT — @function_tool wraps the span-decorated function
@function_tool
@neatlogs.span(kind="TOOL", tool_name="search")
def search(query: str) -> str:
    ...
```

Decorators that preserve the callable (`@app.get`, `@app.post`) can sit either side.

### [@span parameters](https://docs.neatlogs.com/sdk/python\#span-parameters)

| Parameter | Kind | Description |
| --- | --- | --- |
| `kind` | All | **Required.** The span kind (see [Span kinds](https://docs.neatlogs.com/sdk/python#span-kinds)). |
| `name` | All | The span's **label** in the tree. Defaults to the function name. |
| `role` | `AGENT` | The agent's role (also sets `agent.name`). |
| `goal` | `AGENT` | The agent's objective. |
| `tool_name` | `TOOL`, `MCP_TOOL` | The **tool identifier** (sets `tool.name`). Distinct from `name`: `name` is the label, `tool_name` is what the dashboard groups/reports on. |
| `parameters` | `TOOL` | Tool parameter schema (dict). |
| `description` | `TOOL`, `MCP_TOOL` | Human-readable tool description. |
| `capture_input` | All | Record the arguments (default `True`). |
| `capture_output` | All | Record the return value (default `True`). |
| `mask` | All | `(span_dict) -> span_dict`, applied before export for this span. |

To omit content for one span, pass `capture_input=False` and/or `capture_output=False`. To redact or transform captured telemetry for the whole client, use `mask`; there is no global trace-content switch. See [PII Redaction](https://docs.neatlogs.com/sdk/pii-redaction).

## [Span kinds](https://docs.neatlogs.com/sdk/python\#span-kinds)

`@neatlogs.span()` accepts these eight kinds:

| Kind | Use for |
| --- | --- |
| `WORKFLOW` | Top-level entry point — one per trace root |
| `AGENT` | A reasoning step that calls an LLM and decides what to do next |
| `CHAIN` | A fixed sequence of steps with no branching LLM decisions |
| `TOOL` | A function the agent calls to interact with the world |
| `RETRIEVER` | A vector search or document lookup (custom retrievers) |
| `EMBEDDING` | A function that produces embeddings |
| `GUARDRAIL` | A safety or validation check |
| `MCP_TOOL` | A tool exposed over the Model Context Protocol |

Passing any other kind raises `ValueError`. The kinds `RERANKER` and `VECTOR_STORE` are created with `trace()` (below); `LLM` comes from `wrap()` / auto-instrumentation. For the complete catalogue of every kind, see [Span Kinds](https://docs.neatlogs.com/sdk/span-kinds).

## [Inline spans with trace()](https://docs.neatlogs.com/sdk/python\#inline-spans-with-trace)

`with neatlogs.trace(...)` opens a span for a block **inside** a function — use it for prompt-template tracking (below), for custom span kinds (`RERANKER`, `VECTOR_STORE`), or to set attributes yourself on custom retrieval/guardrail logic that Neatlogs doesn't already recognize.

```
with neatlogs.trace(
    name,
    kind=None,
    system_prompt_template=None,
    user_prompt_template=None,
    version=None,
    mask=None,
) as span:
    ...
```

Supported libraries (vector DBs, framework retrievers) are captured automatically — you only set attributes for **custom** implementations:

```
import json
import neatlogs

@neatlogs.span(kind="CHAIN")
def rag_pipeline(query: str) -> str:
    with neatlogs.trace("retrieve", kind="RETRIEVER") as span:
        span.set_attribute("neatlogs.retriever.query", query)
        docs = my_custom_search(query, k=5)   # not a supported library
        span.set_attribute("neatlogs.retriever.documents", json.dumps(docs))
    return generate(query, docs)
```

The `neatlogs.*` attribute names each custom kind expects (`RETRIEVER`, `RERANKER`, `VECTOR_STORE`, `GUARDRAIL`, `EMBEDDING`, `TOOL`) are listed in [Custom Attributes](https://docs.neatlogs.com/sdk/custom-attributes).

## [Prompt templates](https://docs.neatlogs.com/sdk/python\#prompt-templates)

Capture both the template structure and the runtime variable values for an LLM call, linked to its span. `SystemPromptTemplate` is the system/instruction prompt; `UserPromptTemplate` is the user turn. Pass them to `trace(kind="LLM", ...)` around the call:

```
import neatlogs
from neatlogs import SystemPromptTemplate, UserPromptTemplate

system_template = SystemPromptTemplate([\
    {"role": "system", "content": "You are a {{role}} assistant."},\
])
user_template = UserPromptTemplate([\
    {"role": "user", "content": "{{question}}"},\
])

@neatlogs.span(kind="AGENT")
def answer_agent(question: str) -> str:
    with neatlogs.trace("answer", kind="LLM",
                        system_prompt_template=system_template,
                        user_prompt_template=user_template):
        msgs = system_template.compile(role="support") + user_template.compile(question=question)
        return client.chat.completions.create(model="gpt-4o", messages=msgs).choices[0].message.content
```

For prompts managed centrally in the dashboard, the module-level functions (`neatlogs.get_prompt`, `create_prompt`, `update_prompt`, …) are available after `init()`. See [Prompt Templates](https://docs.neatlogs.com/sdk/prompt-templates) for managed prompts and the full API.

Note

`PromptTemplate` and the `prompt_template=` keyword are backward-compatible aliases for `SystemPromptTemplate` / `system_prompt_template=`. New code should use the canonical names.

## [Log capture](https://docs.neatlogs.com/sdk/python\#log-capture)

Log capture is **opt-in** — pass `capture_logs=True` to `init()`. Neatlogs then records logs as `LOG` spans (children of the active span) so they appear inline in the trace timeline. Without it, none of the three mechanisms below capture anything.

```
neatlogs.init(api_key="...", capture_logs=True)

@neatlogs.span(kind="CHAIN")
def rag_pipeline(query: str) -> str:
    docs = retrieve(query)
    neatlogs.log("retrieved {count} docs", count=len(docs))
    return generate(query, docs)
```

### [1\. `neatlogs.log()` — structured template messages](https://docs.neatlogs.com/sdk/python\#1-neatlogslog--structured-template-messages)

The primary way to emit a named, structured step. The **message template** becomes the span name (low-cardinality, searchable) and each keyword argument is stored as a `log.{key}` attribute.

```
neatlogs.log(msg_template, /, level="info", **data)
```

| Parameter | Description |
| --- | --- |
| `msg_template` | Message template with `{key}` placeholders. Stored as the span name. |
| `level` | Log level: `"info"`, `"debug"`, `"warning"`, `"error"`. Default: `"info"`. |
| `**data` | Key-value pairs rendered into the template and stored as `log.{key}` attributes. |

Templates use Python's `str.format_map()` syntax — single braces `{count}`, not `{{count}}`. `neatlogs.log()` must be called **inside an active span** (`@neatlogs.span` or `with neatlogs.trace()`); calls outside a traced block are dropped.

```
neatlogs.log("retrieved {count} docs, top score {score:.2f}",
             count=len(docs), score=docs[0]["score"])
```

When `init(debug=True)`, every `neatlogs.log()` call is also echoed to `stderr` immediately, so you can watch steps in the terminal without opening the dashboard:

```
[neatlogs] 12:34:56  LOG  retrieved 42 docs, top score 0.94  count=42  score=0.94
```

### [2\. stdlib `logging.*()` — auto-captured](https://docs.neatlogs.com/sdk/python\#2-stdlib-logging--auto-captured)

Any `logging.debug()` / `info()` / `warning()` / `error()` call inside a traced block is captured automatically — no code changes. All levels are captured by default; raise the floor with `log_level="WARNING"` in `init()` to capture only `WARNING` and above.

### [3\. `capture_stdout=True` — print capture](https://docs.neatlogs.com/sdk/python\#3-capture_stdouttrue--print-capture)

Pass `capture_stdout=True` to `@neatlogs.span` or `with neatlogs.trace()` to capture every `print()` line inside that block as a LOG span. Output is still mirrored to the real stdout — capture does not suppress terminal output.

```
@neatlogs.span(kind="AGENT", capture_stdout=True)
def run_agent(query: str) -> str:
    print(f"Processing query: {query}")   # captured as a LOG span
    return agent.invoke(query)
```

### [What you'll see in the dashboard](https://docs.neatlogs.com/sdk/python\#what-youll-see-in-the-dashboard)

Each log call produces a `LOG` span as a child of the active span, with these fields:

| Field | Source |
| --- | --- |
| **Span name** | `neatlogs.log()`: the message template. stdlib/print: the rendered message. |
| `input.value` | The fully rendered log message. |
| `log.level` | `info`, `warning`, `error`, etc. |
| `log.{key}` | Each kwarg from `neatlogs.log()`, e.g. `log.count`, `log.score`. |

## [Framework & provider helpers](https://docs.neatlogs.com/sdk/python\#framework--provider-helpers)

Beyond `instrumentations=[...]`, a few helpers attach tracing to a specific object:

- **`neatlogs.wrap(client)`** — the main path; wraps an LLM client or agent (OpenAI, Anthropic, Bedrock, Vertex, OpenRouter, CrewAI, Pydantic AI, DSPy, Agno, Google ADK, Hermes).
- **`neatlogs.langchain_handler()`** — a LangChain callback handler to pass in `config={"callbacks": [...]}`.
- **`neatlogs.openai_agents_processor()`** — a trace processor for the OpenAI Agents SDK.
- **`neatlogs.strands_hooks(agent)`** — registers hooks on a Strands agent.
- **`neatlogs.bind_templates(...)` / `register_crewai_task(...)`** — attach prompt templates to CrewAI work.

Each provider and framework has a runnable example in [Integrations](https://docs.neatlogs.com/integrations).

## [Cross-process propagation](https://docs.neatlogs.com/sdk/python\#cross-process-propagation)

To keep **one logical trace** across a service boundary, carry the active span as W3C `traceparent`/`tracestate` headers: the caller injects, the callee extracts. Both helpers use Neatlogs' **private** propagator — they never read or replace the global OTel propagator, so this stays isolated from a co-tenant tracer.

```
import neatlogs

# Caller — inject before sending. Returns False (carrier untouched) if no span is active.
with neatlogs.trace("caller"):
    headers = {"content-type": "application/json"}
    if neatlogs.inject_trace_context(headers):
        requests.post(url, headers=headers, json=payload)

# Callee — extract to continue the trace. Re-bind identity here (it does NOT ride the wire).
with neatlogs.extract_trace_context(
    req.headers,
    session_id=sid,
    parent_session_id=parent_sid,
    session_custom_fields={"feature_name": feature, "entry_point": "api"},
    end_user_id=uid,
):
    with neatlogs.trace("do_work"):   # joins the caller's trace as a child
        ...
```

Use these instead of a bare `opentelemetry.propagate.inject(...)`, which reads the global propagator and writes nothing under isolation. For the full cross-language walkthrough — including a Go or TypeScript peer — see [Distributed Tracing](https://docs.neatlogs.com/sdk/distributed-tracing).

## [Supported libraries](https://docs.neatlogs.com/sdk/python\#supported-libraries)

Pass these to `instrumentations=[]` (install the matching extra first).

**LLM providers:**`openai`, `anthropic`, `google_genai`, `azure_ai_inference`, `bedrock`, `litellm`, `cohere`, `groq`, `mistralai`, `together`, `ollama`, `replicate`, `openrouter`

**Agent frameworks:**`crewai`, `openai_agents`, `pydantic_ai`, `dspy`, `agno`, `google_adk`, `strands`, `autogen`, `haystack`, `smolagents`, `hermes`

**Vector databases:**`chromadb`, `pinecone`, `qdrant`, `weaviate`, `milvus`, `elasticsearch`

**Other:**`mcp`, `instructor`, `guardrails`

Warning

**LangChain / LangGraph are not in this list on purpose.**`instrumentations=["langchain"]` has no self-rooting and is not offered — use `neatlogs.langchain_handler()` instead (see [LangChain](https://docs.neatlogs.com/integrations/langchain)). Every other agent framework above self-roots via `instrumentations=[...]` alone.

Note

For CrewAI, `instrumentations=["crewai"]` installs class-level hooks on `Crew.kickoff`, `Task`, `Agent`, `BaseTool.run` and `LLM.call`, so a bare crew gets a full tree with no provider key and no `wrap()`. Use `neatlogs.wrap(...)` on top when you want to bind workflow metadata, or when you run a **Flow** or a **standalone Agent** — those are routed per instance and aren't covered by the key alone.

The install commands, minimum package versions, and important compatibility limits are maintained in the [tested support table](https://docs.neatlogs.com/sdk/supported-libraries). Documentation checks verify that every advertised integration names its actual activation mechanism; a registry key alone is not treated as proof that a provider works.

## [init() reference](https://docs.neatlogs.com/sdk/python\#init-reference)

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key` | `str` | `NEATLOGS_API_KEY` env | Project API key. If unset, spans are created but not exported. |
| `endpoint` | `str` | `https://ingest.neatlogs.com` | Backend base URL; set to `https://eu.ingest.neatlogs.com` for EU projects. Trace export is normalized to `{base_url}/v1/traces`. |
| `workflow_name` | `str` | script filename | Label all traces from this process appear under. |
| `instrumentations` | `list[str]` | — | Libraries to auto-instrument. |
| `tags` | `list[str]` | — | Tags attached to every trace. |
| `user_id` | `str` | — | Operator/service identity (a developer, a service account, a CI job). Propagates to all spans as `user.id`. Distinct from the end-user — see [End-User Identity](https://docs.neatlogs.com/sdk/end-user-identity). |
| `capture_logs` | `bool` | `False` | Capture `neatlogs.log()`, stdlib logging, and `print()` as LOG spans. |
| `log_level` | `str` | `"INFO"` | Minimum stdlib log level to capture. |
| `sample_rate` | `float` | `1.0` | Fraction of traces to export. |
| `flush_interval` | `float` | `5.0` | Seconds between background batch flushes. Lower it for short-lived workers that can't wait; raise it to batch more aggressively. |
| `batch_size` | `int` | `100` | Max spans per export request. |
| `mask` | `callable` | — | Client-side telemetry transform. Sync and awaitable callbacks run at the exporter boundary; callback error, timeout, cancellation, or an invalid return drops the item. For compatibility, `None` means “export the mutated clone.” |
| `pii_enabled` | `bool` | project setting | Override server-side PII redaction. Persisted — the dashboard reflects what you pass. |
| `pii_entities` | `list[str]` | project setting | Which server-side entity categories to redact, e.g. `["PERSON", "EMAIL_ADDRESS"]`. Persisted. Must be a non-empty list of non-blank strings or `init()` raises `ValueError`; omit it to keep the saved selection. |
| `pii_span_types` | `list[str]` | project setting | Limit redaction to specific span kinds. Persisted. |
| `debug` | `bool` | `False` | Verbose logging to stderr. |
| `isolate` | `bool` | — | Deprecated compatibility option. Neatlogs is always isolated; this option cannot opt into the global provider. |
| `tracer_provider` | `TracerProvider` | — | A private provider you created (but did **not** install as the OTel global). Neatlogs configures and flushes it but does not register it globally or shut it down. |
| `register_shutdown_handlers` | `bool` | `True` | Register bounded signal handling. Set `False` only when the host owns signal handling and calls `shutdown()` itself. |
| `uploads_enabled` | `bool` | `False` | Enable authenticated typed-media and oversized-OTLP uploads; can also be enabled with `NEATLOGS_UPLOADS_ENABLED`. |

`flush_all()` drains the default pipeline and every live secondary Neatlogs client without touching foreign/global providers. For lifecycle guidance see [Flush and Shutdown](https://docs.neatlogs.com/sdk/lifecycle). For PII redaction details see [PII Redaction](https://docs.neatlogs.com/sdk/pii-redaction); to group multi-turn conversations see [Sessions](https://docs.neatlogs.com/sdk/sessions); to attach your app's users to traces see [End-User Identity](https://docs.neatlogs.com/sdk/end-user-identity).

Building in Node.js? See the [TypeScript SDK](https://docs.neatlogs.com/sdk/typescript).

[SDK Overview\\
\\
Pick your platform and instrument your application in minutes.](https://docs.neatlogs.com/sdk) [TypeScript SDK\\
\\
Install, initialize, and instrument TypeScript/Node.js LLM and agent apps with Neatlogs.](https://docs.neatlogs.com/sdk/typescript)

### On this page

[Install](https://docs.neatlogs.com/sdk/python#install) [Check the installed SDK with Doctor](https://docs.neatlogs.com/sdk/python#check-the-installed-sdk-with-doctor) [Your first trace](https://docs.neatlogs.com/sdk/python#your-first-trace) [flush() and shutdown()](https://docs.neatlogs.com/sdk/python#flush-and-shutdown) [Auto-instrumentation](https://docs.neatlogs.com/sdk/python#auto-instrumentation) [Instrument your own code with @span](https://docs.neatlogs.com/sdk/python#instrument-your-own-code-with-span) [The WORKFLOW root](https://docs.neatlogs.com/sdk/python#the-workflow-root) [A complete multi-span example](https://docs.neatlogs.com/sdk/python#a-complete-multi-span-example) [Decorator ordering](https://docs.neatlogs.com/sdk/python#decorator-ordering) [@span parameters](https://docs.neatlogs.com/sdk/python#span-parameters) [Span kinds](https://docs.neatlogs.com/sdk/python#span-kinds) [Inline spans with trace()](https://docs.neatlogs.com/sdk/python#inline-spans-with-trace) [Prompt templates](https://docs.neatlogs.com/sdk/python#prompt-templates) [Log capture](https://docs.neatlogs.com/sdk/python#log-capture) [1\. `neatlogs.log()` — structured template messages](https://docs.neatlogs.com/sdk/python#1-neatlogslog--structured-template-messages) [2\. stdlib `logging.*()` — auto-captured](https://docs.neatlogs.com/sdk/python#2-stdlib-logging--auto-captured) [3\. `capture_stdout=True` — print capture](https://docs.neatlogs.com/sdk/python#3-capture_stdouttrue--print-capture) [What you'll see in the dashboard](https://docs.neatlogs.com/sdk/python#what-youll-see-in-the-dashboard) [Framework & provider helpers](https://docs.neatlogs.com/sdk/python#framework--provider-helpers) [Cross-process propagation](https://docs.neatlogs.com/sdk/python#cross-process-propagation) [Supported libraries](https://docs.neatlogs.com/sdk/python#supported-libraries) [init() reference](https://docs.neatlogs.com/sdk/python#init-reference)

`⌘I`

Ask Neatlogs AI

Answers from the docs

How can I help?

Ask anything about instrumenting, tracing, or the Neatlogs dashboard.

How do I instrument my Python app?What is a trace vs a span?How do I trace OpenAI calls?How do I import traces from Langfuse?