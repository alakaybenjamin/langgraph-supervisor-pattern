<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# i have a requirment in which there is a chat interface for a data governance app.

based on the inferred user intent it must route one of 3 flows

1. request acess to data product (search > select > fill form > sumbit
2. information q\&a on the request access process
3. check status of exisiting request

now my framework of choice is langgraph.
i need to know which agentic pattern i must use

to be taken in consideration:
a. what if the user in the
middle of flow one asks a question intended to be answered by 2

b. what if the user in the middle of flow 1 wants to check for status

Use a **supervisor + handoff pattern with resumable state**, not a single monolithic agent. In your case, the best fit is a **hybrid LangGraph design**: one top-level intent router/supervisor, plus one subgraph for the multi-step access request flow, and two simpler agents/tools for FAQ and status checks. [^1_1][^1_2][^1_1]

## Recommended pattern

LangGraph documents several multi-agent architectures, but for your use case the most suitable one is **Supervisor** or **Supervisor (tool-calling)**, where a supervisor decides which specialized agent or subgraph should run next. This pattern is specifically meant for cases where you want modularity, specialization, and explicit control over communication between agents. [^1_2]

Your three capabilities are not equal in complexity, so do **not** model all three as peer agents with the same shape. A better split is:

- **Access-request subgraph** for flow 1, because it is multi-step and stateful.
- **FAQ agent/tool** for flow 2, because it is mostly stateless Q\&A.
- **Status-check agent/tool** for flow 3, because it is short, transactional, and may need backend lookup. [^1_2]


## Best structure

I would model it like this:

- **Top-level supervisor/router**
- **request_access_subgraph**
- **process_faq_agent**
- **request_status_agent**
- **shared conversation state + flow-specific state** [^1_2][^1_1]

The reason is that LangGraph supports custom workflows where deterministic parts can coexist with dynamic routing, and it also supports handoffs through `Command`, which lets a node both update state and route to another node. That is exactly what you need when a user switches intent mid-conversation. [^1_2]

## Why not pure routing only

A simple one-time router at the start is not enough, because your user can change intent in the middle of flow 1. LangGraph’s docs emphasize handoffs and dynamic control flow with `Command`, which is better than static routing when execution must move between agents based on the latest user turn. [^1_2]

So the pattern is not just “intent classification.” It is:

1. **Route initially**
2. **Maintain active flow context**
3. **Allow interrupting handoff to another specialized agent**
4. **Resume the suspended flow if appropriate** [^1_2]

## How to handle flow 1

Flow 1 should be a **subgraph with explicit states**, such as:

- `search_data_product`
- `select_data_product`
- `collect_form_fields`
- `confirm_submission`
- `submit_request` [^1_2]

This is better than leaving all of flow 1 to an LLM agent, because parts of it are deterministic and UI-driven. LangGraph explicitly supports custom workflows where some control flow is predefined and only selected parts are dynamic. [^1_2]

In practice, the subgraph state should hold things like:

- `active_flow = "request_access"`
- `current_step`
- `selected_product`
- `form_draft`
- `pending_question`
- `suspended_flow` [^1_2]


## Your case a

If the user is midway through flow 1 and asks a question meant for flow 2, the supervisor should **temporarily hand off to the FAQ agent**, answer the question, and then return control to the request-access subgraph with the prior state preserved. LangGraph describes handoffs as passing both a destination and payload, typically through `Command`, so this is a native fit for your interruption case. [^1_2]

Example:

- User is filling justification.
- User asks: “Who approves this request?”
- Supervisor detects informational intent.
- Handoff to `process_faq_agent`.
- FAQ agent answers.
- Supervisor returns to `request_access_subgraph` with `current_step = collect_form_fields`. [^1_2][^1_1]

This is effectively **interrupt-and-resume**. The key design rule is: treat the FAQ as a **side quest**, not as abandonment of flow 1, unless the user explicitly pivots away. [^1_2]

## Your case b

If the user is midway through flow 1 and says they want to check request status, that is usually not just a side question; it is often a **true intent switch**. In that case, the supervisor should hand off to the `request_status_agent`, but preserve the in-progress request-access state so the user can resume later. [^1_2]

A good policy is:

- If the utterance is a short informational question, use **temporary interruption** and resume flow 1 automatically.
- If the utterance is an operational request like “check my request status,” use **context switch with resumability**. [^1_2]

After status is shown, the assistant can say something like: “Your existing request is pending approval. Do you want to continue the new access request you were filling?” That keeps the orchestration explicit and avoids accidental continuation. [^1_2]

## Concrete recommendation

The best pattern for you is a **hierarchical supervisor-lite design**:

- One **top-level supervisor/router**
- One **state-machine subgraph** for request access
- Two **specialized worker agents/tools** for FAQ and status
- **Handoffs via `Command`**
- **Suspend/resume support in graph state** [^1_2][^1_1]

I would **not** use a fully open-ended network of peer agents, because your domain has a clear control center and business workflow. LangGraph notes that supervisor architectures fit cases where a central node decides what should be called next, while network architectures are better when there is no clear hierarchy. [^1_2]

## Implementation guidance

A practical orchestration policy would be:


| Situation | Pattern | Behavior |
| :-- | :-- | :-- |
| First user turn | Supervisor routing | Choose access, FAQ, or status. [^1_2] |
| In flow 1, user asks a process question | Temporary handoff | Answer with FAQ agent, then resume same step. [^1_2] |
| In flow 1, user asks to check status | Intent switch handoff | Run status agent, preserve draft state. [^1_2] |
| After status answer | Supervisor decision | Ask whether to resume draft or stay in status context. [^1_2] |
| In flow 2 or 3, user wants to start access request | Handoff into subgraph | Initialize flow 1 state and enter first needed step. [^1_2] |

## Design rule

The main architectural rule is: **separate conversation intent from workflow state**. The supervisor decides the current intent, while the request-access subgraph owns the workflow state and can be suspended/resumed safely. LangGraph’s stateful graph model and `Command`-based handoffs are designed for exactly this kind of controlled, stateful orchestration. [^1_2]

## My answer in one line

Use a **supervisor/tool-calling supervisor pattern with a stateful request-access subgraph and handoff-based interruption/resume**. That gives you clean routing, mid-flow FAQ handling, and status-check diversion without losing the user’s place. [^1_2][^1_1]

If you want, I can next sketch the **exact LangGraph state schema and node graph** for this app in Python.
<span style="display:none">[^1_10][^1_11][^1_12][^1_13][^1_14][^1_15][^1_3][^1_4][^1_5][^1_6][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: https://langchain-ai.github.io/langgraph/concepts/multi_agent/

[^1_2]: https://blog.langchain.com/langgraph-multi-agent-workflows/

[^1_3]: https://docs.langchain.com/oss/python/langchain/multi-agent

[^1_4]: https://langchain-ai.github.io/langgraph/how-tos/multi_agent/

[^1_5]: https://www.youtube.com/watch?v=ICBL6VHruZc

[^1_6]: https://reference.langchain.com/python/langgraph/supervisor/

[^1_7]: https://docs.langchain.com/oss/python/langgraph/interrupts

[^1_8]: https://www.youtube.com/watch?v=hvAPnpSfSGo

[^1_9]: https://reference.langchain.com/python/langgraph-supervisor

[^1_10]: https://docs.langchain.com/oss/python/langchain/human-in-the-loop

[^1_11]: https://aws.amazon.com/blogs/machine-learning/build-a-multi-agent-system-with-langgraph-and-mistral-on-aws/

[^1_12]: https://towardsdatascience.com/how-agent-handoffs-work-in-multi-agent-systems/

[^1_13]: https://dev.to/jamesbmour/interrupts-and-commands-in-langgraph-building-human-in-the-loop-workflows-4ngl

[^1_14]: https://launchdarkly.com/docs/tutorials/agents-langgraph

[^1_15]: https://www.youtube.com/watch?v=B_0TNuYi56w


---

# cool. i have a follow up question. does subgraphs reside under the same threadid when using checkpointer mechanism?

Yes — **if you compile only the parent graph with a checkpointer, subgraphs inherit the same `thread_id` and store their checkpoints under that parent thread**. LangGraph’s subgraph persistence docs say you should pass the checkpointer to the **parent** graph, and it is then propagated to child subgraphs automatically. [^2_1][^2_2]

## Practical rule

Use **one `thread_id` for the whole conversation tree**, including the parent graph and nested subgraphs, when they represent the same user session. The docs also show that subgraph state can be inspected with `subgraphs=True` under that same parent thread. [^2_3][^2_1]

## What this means

- Parent graph gets `config={"configurable": {"thread_id": "main-thread"}}`.
- Subgraphs run inside that same persisted conversation context.
- You can resume the whole workflow later with the same `thread_id`. [^2_2][^2_1]


## Important caveat

Don’t compile the subgraph with its own separate checkpointer unless you have a very specific reason. LangGraph’s docs explicitly say the checkpointer should be passed when compiling the **parent** graph, and not the subgraph, because the parent propagates persistence to children. [^2_1]

## Mental model

Think of `thread_id` as the **conversation/session ID**, not the agent ID. Subgraphs are just nested execution scopes inside that same session, so they normally share the same persisted thread unless you intentionally design a separate persistence boundary. [^2_2][^2_1]

If you want, I can draw the exact **parent graph + subgraph state layout** for your access-request app, including where to store `active_flow`, `step`, and `suspended_context`.
<span style="display:none">[^2_10][^2_4][^2_5][^2_6][^2_7][^2_8][^2_9]</span>

<div align="center">⁂</div>

[^2_1]: https://langchain-ai.github.io/langgraph/how-tos/subgraph-persistence/

[^2_2]: https://www.mintlify.com/langchain-ai/langgraph/concepts/checkpointing

[^2_3]: https://docs.langchain.com/oss/python/langgraph/use-subgraphs

[^2_4]: https://docs.langchain.com/oss/python/langgraph/persistence

[^2_5]: https://github.com/langchain-ai/langgraph/issues/5639

[^2_6]: https://www.reddit.com/r/LangChain/comments/1iof5rk/how_does_thread_id_and_state_persistence_work/

[^2_7]: https://github.com/langchain-ai/langgraph/issues/3206

[^2_8]: https://stackoverflow.com/questions/79607143/how-to-implement-subgraph-memory-persistence-in-langgraph-when-parent-and-subgra

[^2_9]: https://www.kurrent.io/blog/langgraph-checkpointer-on-kurrentdb/

[^2_10]: https://developer.couchbase.com/tutorial-langgraph-persistence-checkpoint/


---

# can subgraphs communiate directly to user. im asking because i intend the search, form to be interactive via an MCP App

Yes — **subgraphs can absolutely drive user interaction**, but usually **not as an independently user-facing chat endpoint**. In LangGraph, the user-facing surface is still the **top-level graph/app thread**, while the subgraph can pause, emit prompts, and wait for input via `interrupt()`, and those interrupts propagate back up to the caller. [^3_1][^3_2]

## What that means for MCP

If your **search UI** and **form UI** are rendered through an MCP App, a subgraph can be the part that decides **what UI should be shown next** and **what payload is needed**, then raise an interrupt with a JSON-serializable payload like:

- `type: "search_data_product"`
- `type: "select_data_product"`
- `type: "fill_access_form"`
- `type: "confirm_submission"` [^3_1]

Your frontend or MCP host receives that interrupt payload from the **top-level invocation**, renders the appropriate interactive app, collects user input, and resumes the same thread with `Command(resume=...)`. That is the intended human-in-the-loop pattern in LangGraph. [^3_1]

## Key distinction

So the answer is:

- **Yes**, a subgraph can initiate interaction with the user.
- **No**, it typically does so **through the parent graph runtime**, not by bypassing the parent and talking to the user on its own private channel. [^3_1][^3_2]

LangGraph’s interrupt docs say the payload from `interrupt()` is surfaced to the caller, and resumption happens by reinvoking the graph with `Command(resume=...)` on the same `thread_id`. The subgraph docs also note that interrupts still propagate to the top-level graph regardless of nesting. [^3_1][^3_2]

## Best fit for your app

For your data-governance use case, this is actually a strong design:

- The **request_access subgraph** owns the flow logic.
- It emits MCP-oriented UI intents through `interrupt()`.
- The **chat container/top-level supervisor** remains the single orchestration boundary.
- The MCP App handles rich interaction for search and forms. [^3_1][^3_2]

That lets flow 1 be highly interactive without forcing every step into plain chat text. [^3_1]

## Suggested pattern

Have the subgraph produce **structured UI requests**, not raw prose. For example, the interrupt payload can include:

- `ui_mode`
- `title`
- `form_schema`
- `search_filters`
- `selected_product`
- `draft_values`
- `resume_contract` [^3_1]

Then your MCP App can render the right widget and return a structured response like:

- selected product
- edited form values
- cancel
- ask a side question [^3_1]


## Important caveat

If you call a subgraph **inside a tool function or hidden indirection**, state inspection becomes more limited, but interrupts still propagate upward. The subgraph docs explicitly say viewing subgraph state does not work through such indirection, even though interrupts still reach the top-level graph. [^3_2]

So for your use case, if the access flow is central and interactive, it is cleaner to make it a **real subgraph node** under the parent graph, not bury it inside a tool call. [^3_2]

## Recommended architecture

A good architecture for your case is:

- **Supervisor graph** as the only chat-facing entrypoint.
- **Access-request subgraph** as a node.
- Inside that subgraph, each step uses `interrupt()` to request MCP UI interaction when needed.
- Resume all user actions back through the same parent `thread_id`. [^3_1][^3_2]

That gives you:

- one conversation thread,
- one orchestration surface,
- interactive MCP search/form steps,
- and safe interruption/resume when the user asks FAQ or status mid-flow. [^3_1][^3_2]


## Practical answer

So in plain terms: **yes, subgraphs can “communicate” with the user by emitting interrupt payloads that your MCP App renders, but the communication is mediated by the top-level LangGraph run rather than being a separate direct user session.** [^3_1][^3_2]

If you want, I can next show you a **concrete LangGraph + MCP event contract** for flow 1, including example interrupt payloads and resume payloads.
<span style="display:none">[^3_10][^3_11][^3_12][^3_13][^3_14][^3_15][^3_16][^3_17][^3_3][^3_4][^3_5][^3_6][^3_7][^3_8][^3_9]</span>

<div align="center">⁂</div>

[^3_1]: https://blog.langchain.com/langgraph-multi-agent-workflows/

[^3_2]: https://langchain-ai.github.io/langgraph/concepts/multi_agent/

[^3_3]: https://docs.langchain.com/oss/python/langgraph/interrupts

[^3_4]: https://docs.langchain.com/oss/javascript/langgraph/use-subgraphs

[^3_5]: https://github.com/langchain-ai/langgraph/issues/1222

[^3_6]: https://github.com/langchain-ai/langgraph/issues/4796

[^3_7]: https://dev.to/jamesbmour/interrupts-and-commands-in-langgraph-building-human-in-the-loop-workflows-4ngl

[^3_8]: https://docs.langchain.com/oss/python/langgraph/use-subgraphs

[^3_9]: https://dev.to/copilotkit/how-to-build-a-langgraph-research-agent-that-embeds-dynamic-charts-via-mcp-apps-copilotkit-tako-3ihi

[^3_10]: https://langchain-ai.github.io/langgraphjs/how-tos/subgraphs-manage-state/

[^3_11]: https://www.youtube.com/watch?v=PYH7Mn4pXUc

[^3_12]: https://www.langchain.com/langgraph

[^3_13]: https://www.permit.io/blog/delegating-ai-permissions-to-human-users-with-permitios-access-request-mcp

[^3_14]: https://github.com/KirtiJha/langgraph-interrupt-workflow-template

[^3_15]: https://docs.langchain.com/langsmith/generative-ui-react

[^3_16]: https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/wait-user-input/

[^3_17]: https://github.com/langchain-ai/langgraph/issues/4879


---

# i mean, the mcp app is invoked from one of the nodes on the subgraph

Yes — that is a valid design. If an **MCP app/tool is invoked from a node inside a subgraph**, then from LangGraph’s point of view it is just a node performing an action inside the same graph execution, and the result still flows back through the same parent run and thread context. [^4_1][^4_2]

## Short answer

So the answer is:

- **Yes, a subgraph node can invoke an MCP app/tool.** [^4_1]
- **But the user conversation boundary is still the overall LangGraph run**, not a separate standalone “subgraph session.” [^4_1][^4_2]

That means the subgraph can absolutely own the interactive search/form step, but operationally it is still part of the same thread and orchestration tree. [^4_1][^4_2]

## Two cases

There are really two different meanings of “invoke MCP app,” and the architecture changes slightly:


| Case | What happens | Recommended |
| :-- | :-- | :-- |
| MCP tool call returns data immediately | Node calls MCP server/tool and continues execution | Good for backend search/lookups. [^4_1] |
| MCP app needs user interaction before continuing | Node should pause and wait for user input | Use `interrupt()` plus resume on same thread. [^4_1] |

If your MCP app is **interactive**—for example, product search, selection, and form filling—then the clean pattern is not “tool call blocks until user finishes UI.” The cleaner LangGraph-native approach is: the node emits an interrupt payload that tells the client which MCP app/view to render, then the graph resumes when the user completes the interaction. [^4_1]

## What I would avoid

I would avoid treating the MCP app as if it were an autonomous side-channel conversation that the subgraph fully hands off to and forgets. LangGraph’s interaction model is built around **pause/resume with persisted state**, so if the UI requires human steps, model that explicitly with interrupts rather than trying to hide it inside a long-running node. [^4_1]

Why:

- checkpointer state stays clean,
- retries are safer,
- mid-flow intent switching is easier,
- and resume semantics stay predictable. [^4_1][^4_2]


## Best pattern for your flow

For your flow 1, the best design is:

1. `search_step` node in subgraph decides user needs search UI. [^4_1]
2. It raises an interrupt with payload like `{"ui":"data_product_search", "filters": ..., "draft": ...}`. [^4_1]
3. Your chat/MCP client renders the MCP app. [^4_1]
4. User interacts in the app. [^4_1]
5. Client resumes graph with `Command(resume=...)` containing selected product or form data. [^4_1]
6. Subgraph continues to next node. [^4_1]

That gives you a true interactive experience while preserving LangGraph’s thread/checkpoint behavior. [^4_1]

## If you still want direct MCP call from node

If the node calls an MCP server directly and that server itself returns a UI artifact or app descriptor, that is still fine. The key question is whether the node can **complete synchronously**. If yes, normal node/tool execution is enough; if not, use interrupt/resume. LangGraph’s docs are clear that interrupts are the built-in mechanism when external input is required before proceeding. [^4_1]

## Recommendation

So for your exact scenario: **yes, let the subgraph node trigger the MCP app, but if the app requires user interaction, represent that boundary as a LangGraph interrupt/resume point rather than as a hidden blocking tool call.** [^4_1]

A good rule of thumb is:

- **machine-only MCP call** → regular node/tool call. [^4_1]
- **human-in-the-loop MCP app** → interrupt from subgraph node, then resume. [^4_1]

If you want, I can draw the exact node-level design for:

- `search_product`
- `select_product`
- `fill_form`
- `submit_request`

using **subgraph + interrupt + MCP app payload contracts** in LangGraph Python.
<span style="display:none">[^4_10][^4_11][^4_12][^4_13][^4_14][^4_15][^4_16][^4_3][^4_4][^4_5][^4_6][^4_7][^4_8][^4_9]</span>

<div align="center">⁂</div>

[^4_1]: https://docs.langchain.com/oss/python/langgraph/interrupts

[^4_2]: https://docs.langchain.com/oss/python/langgraph/use-subgraphs

[^4_3]: https://docs.langchain.com/oss/javascript/langgraph/interrupts

[^4_4]: https://dev.to/aiengineering/a-beginners-guide-to-using-mcp-with-langgraph-2fg5

[^4_5]: https://github.com/langchain-ai/langchain-mcp-adapters/issues/149

[^4_6]: https://github.com/langchain-ai/langgraph/issues/1222

[^4_7]: https://www.reddit.com/r/LangChain/comments/1nyv6lo/interrupt_in_subgraph/

[^4_8]: https://docs.langchain.com/langsmith/generative-ui-react

[^4_9]: https://tessl.io/registry/tessl/pypi-langgraph/1.0.2/files/docs/advanced/interrupts.md

[^4_10]: https://github.com/KirtiJha/langgraph-interrupt-workflow-template

[^4_11]: https://docs.copilotkit.ai/reference/v1/hooks/useLangGraphInterrupt

[^4_12]: https://www.nkthanh.dev/en/posts/human-in-loop-with-langchain

[^4_13]: https://www.reddit.com/r/LangChain/comments/1moi94j/langgraph_how_do_i_read_subgraph_state_without_an/

[^4_14]: https://github.com/langchain-ai/langgraphjs-gen-ui-examples

[^4_15]: https://www.youtube.com/watch?v=ar-8n66EMSw

[^4_16]: https://github.com/langchain-ai/langgraph-studio/issues/232


---

# what if in the middle of the interaction the user asks a question or intent switch

Then you should treat that moment as a **suspendable workflow boundary**. If the user asks a question or changes intent in the middle of the MCP interaction, the current subgraph step should remain paused, the supervisor should handle the new intent, and then either resume or abandon the paused flow explicitly. LangGraph’s interrupt/resume model and handoff pattern are designed for exactly this. [^5_1][^5_2][^5_3]

## Core rule

Do **not** let the MCP interaction own the whole conversation state by itself. Instead:

- the subgraph node initiates the MCP interaction,
- the graph enters a paused state,
- new user input is reclassified by the parent/supervisor,
- and the system decides whether to **resume**, **branch temporarily**, or **cancel** the paused subgraph step. [^5_1][^5_2]

That is the clean way to support mid-flow questions and intent switches without corrupting state. [^5_1]

## What should happen

When the search/form MCP app is open, the system should still preserve:

- `active_flow`
- `paused_at_step`
- `pending_ui_action`
- `draft_form`
- `selected_product`
- `resume_token` or equivalent resume metadata. [^5_1]

So if the user types, “What does steward approval mean?” while the form step is active, the app should **not** blindly feed that into the form. It should go back through the top-level intent layer, which can classify it as FAQ, answer it, and then offer to continue the paused form step. [^5_1][^5_2]

## Decision policy

Use a simple policy table like this:


| User action during MCP step | System behavior |
| :-- | :-- |
| Clarifying question about current step | Answer, then auto-resume paused step. [^5_1][^5_2] |
| General FAQ about process | Temporary handoff to FAQ, preserve paused step. [^5_1][^5_2] |
| “Check my request status” | Intent switch to status flow, keep paused draft resumable. [^5_1][^5_2] |
| “Cancel this” | Mark paused flow canceled and close MCP interaction. [^5_1] |
| Form/search submission payload | Resume paused subgraph node with structured result. [^5_1] |

## Best architectural model

The cleanest mental model is that an MCP interaction is **not a separate conversation**, but a **UI state attached to a paused graph state**. LangGraph interrupts pause execution and allow resumption on the same thread with `Command(resume=...)`, and handoffs let control move to another node when intent changes. [^5_1][^5_2]

So your parent graph should be the authority for:

- current conversational intent,
- which flow is paused,
- whether to resume or reroute. [^5_1][^5_2]

The subgraph should be the authority for:

- the request-access workflow,
- validation,
- step progression,
- and mapping resume payloads back into workflow state. [^5_1][^5_3]


## Important implication

This means your MCP app should return **structured events**, not just raw text. For example:

- `SEARCH_SELECTED`
- `FORM_UPDATED`
- `FORM_SUBMITTED`
- `USER_ASKED_QUESTION`
- `USER_SWITCHED_INTENT`
- `USER_CANCELED` [^5_1]

Then the parent graph can interpret those events safely. If the event is conversational rather than transactional, route it through the supervisor instead of resuming the subgraph directly. [^5_1][^5_2]

## Recommended handling

I would implement it like this:

1. Subgraph node triggers MCP UI and pauses. [^5_1]
2. User action comes back as a structured client event. [^5_1]
3. Client or gateway decides whether it is:
    - resume payload for the paused node,
    - a side question,
    - or a true intent switch. [^5_1][^5_2]
4. If resume payload, invoke graph with `Command(resume=...)`. [^5_1]
5. If side question or switch, route through supervisor while preserving paused state. [^5_1][^5_2]
6. After handling, ask whether to continue paused flow if needed. [^5_1]

## Practical answer

So if the user changes course in the middle of the MCP app interaction, **don’t force the subgraph to keep owning the turn**. Pause the subgraph, let the supervisor process the new turn, and then either resume that exact subgraph step or close it. That is the most robust LangGraph pattern for your use case. [^5_1][^5_2][^5_3]

If you want, I can next give you a **concrete event schema and LangGraph control-flow design** for:

- pause during search,
- pause during form fill,
- FAQ interruption,
- status-switch interruption,
- resume/cancel behavior.
<span style="display:none">[^5_10][^5_11][^5_12][^5_13][^5_14][^5_15][^5_4][^5_5][^5_6][^5_7][^5_8][^5_9]</span>

<div align="center">⁂</div>

[^5_1]: https://docs.langchain.com/oss/python/langgraph/interrupts

[^5_2]: https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs

[^5_3]: https://github.com/langchain-ai/langgraph/issues/1222

[^5_4]: https://docs.langchain.com/oss/javascript/langgraph/interrupts

[^5_5]: https://stackoverflow.com/questions/79582204/how-to-resume-a-langgraph-stream-after-a-custom-human-assistance-tool-interrupt

[^5_6]: https://www.youtube.com/watch?v=PYH7Mn4pXUc

[^5_7]: https://www.youtube.com/watch?v=NrUVOH8zssk

[^5_8]: https://skill4agent.com/en/skill/langchain-ai-langchain-skills/langgraph-human-in-the-loop

[^5_9]: https://www.youtube.com/watch?v=QL-SGSzDsQ8

[^5_10]: https://docs.langchain.com/oss/python/langchain/human-in-the-loop

[^5_11]: https://forum.langchain.com/t/how-to-use-a-subgraph-as-a-tool/2175

[^5_12]: https://www.youtube.com/watch?v=6t7YJcEFUIY

[^5_13]: https://www.youtube.com/watch?v=ndPrCjRCSGo

[^5_14]: https://github.com/KirtiJha/langgraph-interrupt-workflow-template

[^5_15]: https://www.youtube.com/watch?v=Ib4PQOrCh0g


---

# what about memory management for this pattern

For this pattern, treat memory as **three separate layers**: **workflow state**, **thread memory**, and **cross-thread long-term memory**. In LangGraph, short-term memory lives in graph state and is persisted by the **checkpointer per `thread_id`**, while long-term memory should go into a **store** that works across threads. [^6_1][^6_2][^6_3]

## Use three buckets

Do **not** put everything into `messages`. For your app, you want a clean separation like this:


| Memory type | Where it lives | What goes there |
| :-- | :-- | :-- |
| Workflow memory | Graph state + checkpointer | current flow, paused step, selected product, form draft, pending UI state. [^6_1][^6_2] |
| Conversation memory | Graph state + checkpointer | user turns, assistant turns, recent FAQ context, current thread history. [^6_1][^6_4] |
| Long-term memory | LangGraph store | stable user facts or reusable preferences across sessions, such as preferred business unit or common justification defaults if appropriate. [^6_2][^6_5] |

That separation is the main architecture rule for your case. [^6_1][^6_2]

## What should be in state

For your request-access subgraph, keep **operational state** in the checkpointed graph state, for example:

- `active_flow`
- `paused_flow`
- `paused_step`
- `selected_product`
- `search_results`
- `form_draft`
- `submission_preview`
- `pending_interrupt`
- `last_user_intent` [^6_1][^6_2]

This is short-term memory, and LangGraph explicitly describes short-term memory as thread-scoped state persisted via checkpoints so the thread can be resumed later. [^6_1][^6_4]

## What should stay out of messages

Do not overload the `messages` array with UI or workflow internals like:

- full form payloads,
- search result lists,
- product catalogs,
- app event envelopes,
- large backend lookup responses. [^6_1][^6_2]

Those belong in structured state fields, not in chat history. Otherwise the conversation gets noisy, token costs rise, and routing becomes harder. LangGraph’s memory docs describe state as including more than message history, such as retrieved docs or generated artifacts, which supports keeping structured non-message context in state. [^6_1][^6_4]

## Messages strategy

Keep `messages` mostly for:

- user natural-language turns,
- assistant natural-language responses,
- minimal summaries of workflow actions when useful. [^6_1]

For example, instead of storing the whole submitted form in chat history, store one compact assistant event summary like “User selected Product X and started access form,” while the real draft stays in structured state. That keeps the model grounded without bloating the prompt. [^6_1][^6_2]

## Long-term memory

Use the **store** only for facts worth remembering across sessions, because LangGraph distinguishes the store from the checkpointer: the checkpointer persists state within a thread, while the store is for arbitrary information accessed **across** threads. [^6_2][^6_3]

Good long-term memory candidates for your app:

- user department or business unit, if stable,
- preferred approver or common access purpose template,
- accessibility or UX preferences,
- repeated product interests. [^6_2][^6_5]

Bad candidates:

- current draft form,
- current paused step,
- latest search result page,
- temporary status check results. [^6_2][^6_1]


## Best design pattern

I’d recommend this split:

### Thread-scoped state

Use the checkpointer for:

- active workflow,
- interrupt/resume data,
- draft progress,
- current conversational context. [^6_1][^6_2]


### Cross-thread store

Use the store for:

- stable profile facts,
- learned preferences,
- reusable defaults,
- maybe successful past request metadata if business rules allow it. [^6_2][^6_5]

This is exactly how LangGraph positions the two persistence mechanisms: thread checkpoints for session state, store for cross-thread persistence. [^6_2][^6_3]

## For intent switching

Memory management is especially important when the user switches intent mid-flow. The paused flow should remain in **thread state** as resumable operational context, while the new intent runs in the same thread and can read that paused context. Because short-term memory is thread-scoped, the graph can resume the request-access flow later without losing draft state. [^6_1][^6_4]

A useful pattern is:

- `active_flow = "status_check"`
- `suspended_flow = {"name":"request_access","step":"fill_form","draft_id":"..."}`
- `resume_available = true` [^6_1][^6_2]


## Summarization policy

Because chat history can grow, summarize older conversational turns but keep workflow state exact. LangGraph memory guidance treats state as the place for current thread context, so it is reasonable to compress old messages while retaining precise structured fields for the workflow. [^6_1][^6_4]

In practice:

- **summarize old FAQs/chat**
- **never summarize away exact form draft fields unless they are copied into durable structured state**
- **keep the latest interrupt payload and resume contract explicit** [^6_1][^6_2]


## Recommended schema

A practical state shape would be:

- `messages`
- `active_intent`
- `active_flow`
- `flow_state`
- `paused_flows`
- `ui_state`
- `last_status_result`
- `user_profile_snapshot`
- `memory_summary` [^6_1][^6_2]

And your long-term store namespace can be something like:

- `(user_id, "profile")`
- `(user_id, "preferences")`
- `(user_id, "data_access_defaults")` [^6_2][^6_5]


## Concrete recommendation

For your architecture:

- Use **checkpointer** for everything needed to resume the exact in-flight workflow. [^6_1][^6_2]
- Use **store** for durable user-specific facts that should survive new `thread_id`s. [^6_2][^6_3]
- Keep **UI/app events and form drafts in structured state**, not in message history. [^6_1][^6_4]
- Keep **messages lean** and summarize aggressively once turns get old. [^6_1]


## Practical rule of thumb

If losing it would break **resume**, store it in **checkpointed state**. [^6_1][^6_2]
If you want it available in a **future conversation**, store it in the **long-term store**. [^6_2][^6_5]
If it only helps the model speak naturally, keep a compact version in **messages**. [^6_1]

If you want, I can give you a **Pydantic/LangGraph state schema** for this exact app, including `messages`, `flow_state`, `ui_interrupt`, `paused_flows`, and long-term memory namespaces.
<span style="display:none">[^6_10][^6_11][^6_12][^6_13][^6_14][^6_15][^6_6][^6_7][^6_8][^6_9]</span>

<div align="center">⁂</div>

[^6_1]: https://docs.langchain.com/oss/python/langgraph/memory

[^6_2]: https://docs.langchain.com/oss/python/langgraph/persistence

[^6_3]: https://www.mintlify.com/langchain-ai/langgraph/guides/memory

[^6_4]: https://langchain-ai.github.io/langgraph/concepts/memory/

[^6_5]: https://docs.langchain.com/oss/python/langchain/long-term-memory

[^6_6]: https://dev.to/sreeni5018/five-agent-memory-types-in-langgraph-a-deep-code-walkthrough-part-2-17kb

[^6_7]: https://www.linkedin.com/pulse/langgraph-persistence-state-management-production-ready-yash-sarode-4ovcc

[^6_8]: https://www.youtube.com/watch?v=fsENEq4F55Q

[^6_9]: https://docs.langchain.com/oss/python/langgraph/add-memory

[^6_10]: https://dev.to/mongodb/langgraph-with-mongodb-building-conversational-long-term-memory-for-intelligent-ai-agents-2pcn

[^6_11]: https://langchain-ai.github.io/langgraphjs/concepts/memory/

[^6_12]: https://pub.towardsai.net/persistence-in-langgraph-deep-practical-guide-36dc4c452c3b

[^6_13]: https://docs.langchain.com/oss/javascript/langgraph/memory

[^6_14]: https://www.mongodb.com/company/blog/product-release-announcements/powering-long-term-memory-for-agents-langgraph

[^6_15]: https://pub.towardsai.net/understanding-memory-management-in-langgraph-a-practical-guide-for-genai-students-b3642c9ea7e1

