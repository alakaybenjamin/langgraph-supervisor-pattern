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
    "appears in the text**, e.g. ``STU-203121``, ``203121``, ``study "
    "203121``. Normalize to the form ``STU-<digits>`` when digits are "
    "present; otherwise return the literal string. Leave empty when no "
    "study id is present — do not invent one.\n\n"
    "Examples:\n"
    "- ``'patient demographics for STU-203121'`` -> "
    "``search_text='patient demographics'``, ``study_id='STU-203121'``.\n"
    "- ``'study 203121'`` -> ``search_text='*'``, "
    "``study_id='STU-203121'``.\n"
    "- ``'sales performance'`` -> ``search_text='sales performance'``, "
    "``study_id=''``.\n"
    "- ``''`` -> ``search_text='*'``, ``study_id=''``."
)

