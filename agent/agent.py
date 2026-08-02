"""Schema Intelligence Agent -- wires the Day 1 detector, Day 2C generator,
and Day 2B RAG retrieval into a conversational interface.

Architecture (see conversation log distilled into README.md's design
decisions once written): a hybrid, not a pure LLM-driven tool-calling loop
and not a pure deterministic router either.

  1. The incoming message is parsed deterministically first -- an embedded
     schema JSON payload, or a "column X in table Y" pattern, if present.
  2. The LLM (native Ollama tool-calling, not LangGraph/LangChain -- see
     README) is asked which of the three tools applies. Its answer is used
     ONLY as a selection signal -- tool_calls[0]['function']['arguments']
     is never read anywhere in this file. Verified directly (see
     conversation log) that this model reliably picks the right tool, but
     unreliably fabricates plausible-looking arguments (a full invented
     schema) when the real data isn't in front of it -- so we never let it
     construct anything structured. All tool arguments come from step 1's
     deterministic parse, or from session state.
  3. If no tool was selected at all, that's the out-of-scope case --
     refuse, no further LLM call, so nothing gets generated at all for a
     genuinely irrelevant question.
  4. Documentation questions always call search_masking_docs before any
     answer text is generated -- a code-level fact (search_masking_docs is
     called on this line, unconditionally, or the DOC_QUESTION branch
     isn't reached at all), not a prompted hope. The citation is appended
     by code from the actual retrieved chunk's source_file, not trusted to
     the model's own output.
"""
import json
import os
import re
import sys
from pathlib import Path

import ollama

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools import detect_pii_columns, generate_masking_config, search_masking_docs  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "masking-generator"))
from generator import MASKING_FUNCTION_MAP  # noqa: E402

