You judge one request to an LLM application from its trace, and say whether it failed its user.

The trace is a tree of spans as JSON. Each span has an id, a name, timing, a status (`ok`, `error` or `unset`), a status message, attributes and events. Most span names and `gen_ai.*` attributes follow the OpenTelemetry GenAI semantic conventions, which are still in development: `invoke_agent <app>` is the whole request, `chat <model>` a model call and `execute_tool <tool>` a tool call. The rest is the application's own: `retrieval <source>` is a search of the application's data (the conventions name that span just `retrieval`), and its `retrieval.hits` attribute, which is not in the conventions, is how many results the search found. On the root span, `medas.reply.format` says whether the answer had the shape the application asks its model for: `ok`, `no_severity` (the triage code missing) or `malformed` (not that shape at all). Some attribute values read `[redacted]`: they were removed on purpose, do not guess them. No question, answer or record text is ever in the trace.

Judge the outcome for the user, not the presence of errors:

- An error the application recovered from is not a failure. Recovery means the work was done after all: a later call of the same tool or step that succeeded.
- A model call that completes after a failed step is not a recovery by itself. A model answers whether or not it got what it asked for, so a final answer only shows that the request ended, not that it was served. When the model called a tool or a search, its result was what the answer needed: if that step failed or returned nothing, and nothing did the same work again, the request failed its user, even though the last model call succeeded. This holds when the model asked for several steps and only one of them failed: each was asked for because the answer needed it, the others working does not stand in for the one that failed, and not knowing how much the answer missed it is no reason to call the request unsure. Blame the step that failed.
- An error that is the application working as designed is not a failure, for example a lookup whose error says that the thing asked for does not exist, followed by a model call that completed: that call is the model telling the user so. The trace never holds the answer, so its absence is no reason to doubt it.
- A request can fail with no error at all, for example a search that returned 0 results, after which the model answered without the data it went to find.
- A request can also fail by going round in circles. Each `chat` span is one round of the model; the tool calls between two rounds are what the model asked for in the first. When round after round asks for the same tool or search again, four rounds or more, although each call completed, the model is not getting or not keeping what it asked for: the request failed its user, even though nothing errored and an answer came at the end. Several calls in one round are normal, and so are a few rounds that each ask for something different. Blame the first `chat` span that asked for the same step again.
- Judge only what the trace shows. A step that completed without an error did its work unless the trace shows it came back empty (such as 0 hits); a result the trace does not record is not a reason to doubt it. A request with no error, no empty result and no step asked for round after round went fine.
- When the trace does not show enough to decide, say so in the reason and score 0.6. A score of 0.5 or less means the request failed, so keep those for requests the trace shows failed.

For a failed request, also say whose fault it is. The application is the agent itself: its prompts, its tool calls and their arguments, its retrieval, the limits it sets (timeouts, context size) and how it handles errors. Outside it are the model provider, the services its tools call and the network.

- `app`: the cause is the application's own behaviour. This includes an outside error it did not handle well: no retry of a transient error, a timeout set too tight, no fallback, a failure passed on to the user unexplained.
- `external`: the cause is outside the application, and it handled it as well as it reasonably could.
- `unclear`: the trace does not show which.

Whose fault it is does not change the score: a request that failed its user scores low either way.

Answer with:

- `reason`: one or two sentences on what went well or badly, naming the steps by span name. Ids, names and counts only: never copy attribute values or messages that could hold personal or clinical data.
- `score`: from 0.0 (the request failed its user) to 1.0 (it went fine).
- `blamed_span_id`: for a failed request, the id of the span where the failure started, which must be a span id of the trace shown. The cause, not where it surfaced: an error usually marks every span up to the root, so prefer the deepest span that explains it. When more than one step failed, blame the one that ended the request: the failure after which nothing went on to serve the user, usually the last. A failed step the request carried on after still counts towards the score, but is not the one to blame. Null for a request that went fine.
- `attribution`: for a failed request, `app`, `external` or `unclear` as above. Null for a request that went fine.
- `healthy_span_ids`: for a request that went fine, up to 3 ids of `chat`, `execute_tool` or `retrieval` spans that completed, returned something, and whose result the request used: examples of a step working. Never the root, a span with an error, or a step a retry had to redo. Empty for a failed request; an empty list is always a good answer.
