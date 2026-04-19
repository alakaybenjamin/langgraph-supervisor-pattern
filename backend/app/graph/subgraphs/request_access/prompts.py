from __future__ import annotations

"""Request-access subgraph prompts.

Centralised user-facing text for the request-access subgraph — HITL step
messages, cart / confirmation messages, submission success, and the
form-title template used when building the dynamic access form schema.

Rule: this module is **data only** (plain strings and simple
``.format``-style templates). Structured UI option lists (domain chips,
anonymization chips, cart action buttons) remain in :mod:`helpers`
because they are typed UI contracts with the frontend, not prose.
"""

# ---------------------------------------------------------------------------
# HITL step messages
# ---------------------------------------------------------------------------

CHOOSE_DOMAIN_MESSAGE = "Choose the **data domain** for your access request."

CHOOSE_ANONYMIZATION_MESSAGE = (
    "Choose the **anonymization / data handling** level you need."
)

CHOOSE_PRODUCTS_MESSAGE = "Select one or more **data products** to include."

SHOW_CART_MESSAGE = (
    "Review your **selected products** before generating access forms."
)

SHOW_CART_READONLY_MESSAGE = (
    "**Your current selection** (read-only). Continue the workflow when "
    "ready."
)


# ---------------------------------------------------------------------------
# Side-remark hint (shown when the user types chit-chat while a step is
# waiting for their selection)
# ---------------------------------------------------------------------------

SIDE_REMARK_HINT_MESSAGE = (
    "I'm waiting for your selection in the panel above. "
    "You can also ask a **process or policy question** — your "
    "access request stays paused."
)


# ---------------------------------------------------------------------------
# Submit-request confirmation
# ---------------------------------------------------------------------------

SUBMIT_CONFIRMATION_MESSAGE = (
    "Review and confirm your access request submission."
)

SUBMIT_CONFIRMATION_ACTIONS: list[dict[str, str]] = [
    {"id": "submit", "label": "Submit Request"},
    {"id": "edit", "label": "Edit"},
    {"id": "cancel", "label": "Cancel"},
]

SUBMIT_PRODUCTS_EMPTY = "(no products)"

# Format: ``.format(request_id=…)``
SUBMIT_SUCCESS_TEMPLATE = (
    "Your access request **{request_id}** has been submitted successfully. "
    "You'll receive a confirmation email shortly."
)


# ---------------------------------------------------------------------------
# Form schema
# ---------------------------------------------------------------------------

# Format: ``.format(product_id=…)`` — used when building the per-product
# access-form section title.
FORM_SECTION_TITLE_TEMPLATE = "Access request — {product_id}"


# ---------------------------------------------------------------------------
# Search-intent extraction (LLM tool-calling)
# ---------------------------------------------------------------------------
#
# Used right before the ``search_products`` node to pull a clean free-text
# query **and** an optional study id out of whatever the user typed.
# Output is delivered via a single ``set_search_intent`` tool call with
# fields ``search_text`` and ``study_id``. The LLM is instructed to leave
# ``study_id`` empty unless the text clearly contains one — we never guess.

SEARCH_INTENT_SYSTEM_PROMPT = (
    "You extract search intent for a data-product catalog from the user's "
    "message and the pending search query. Always reply by calling the "
    "``set_search_intent`` tool — never plain text.\n\n"
    "Fields:\n"
    "- ``search_text``: concise free-text query suitable for substring "
    "search over product title/description. Use ``'*'`` when the user "
    "gave no meaningful keywords (e.g. just a study id, or empty).\n"
    "- ``study_id``: the clinical study / trial id **only if it clearly "
    "appears in the text**, e.g. ``dp-501``, ``dp 501``, ``study dp-501``. "
    "Normalize to the form ``dp-<digits>`` (lowercase ``dp`` prefix, dash, "
    "digits) when digits are present; otherwise return the literal "
    "string. Leave empty when no study id is present — do not invent "
    "one.\n\n"
    "Examples:\n"
    "- ``'patient demographics for dp-501'`` -> "
    "``search_text='patient demographics'``, ``study_id='dp-501'``.\n"
    "- ``'study dp-501'`` -> ``search_text='*'``, "
    "``study_id='dp-501'``.\n"
    "- ``'sales performance'`` -> ``search_text='sales performance'``, "
    "``study_id=''``.\n"
    "- ``''`` -> ``search_text='*'``, ``study_id=''``."
)


# ---------------------------------------------------------------------------
# Narrowing subagent (purely conversational — no chips, no buttons)
# ---------------------------------------------------------------------------
#
# Drives the ``narrow_search`` node. The agent has exactly two tools:
#   - ``ask_user(message)`` — emits a chat bubble and pauses the graph for
#     the user's reply.
#   - ``commit_narrow(search_text, domain, anonymization, study_id)`` —
#     finalizes the narrowing and hands off to ``search_products``.
#
# Template params:
#   - {domains}        — comma-separated canonical domain ids from the
#                        prefetched MCP facet cache.
#   - {anonymizations} — comma-separated canonical anonymization level ids.
#   - {known_facets}   — short human-readable summary of fields the user
#                        (or supervisor) already provided, so the agent
#                        doesn't ask for them again.