# qwen2.5:7b, not 14b, on the evidence of tests/ab_baseline_results.md.
# The larger model was the initial choice on the assumption that it would
# route and generate better; the A/B baseline showed the opposite. 14b
# consistently (3/3) routes "How do I configure and run a masking job?" to
# detect_pii_columns rather than search_masking_docs -- reading "masking
# job" as a data operation -- which breaks the grounding rule for that
# whole class of documentation question. 7b routes it correctly, scores
# higher overall (3.93 vs 3.40), and runs ~5x faster.
AGENT_MODEL = os.environ.get("AGENT_MODEL", "qwen2.5:7b")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "detect_pii_columns",
            "description": (
                "Analyze a database schema, or ask whether a specific column contains PII. "
                "Use this for any request to analyze a schema for PII, or to check whether "
                "a named column in a named table is PII."
            ),
            "parameters": {
                "type": "object",
                "properties": {"schema": {"type": "array", "description": "List of column descriptors"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_masking_config",
            "description": (
                "Generate a masking job configuration from PII detection results that were "
                "already produced earlier in the conversation. Use this when the user asks to "
                "generate, create, or produce a masking configuration for existing results."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_masking_docs",
            "description": (
                "Search the data masking documentation -- masking functions (e.g. EMAIL_MASK, "
                "DATE_SHIFT, CREDIT_CARD_MASK), how to configure a masking job, or GDPR/CCPA "
                "compliance. Use this for any question about how masking works, what a masking "
                "function does or accepts, or compliance requirements."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

OUT_OF_SCOPE_MESSAGE = (
    "That's out of scope for what I can help with -- I'm focused on PII detection, "
    "data masking configuration, and masking documentation questions. Ask me about a "
    "schema, a specific column, a masking function, or a compliance question instead."
)

MISSING_SCHEMA_MESSAGE = (
    "I don't have a schema to analyze yet -- please provide the column descriptors "
    "(table name, column name, data type, and sample values) you'd like me to check."
)

NO_PRIOR_DETECTIONS_MESSAGE = (
    "I don't have any PII detection results yet -- please analyze a schema first."
)

_TABLE_COLUMN_RE = re.compile(
    r"column\s+['\"`]?(\w+)['\"`]?\s+in\s+table\s+['\"`]?(\w+)['\"`]?", re.IGNORECASE
)

# Deliberately deterministic, not LLM-decided -- see chat()'s docstring
# note on why. Whether a generate-config request is valid also depends on
# self.last_detections, something the tool-selection LLM call is never
# shown (it only ever sees the current message, no conversation history),
# so it structurally cannot make this call correctly on its own.
_GENERATE_CONFIG_RE = re.compile(r"\b(generate|create|produce)\b.*\bmasking\s+config", re.IGNORECASE)

# Secondary check, only consulted when the tool-selection call returned NO
# tool at all. "Mask this column" (JD interaction 7) is in scope but has no
# data to act on -- the model declines to pick a tool for it, which is
# indistinguishable at that point from a genuinely out-of-scope question.
# Requires both an action verb and a data noun, so it stays narrow: the
# worst case if it misfires is answering "I need a schema" to something
# irrelevant, never fabricating a detection result.
_DATA_ACTION_RE = re.compile(
    r"\b(mask|masking|analy[sz]e|detect|scan|check|classify|identify)\b", re.IGNORECASE
)
_DATA_NOUN_RE = re.compile(r"\b(column|columns|schema|table|tables|field|fields)\b", re.IGNORECASE)

_GROUNDED_ANSWER_SYSTEM_PROMPT = """You are a documentation assistant for a data masking
platform. Answer the user's question using ONLY the documentation excerpts provided below.
Do not use outside knowledge. If the excerpts don't actually answer the question, say so
honestly instead of guessing. Keep the answer concise -- a few sentences, not an essay."""


def _extract_json_payload(message: str):
    """Scans for the first valid JSON value ([ or { start) anywhere in the
    message, tolerating surrounding natural-language text.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(message):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(message, i)
                return obj
            except json.JSONDecodeError:
                continue
    return None


def _extract_schema(message: str):
    payload = _extract_json_payload(message)
    if isinstance(payload, list) and payload and all(
        isinstance(c, dict) and "table_name" in c and "column_name" in c for c in payload
    ):
        return payload
    return None


def _extract_table_column(message: str):
    m = _TABLE_COLUMN_RE.search(message)
    if not m:
        return None, None
    return m.group(2), m.group(1)  # (table, column)


def _infer_category_filter(message: str):
    upper = message.upper()
    for category, function in MASKING_FUNCTION_MAP.items():
        if function in upper or category in upper:
            return category
    return None


class SchemaIntelligenceAgent:
    def __init__(self, model: str = AGENT_MODEL, client=None):
        self.model = model
        self.client = client or ollama
        self.last_detections = None  # set after a successful schema analysis

    def _select_tool(self, message: str) -> str | None:
        response = self.client.chat(
            model=self.model,
            # temperature=0 for the same reason detector.py uses it: tool
            # selection is a routing decision, not creative generation, and
            # it must not vary run to run. Found the hard way -- without
            # this, the GDPR question selected search_masking_docs on some
            # runs and no tool at all on others, making the grounding rule
            # intermittent rather than guaranteed.
            options={"temperature": 0},
            messages=[{"role": "user", "content": message}],
            tools=TOOLS,
        )
        tool_calls = response["message"].get("tool_calls")
        if not tool_calls:
            return None
        return tool_calls[0]["function"]["name"]

    def _format_detections(self, detections: list) -> str:
        lines = [
            f"- {d.table}.{d.column}: {'PII' if d.is_pii else 'not PII'}"
            f"{' (' + d.pii_category + ')' if d.pii_category else ''}, "
            f"confidence {d.confidence:.2f}"
            f"{', review required' if d.review_required else ''}"
            for d in detections
        ]
        return "Analyzed " + str(len(detections)) + " column(s):\n" + "\n".join(lines)

    def _format_single(self, result, table: str, column: str) -> str:
        verdict = "is PII" if result.is_pii else "is not PII"
        category = f" ({result.pii_category})" if result.pii_category else ""
        return (
            f"{table}.{column} {verdict}{category}, confidence {result.confidence:.2f}. "
            f"{result.reasoning}"
        )

    def _format_config(self, config: dict) -> str:
        return "Generated masking configuration:\n" + json.dumps(config, indent=2)

    def _generate_grounded_answer(self, message: str, chunks: list) -> str:
        excerpts = "\n\n".join(f"[{c['source_file']}]\n{c['text']}" for c in chunks)
        response = self.client.chat(
            model=self.model,
            options={"temperature": 0},
            messages=[
                {"role": "system", "content": _GROUNDED_ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Documentation excerpts:\n\n{excerpts}\n\nQuestion: {message}"},
            ],
        )
        answer = response["message"]["content"].strip()
        # Citation is appended by code from the actual retrieved sources,
        # not trusted to the model's own output -- see module docstring.
        # Every retrieved document is cited, not just the top-ranked one:
        # the model was shown all of them as context, so any of them could
        # have grounded the answer, and citing only rank 1 was observed to
        # attribute a GDPR answer to data_masking_overview.md when
        # gdpr_ccpa_compliance.md (rank 2) was the real source. Citing what
        # was actually retrieved is truthful; guessing which one the model
        # leaned on is not something we can know.
        sources = list(dict.fromkeys(c["source_file"] for c in chunks))
        label = "Source" if len(sources) == 1 else "Sources"
        return f"{answer}\n\n({label}: {', '.join(sources)})"

    def chat(self, message: str) -> str:
        # Deterministic signals first, unconditionally, before any LLM call
        # -- each of these is 100% decidable from the message (and session
        # state) alone, so there's nothing for a model's judgment to add,
        # only latency/cost and (per the generate-config bug found while
        # testing) a real risk of the model failing on context it was
        # never shown in the first place.
        schema = _extract_schema(message)
        if schema is not None:
            detections = detect_pii_columns(schema)
            self.last_detections = detections
            return self._format_detections(detections)

        table, column = _extract_table_column(message)
        if table and column:
            single = detect_pii_columns([{"table_name": table, "column_name": column}])
            self.last_detections = single
            return self._format_single(single[0], table, column)

        if _GENERATE_CONFIG_RE.search(message):
            if not self.last_detections:
                return NO_PRIOR_DETECTIONS_MESSAGE
            config = generate_masking_config(self.last_detections)
            return self._format_config(config)

        # Everything left is genuinely ambiguous from structure alone --
        # doc question, a vague PII-ish request with no real data, or
        # out-of-scope. This is where an LLM call earns its cost.
        tool_name = self._select_tool(message)

        if tool_name is None:
            # No tool selected. Either genuinely out of scope, or an
            # in-scope request with nothing to act on -- and we already
            # know from the parses above that there's no schema and no
            # table/column here, so if it reads as a data request at all,
            # the honest answer is to ask for the data rather than refuse.
            if _DATA_ACTION_RE.search(message) and _DATA_NOUN_RE.search(message):
                return MISSING_SCHEMA_MESSAGE
            return OUT_OF_SCOPE_MESSAGE

        if tool_name == "detect_pii_columns":
            # The model thought this was PII-related, but our deterministic
            # parse found no real schema or table/column data to act on.
            return MISSING_SCHEMA_MESSAGE

        if tool_name == "generate_masking_config":
            # Same story as above -- got here without matching the
            # deterministic phrase check, so there's nothing real to act on.
            return NO_PRIOR_DETECTIONS_MESSAGE

        if tool_name == "search_masking_docs":
            category_filter = _infer_category_filter(message)
            chunks = search_masking_docs(message, category_filter)
            if not chunks:
                return "I couldn't find anything in the documentation about that."
            return self._generate_grounded_answer(message, chunks)

        return OUT_OF_SCOPE_MESSAGE


def _sanitize_terminal_input(text: str) -> str:
    """Strips lone surrogates out of terminal input.

    On a non-UTF-8 locale, Python decodes stdin with the surrogateescape
    handler, so any byte it can't decode arrives as a lone surrogate
    (\\udc80-\\udcff). Pasting text containing a non-breaking space is
    enough to trigger it -- 0xC2 becomes '\\udcc2' -- and the request
    library then fails to encode the message into a JSON body at all.

    Round-tripping through surrogateescape recovers the original bytes,
    then decodes with replacement: a genuine multi-byte character that was
    escaped comes back intact, and a truly undecodable byte becomes U+FFFD
    instead of crashing the REPL.
    """
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def main():
    """Interactive REPL. Requires Ollama running and `python rag/ingest.py`
    to have been run at least once (retrieval reads the persisted index).
    """
    agent = SchemaIntelligenceAgent()
    print(f"Schema Intelligence Assistant  (model: {agent.model})")
    print("Ask about a schema, a column, a masking function, or compliance.")
    print("Ctrl-C or 'exit' to quit.\n")
    while True:
        try:
            message = _sanitize_terminal_input(input("> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            break
        try:
            print(f"\n{agent.chat(message)}\n")
        except Exception as exc:
            # A REPL that dies on one bad turn loses the session state that
            # makes "generate a config for these results" work at all.
            print(f"\n[error handling that message: {exc}]\n")


if __name__ == "__main__":
    main()
