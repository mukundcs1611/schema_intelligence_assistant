"""Quality test type 6: A/B baseline (model comparison).

Runs 5 standard queries against two candidate agent models, scores each
response against the rubric below, and writes ab_baseline_results.md.

This is a script rather than a pytest test on purpose: it establishes a
baseline for future model comparisons rather than asserting a pass/fail
condition. A model swap (or a new qwen release) is evaluated by re-running
this and diffing the table, not by watching a test go red.

Run from agent/:  python tests/ab_comparison.py

Rubric -- four criteria, scored mechanically rather than by judgement, so
the same run produces the same score and the baseline stays comparable
across time:

  tool_correct   (0/1)  Did the model route to the expected tool?
                        This is the routing decision the agent depends on;
                        getting it wrong means the right answer is
                        impossible regardless of generation quality.
  grounded       (0/1)  Does the response cite a document that actually
                        exists in rag/corpus/? A citation naming a file we
                        don't ship is a fabricated citation.
  keyword_cover  (0-1)  Fraction of the query's expected concept keywords
                        present in the response. Measures whether the
                        answer contains the substance, without asserting
                        exact phrasing (which would punish rewording).
  no_fabrication (0/1)  Does the response avoid content it should not
                        contain (the answer to an out-of-scope question)?

  total = tool_correct + grounded + keyword_cover + no_fabrication  (max 4.0)

Scoring is deliberately blunt. It cannot detect a subtly wrong-but-fluent
answer, which is the failure mode automated scoring is worst at -- that is
what the human-reviewed eval reports elsewhere in this repo are for. The
value here is a repeatable baseline, not a quality verdict.
"""
import sys
import time
from pathlib import Path

_AGENT_DIR = Path(__file__).resolve().parent.parent
_ROOT = _AGENT_DIR.parent
sys.path.insert(0, str(_AGENT_DIR))

from agent import AGENT_MODEL, SchemaIntelligenceAgent  # noqa: E402

CORPUS_DIR = _ROOT / "rag" / "corpus"
OUTPUT_PATH = Path(__file__).resolve().parent / "ab_baseline_results.md"

CANDIDATE_MODELS = ["qwen2.5:7b", "qwen2.5:14b"]

# Every query runs this many times per model, to measure run-to-run
# consistency rather than assume it. See run_model's docstring.
REPEATS = 3

QUERIES = [
    {
        "query": "What does DATE_SHIFT do?",
        "expected_tool": "search_masking_docs",
        "keywords": ["shift", "offset", "date"],
        "forbidden": None,
    },
    {
        "query": "What parameters does EMAIL_MASK accept?",
        "expected_tool": "search_masking_docs",
        "keywords": ["domain", "mapping", "mask"],
        "forbidden": None,
    },
    {
        "query": "How do I comply with GDPR when masking customer data?",
        "expected_tool": "search_masking_docs",
        "keywords": ["gdpr", "personal data", "irreversible"],
        "forbidden": None,
    },
    {
        "query": "How do I configure and run a masking job?",
        "expected_tool": "search_masking_docs",
        "keywords": ["job", "configuration", "source"],
        "forbidden": None,
    },
    {
        "query": "What is the weather in Hyderabad?",
        "expected_tool": None,  # out of scope -- no tool should be selected
        "keywords": ["out of scope", "masking"],
        "forbidden": "temperature",
    },
]


def _corpus_files():
    return {f.name for f in CORPUS_DIR.glob("*.md")}


def cites_real_source(response: str) -> bool:
    if "(Source:" not in response and "(Sources:" not in response:
        return False
    tail = response.rsplit("(", 1)[-1].rstrip(")\n ")
    cited = [c.strip() for c in tail.split(":", 1)[-1].split(",")]
    return bool(cited) and all(c in _corpus_files() for c in cited)


def score_response(case: dict, response: str, selected_tool) -> dict:
    tool_correct = 1 if selected_tool == case["expected_tool"] else 0

    if case["expected_tool"] is None:
        # An out-of-scope refusal has nothing to cite -- scoring it on
        # citations would penalise the correct behaviour.
        grounded = 1
    else:
        grounded = 1 if cites_real_source(response) else 0

    lowered = response.lower()
    hits = sum(1 for kw in case["keywords"] if kw.lower() in lowered)
    keyword_cover = hits / len(case["keywords"])

    forbidden = case["forbidden"]
    no_fabrication = 0 if (forbidden and forbidden.lower() in lowered) else 1

    return {
        "tool_correct": tool_correct,
        "grounded": grounded,
        "keyword_cover": round(keyword_cover, 2),
        "no_fabrication": no_fabrication,
        "total": round(tool_correct + grounded + keyword_cover + no_fabrication, 2),
    }


def run_model(model: str, repeats: int = REPEATS) -> list[dict]:
    """Each query runs `repeats` times. Everything here runs at
    temperature=0 and should therefore be deterministic -- the repeats
    exist to verify that rather than assume it. That assumption already
    failed once: tool selection was non-deterministic until temperature=0
    was set explicitly on the selection call, and a single-run baseline
    would not have caught it.
    """
    agent = SchemaIntelligenceAgent(model=model)
    rows = []
    for case in QUERIES:
        totals, tools, latencies = [], [], []
        first_response = None
        for i in range(repeats):
            started = time.time()
            selected_tool = agent._select_tool(case["query"])
            response = agent.chat(case["query"])
            latencies.append(time.time() - started)
            scores = score_response(case, response, selected_tool)
            totals.append(scores["total"])
            tools.append(selected_tool)
            if i == 0:
                first_response, first_scores = response, scores

        distinct_tools = list(dict.fromkeys(str(t) for t in tools))
        consistent = len(distinct_tools) == 1 and len(set(totals)) == 1
        rows.append({
            "query": case["query"],
            "selected_tool": tools[0],
            "elapsed_s": round(sum(latencies) / len(latencies), 1),
            "response": first_response,
            "runs": repeats,
            "consistent": consistent,
            "distinct_tools": distinct_tools,
            "score_range": (min(totals), max(totals)),
            "mean_total": round(sum(totals) / len(totals), 2),
            **first_scores,
        })
        flag = "" if consistent else "  <-- INCONSISTENT"
        print(f"  [{model}] {case['query'][:45]:<45} mean={rows[-1]['mean_total']}/4.0  "
              f"({rows[-1]['elapsed_s']:.1f}s avg){flag}")
    return rows


