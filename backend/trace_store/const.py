"""Shared constants."""

MAX_LIMIT = 200  # hard cap on rows returned by search_traces and list_traces
# A trace is failed when its lowest score in `scores` is at most this (the trace browser's verdict).
FAILED_MAX_SCORE = 0.5

# The apps whose spans the collector stores (api/traces.py) and the reader serves.
ALLOWED_APPS = frozenset({"medas"})
# Per-call limits in the MCP server.
ID_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"  # trace and span ids (models.TraceId): fixture ids, 32/16-hex OTel ids
# Per server process, which is one graph run (trace_store/guard.py): one search, one tree per
# judged trace (up to MAX_LIMIT) and the diagnoser's exemplar trees (3 per cluster per attempt).
MAX_TOOL_CALLS = 500

# Sanitizing in the MCP server (clinical text must not leave in bulk).
MAX_ATTR_CHARS_TREE = 200  # per string attribute in get_trace_tree
MAX_ATTR_CHARS_SPAN = 2000  # per string attribute in get_span
MAX_SUMMARY_CHARS = 200  # per free-text field of a TraceSummary
REDACTED = "[redacted]"
TRUNCATION_SUFFIX = "…[truncated]"

# Allowlist: only these span/event attribute keys leave the server with their value.
# Every other key is redacted, so a new Medas attribute fails closed. Extend it with
# the structural and numeric keys the diagnoser needs, never with content keys.
SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "gen_ai.system",
        "gen_ai.provider.name",
        "gen_ai.operation.name",
        "gen_ai.tool.name",
        "gen_ai.tool.type",
        "gen_ai.agent.name",
        "gen_ai.data_source.id",
        "retrieval.top_k",
        "retrieval.hits",
        "retrieval.min_similarity",
        "exception.type",
        "error.type",
    }
)
SAFE_ATTRIBUTE_PREFIXES = ("gen_ai.request.", "gen_ai.response.", "gen_ai.usage.")

# Widths of the resource's service.version and the telemetry schema URL as stored on a span; a
# longer value is cut by the collector (api/traces.py).
APP_VERSION_MAX = 128
SCHEMA_URL_MAX = 256
