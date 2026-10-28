# GeoAgent backend

FastAPI hosts the agent APIs, local file storage, GeoServer retrieval and PostGIS integration.
Supported chat providers are configured through the existing vLLM, Kimi and DeepSeek modules.

When vLLM is reached through a host SSH tunnel, containers use
`VLLM_BASE_URL=http://host.docker.internal:18000/v1`. Both Compose configurations
map this hostname to `host-gateway`, including when custom DNS is configured.
vLLM connections time out after 10 seconds; response inactivity defaults to
120 seconds (override with the positive integer `VLLM_REQUEST_TIMEOUT`). Requests
retry once. Streaming waits preserve pending model/tool events across cancellation
polls and report provider failures as SSE errors instead of empty successful replies.

Uploads and generated artifacts use local storage. GeoServer search defaults to local
hashing embeddings, with SQLite vector storage and an in-memory fallback.
The shared environment template explicitly sets `EMBEDDING_PROVIDER=hashing`,
`USE_OPENAI_EMBEDDINGS=false` and an empty custom embedding factory.
Configure a GeoServer source and preload its metadata before querying.
See [local storage and search](../docs/local-storage-and-search.md) for configuration,
persistence and the optional local semantic-embedding interface.

Follow [CONTRIBUTING.md](../CONTRIBUTING.md) for setup, running, tests and linting.
Component references: [tests](tests/README.md) and [agent tools](services/tools/README.md).

LangSmith tracing uses the existing LangChain integration. Chat and streaming runs
include conversation/thread metadata, model identity and the database audit run ID.
See [LangSmith tracing and manual evaluation](../docs/langsmith-evaluation.md) for
environment configuration, trace navigation and the geospatial review rubric.

Plan mode is enforced per request, including when enabled after ordinary chat or
after an earlier confirmed plan. Before confirmation, only `create_execution_plan`
is executable; business and MCP tools are described in the planning catalog but
cannot run. Creating the plan ends the invocation immediately. Confirming the
pending plan enables its execution in a separate request. Dynamic tool selection
cannot remove the planner, and previous confirmations in chat history do not
authorize a new task.

Multi-turn chat preserves complete tool-call messages (including empty assistant
content), call IDs and provider metadata in both JSON and SSE responses. Incoming
history accepts canonical and legacy function-call formats; unmatched tool outputs
are omitted from model context rather than converted to user instructions. After
context pruning or summarization, tool pairs are validated again. Responses retain
the full visible conversation even when the model uses a shorter context window.
Conversation persistence distinguishes repeated calls by their IDs and arguments.

Before each model call, the base instructions, map state, memory and conversation
summary are combined into a single leading system message. This supports chat
templates such as Qwen that reject a second system message once long conversations
trigger summarization. Four-turn regressions cover both JSON and SSE endpoints,
with pruning and repeated summarization enabled.