def render_report(results: dict[str, list[dict]]) -> str:
    lines = [
        "# A/B Baseline — Agent Model Comparison",
        "",
        "Generated by `agent/tests/ab_comparison.py`. Re-run it and diff this",
        "file to evaluate a model swap or a new model release.",
        "",
        "## Rubric",
        "",
        "| Criterion | Range | Measures |",
        "|---|---|---|",
        "| `tool_correct` | 0/1 | Routed to the expected tool (or correctly selected none, for out-of-scope) |",
        "| `grounded` | 0/1 | Cites a document that actually exists in `rag/corpus/` |",
        "| `keyword_cover` | 0–1 | Fraction of expected concept keywords present |",
        "| `no_fabrication` | 0/1 | Avoids content it should not contain |",
        "",
        "Max total per query: **4.0**. Scoring is mechanical and repeatable; it",
        "cannot detect a subtly wrong-but-fluent answer — see the honest-limits",
        "note at the end.",
        "",
        f"Each query is run **{REPEATS}×** per model. All calls use `temperature=0`",
        "and should therefore be identical across runs — the repeats verify that",
        "rather than assume it (see the consistency note below).",
        "",
        "## Summary",
        "",
        "| Model | Mean total | Tool accuracy | Grounded | Consistent | Mean latency |",
        "|---|---|---|---|---|---|",
    ]

    for model, rows in results.items():
        mean_total = sum(r["mean_total"] for r in rows) / len(rows)
        tool_acc = sum(r["tool_correct"] for r in rows) / len(rows)
        grounded = sum(r["grounded"] for r in rows) / len(rows)
        consistent = sum(1 for r in rows if r["consistent"]) / len(rows)
        mean_latency = sum(r["elapsed_s"] for r in rows) / len(rows)
        lines.append(
            f"| `{model}` | {mean_total:.2f} / 4.0 | {tool_acc:.0%} | {grounded:.0%} | "
            f"{consistent:.0%} | {mean_latency:.1f}s |"
        )

    lines += ["", "## Per-query detail", ""]
    for model, rows in results.items():
        lines += [f"### `{model}`", "",
                  "| Query | Tool selected | tool | grnd | kw | no-fab | mean | consistent |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            tool = r["selected_tool"] or "(none)"
            if r["consistent"]:
                consistency = "yes"
            else:
                lo, hi = r["score_range"]
                consistency = f"**NO** (tools: {', '.join(r['distinct_tools'])}; scores {lo}–{hi})"
            lines.append(
                f"| {r['query']} | `{tool}` | {r['tool_correct']} | {r['grounded']} | "
                f"{r['keyword_cover']} | {r['no_fabrication']} | **{r['mean_total']}** | {consistency} |"
            )
        lines.append("")

    best = max(results, key=lambda m: sum(r["total"] for r in results[m]) / len(results[m]))
    lines += [
        "## Decision",
        "",
        f"The agent's current default is **`{AGENT_MODEL}`** (`agent.py`'s `AGENT_MODEL`,",
        "overridable via the `AGENT_MODEL` environment variable).",
        "",
        f"Highest mean score in this run: **`{best}`**.",
        "",
        "This baseline reversed the original design decision. `qwen2.5:14b` was",
        "chosen first, on the assumption that the larger model would route and",
        "generate better. It does not: it consistently (3/3 on repeat runs)",
        "routes *\"How do I configure and run a masking job?\"* to",
        "`detect_pii_columns` instead of `search_masking_docs`, apparently",
        "reading \"masking job\" as a data operation rather than a documentation",
        "topic. That breaks the grounding rule for that whole class of question —",
        "a documentation question that never retrieves. `qwen2.5:7b` routes it",
        "correctly, scores higher overall, and runs several times faster.",
        "",
        "## Honest limits of this baseline",
        "",
        "- **Five queries is a baseline, not an evaluation.** It is enough to",
        "  catch a model that routes badly or stops citing sources; it is not",
        "  enough to rank two models that both score well.",
        "- **Mechanical scoring cannot see subtle wrongness.** A confidently",
        "  incorrect answer that happens to contain the expected keywords and",
        "  a valid citation scores full marks here. Detecting that needs a",
        "  human, or a judge model whose own accuracy would then need",
        "  establishing.",
        "- **`keyword_cover` rewards vocabulary, not understanding.** It is a",
        "  proxy chosen because it is stable across rewording, not because it",
        "  measures comprehension.",
        "- Latency is wall-clock on one machine including local model load",
        "  time, so it is indicative of relative cost, not a benchmark.",
        f"- **{REPEATS} repeats detects gross non-determinism, not rare flakiness.**",
        "  A routing decision that varies one time in twenty would very likely",
        "  show as consistent here. The repeats exist because a single-run",
        "  baseline missed a real non-determinism bug during development; they",
        "  raise the floor, they do not prove determinism.",
    ]
    return "\n".join(lines) + "\n"


def main():
    results = {}
    for model in CANDIDATE_MODELS:
        print(f"Running {model}...")
        results[model] = run_model(model)
    OUTPUT_PATH.write_text(render_report(results))
    print(f"\nWrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
