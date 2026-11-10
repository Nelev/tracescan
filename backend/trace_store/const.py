"""Shared constants."""

MAX_LIMIT = 200  # hard cap on rows returned by search_failed_traces

# The apps whose spans the collector stores (api/traces.py) and search_failed_traces serves.
ALLOWED_APPS = frozenset({"medas"})
# Per-call limits in the MCP server.
ID_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"  # trace and span ids (models.TraceId): fixture ids, 32/16-hex OTel ids
MAX_TOOL_CALLS = 300  # per server process, which is one graph run (trace_store/guard.py)

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
        "retrieval.top_k",
        "retrieval.hits",
        "retrieval.min_similarity",
        "exception.type",
    }
)
SAFE_ATTRIBUTE_PREFIXES = ("gen_ai.request.", "gen_ai.response.", "gen_ai.usage.")
