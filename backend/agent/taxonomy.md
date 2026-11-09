# Failure taxonomy

The diagnoser picks exactly one category per cluster. The list is closed: the category must be one of the headings below, spelled exactly as written. The examples are synthetic and contain no clinical content.

How to choose:

- Name the **cause**, not the symptom. "The answer was empty" is a symptom; "the retriever's filter excludes the drug-interaction category" is a cause.
- Pick the category the evidence supports. If the cited spans do not point to one cause, choose `unknown` and say what is missing. A wrong guess is worse than `unknown`.
- Cite real trace ids and span ids from the cluster. A diagnosis without evidence is not accepted.

## retrieval_miss

**Definition.** The retriever returned nothing, or nothing relevant, so the model answered without the sources it needed. The failure is in what was fetched, not in what the model did with it.

**Example.** `retrieve` returns 0 chunks for every drug-interaction question, and `generate` then answers without sources. A filter on the retriever excludes that document category.

## tool_schema_error

**Definition.** A tool call was rejected or misbehaved because the arguments the model sent do not match the tool's input schema: a missing or renamed field, a wrong type, an unexpected value.

**Example.** `execute_tool lookup_dosage` fails validation with `missing required field 'dose_unit'`, because the tool's schema gained a required field that the prompt and the model do not know about.

## context_overflow

**Definition.** The prompt grew past the model's context window, so the request was rejected or the input was cut off. The cause is how much was put in, not what was put in.

**Example.** `generate` fails with `context length exceeded: 9000 tokens > 8192` on long guideline documents, because the retrieved text is concatenated without a size limit.

## prompt_regression

**Definition.** A change to the prompt (an edit, a truncation, a new template version) removed or weakened an instruction the app depended on, so behavior changed without any error.

**Example.** The system prompt is cut off after its first paragraph, so the instruction to cite a source for every dosage is lost and answers stop carrying citations, with no error in any span.

## model_quality

**Definition.** Retrieval, tools and prompt all worked, but the model itself produced a wrong, ungrounded or low-quality answer. This is the category to use only after those causes are ruled out, for example after a switch to a weaker model.

**Example.** `retrieve` returns the right chunks and the prompt is intact, but after the model was swapped for a smaller one the answers ignore the retrieved context and score low on groundedness.

## infra_error

**Definition.** A dependency or the platform failed: a timeout, a rate limit, an unavailable upstream service, a network or credential problem. The app's own logic and prompts are not at fault.

**Example.** `execute_tool fetch_guidelines` fails with `upstream timeout after 30000 ms` on a share of calls, because the guideline service does not answer in time.

## system_design

**Definition.** The multi-agent system is built in a way that makes the failure likely: unclear roles, missing or contradictory instructions, a flawed workflow, or no stopping condition. The fix is in the design, not in one step. (MAST category, for multi-agent targets.)

**Example.** Two agents are both told to finalize the answer, and neither is told to stop. The run loops until it hits the step limit.

## inter_agent_misalignment

**Definition.** Agents in a multi-agent system fail to work from the same understanding: one ignores or misreads another's output, information is not passed on, or they pursue different goals. (MAST category, for multi-agent targets.)

**Example.** A planner agent asks for adult dosing, but the executor agent never receives the patient's age and answers with pediatric dosing.

## task_verification

**Definition.** Nothing in the system checked that the result was correct or complete, so a wrong or unfinished answer was returned as done. (MAST category, for multi-agent targets.)

**Example.** The final answer cites a guideline that was never retrieved, and no step compares the answer with its sources before it is returned.

## unknown

**Definition.** The evidence in the cluster does not support any other category, or supports several equally. State what is missing and which trace or span would settle it. Never use `unknown` to avoid naming a cause that the evidence does support.

**Example.** Ten traces fail with an empty answer, but `retrieve` returned chunks, the prompt is intact and no span carries an error, so retrieval, prompt and model quality all remain possible.
