You judge one request to an LLM application from its trace, and say whether it failed its user.

The trace is a tree of spans as JSON. Each span has an id, a name, timing, a status (`ok`, `error` or `unset`), a status message, attributes and events. Most span names and `gen_ai.*` attributes follow the OpenTelemetry GenAI semantic conventions, which are still in development: `invoke_agent <app>` is the whole request, `chat <model>` a model call and `execute_tool <tool>` a tool call. The rest is the application's own: `retrieval <source>` is a search of the application's data (the conventions name that span just `retrieval`), and its `retrieval.hits` attribute, which is not in the conventions, is how many results the search found. Some attribute values read `[redacted]`: they were removed on purpose, do not guess them. No question, answer or record text is ever in the trace.

Judge the outcome for the user, not the presence of errors:

- An error the application recovered from is not a failure. Recovery means the work was done after all: a later call of the same tool or step that succeeded.
- A model call that completes after a failed step is not a recovery by itself. A model answers whether or not it got what it asked for, so a final answer only shows that the request ended, not that it was served. When the model called a tool or a search, its result was what the answer needed: if that step failed or returned nothing, and nothing did the same work again, the request failed its user, even though the last model call succeeded.
- An error that is the application working as designed is not a failure, for example a lookup whose error says that the thing asked for does not exist, after which the model tells the user so.
- A request can fail with no error at all, for example a search that returned 0 results, after which the model answered without the data it went to find.
- Judge only what the trace shows. A step that completed without an error did its work unless the trace shows it came back empty (such as 0 hits); a result the trace does not record is not a reason to doubt it. A request with no error and no empty result went fine.
- When the trace does not show enough to decide, say so in the reason and score in the middle.

For a failed request, also say whose fault it is. The application is the agent itself: its prompts, its tool calls and their arguments, its retrieval, the limits it sets (timeouts, context size) and how it handles errors. Outside it are the model provider, the services its tools call and the network.

- `app`: the cause is the application's own behaviour. This includes an outside error it did not handle well: no retry of a transient error, a timeout set too tight, no fallback, a failure passed on to the user unexplained.
- `external`: the cause is outside the application, and it handled it as well as it reasonably could.
- `unclear`: the trace does not show which.

Whose fault it is does not change the score: a request that failed its user scores low either way.

Answer with:

- `reason`: one or two sentences on what went well or badly, naming the steps by span name. Ids, names and counts only: never copy attribute values or messages that could hold personal or clinical data.
- `score`: from 0.0 (the request failed its user) to 1.0 (it went fine).
- `blamed_span_id`: for a failed request, the id of the span where the failure started, which must be a span id of the trace shown. The cause, not where it surfaced: an error usually marks every span up to the root, so prefer the deepest span that explains it. Null for a request that went fine.
- `attribution`: for a failed request, `app`, `external` or `unclear` as above. Null for a request that went fine.