NARROW_AGENT_SYSTEM_TEMPLATE = (
    "You are a friendly assistant helping a user narrow down a "
    "data-product search before it runs. Collect, where the user "
    "actually mentions them, any of:\n"
    "  - domain          (canonical ids: {domains})\n"
    "  - anonymization   (canonical ids: {anonymizations})\n"
    "  - study_id        (canonical format: dp-NNN — lowercase ``dp-`` "
    "prefix followed by digits, e.g. dp-501)\n"
    "  - search keywords (free text describing the topic / dataset — "
    "must describe WHAT KIND of data, NOT the user's intent to start)\n\n"
    "What you already know from earlier in the conversation:\n"
    "{known_facets}\n\n"
    "You have exactly two tools and MUST always reply by calling one of "
    "them — never plain text.\n\n"
    "  - ``ask_user(message)`` — sends a short, natural chat message to "
    "the user and waits for their typed reply. Use this to ask for ONE "
    "missing piece of info, or to confirm an ambiguous value, at a time.\n"
    "  - ``commit_narrow(search_text, domain, anonymization, study_id)`` "
    "— finalizes the narrowing and runs the search. Pass the empty "
    "string for any field the user did not state.\n\n"
    "Conversational rules — follow strictly:\n"
    "  1. Keep messages short and friendly. Acknowledge what you "
    "already know so the user does not repeat themselves.\n"
    "  2. **First-turn bias toward asking.** On the very first turn, "
    "if you have NO usable filters (no domain, no anonymization, no "
    "study_id, AND no real search topic) you MUST call ``ask_user`` to "
    "ask what kind of data they're looking for. DO NOT commit with "
    "everything empty — that dumps the user into a generic browse with "
    "zero context.\n"
    "  3. **Generic intent phrases are NOT search topics.** Phrases "
    "like \"request access\", \"i need data\", \"data products\", "
    "\"datasets\", \"some data\", \"help me find data\", \"start\", "
    "\"new request\", \"give me access\" are intent signals or vague "
    "category words, NOT keywords describing a dataset. When the user "
    "answers with one of these, treat the topic as still missing and "
    "ask them to be more specific. A real topic looks like \"oncology "
    "trial data\", \"sales by region\", \"ECG signals from cardiac "
    "studies\".\n"
    "  4. **Batch the optional facets in ONE follow-up question.** "
    "Once you have a real topic (or a study_id), do NOT ask one facet "
    "per turn — that wastes the user's time and burns through your "
    "turn budget. Instead, ask about ALL of the remaining unknown "
    "optional facets (domain, anonymization, study_id) in a single "
    "``ask_user`` message. List the canonical options inline so the "
    "user can answer with one short reply, e.g.:\n"
    "      \"Got it — clinical data. Two quick optional filters: do "
    "you want a specific domain ({domains}), or an anonymization level "
    "({anonymizations})? Mention any that apply, give a study ID like "
    "dp-501, or just say 'any' to search now.\"\n"
    "  5. If the user's reply contains a number or token that looks "
    "like an ID but does NOT match the ``dp-NNN`` format (lowercase "
    "``dp-`` prefix + digits), ASK them to confirm before treating it "
    "as a study_id. Example: user says \"12455\" → ask \"Just to "
    "confirm — should I treat 12455 as a study ID? Our study IDs "
    "usually look like dp-NNN (e.g. dp-501).\"\n"
    "  6. If the user paraphrases a domain or anonymization level, map "
    "it silently to the canonical id. If the paraphrase is ambiguous "
    "(could mean two canonical values), ask which one.\n"
    "  7. If the user EXPLICITLY signals they want to proceed without "
    "narrowing further (e.g. \"go ahead\", \"just search\", \"skip\", "
    "\"any\", \"I don't know\", \"no preference\", \"show me "
    "everything\"), call commit_narrow IMMEDIATELY with whatever you "
    "have. Empty fields mean \"no filter for this dimension\". Note: "
    "this rule only applies AFTER you've asked at least one question "
    "— don't pre-empt it on turn one.\n"
    "  8. Never invent a value the user did not state.\n"
    "  9. Use canonical ids for domain and anonymization. If the user "
    "provided a value that is NOT in the canonical lists above, leave "
    "the field empty in commit_narrow.\n"
    "  10. Hard cap: at most 4 ask_user calls. Aim for 1-2 in normal "
    "use by batching per rule 4. After the fourth reply, you MUST call "
    "commit_narrow on the next turn."
)


