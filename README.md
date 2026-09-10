# CloudServe Support System

An intelligent customer support system for CloudServe Solutions — the Forward
Deployed AI Engineering capstone. Six-stage LangGraph pipeline (Ingest →
Classify → Retrieve → Route → Generate → Validate) over three cross-cutting
concerns (Security, Observability, Governance). See `docs/architecture.md`
for the full design rationale this build follows.

## Setup

Requires Python 3.10+ (developed and tested on 3.11). **Use 3.11 explicitly, not
whatever `python3` resolves to** — on a machine where that's a newer release
(3.14 in testing), `pandas`/`psycopg2-binary`'s original exact pins fail to
build entirely; that part is fixed below to install cleanly on any 3.10–3.14.

3.14 specifically has one further problem that is **not** fixed, deliberately:
`numpy`'s wheels below 2.3 fail to import on 3.14 (`_umath_linalg` can't find
a LAPACK symbol, an Accelerate-framework linking change on newer macOS/Xcode)
— but `langchain<0.2.0` (this project's pin, §09's named orchestration
library) hard-requires `numpy<2`. Those two constraints cannot both be
satisfied. The alternative — moving off the langchain 0.1.x line to unblock
a newer numpy — is a bigger, less-tested change than three days before a
deadline warrants for a Python release the Brief doesn't require. If
`python3.11` isn't available, 3.12 or 3.13 are safe; 3.14 is not, until either
numpy or langchain resolves this upstream.

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# edit .env: fill in OPENROUTER_API_KEY (or GROQ_API_KEY + LLM_BASE_URL)
```

### A note on requirements.txt

A few exact pins in the supplied `requirements.txt` are mutually
unsatisfiable and were relaxed to the narrowest range that resolves cleanly —
each is called out here because it changes real behaviour, not just a version
number:

| Package | Given pin | Changed to | Why |
|---|---|---|---|
| `chromadb` | `0.3.21` | `0.4.24` | 0.3.21 hard-imports `pydantic.BaseSettings`, which only exists under pydantic v1. FastAPI 0.104 and LangChain 0.1 both require pydantic v2. These two pins cannot coexist in one environment; 0.4.24 is pydantic-v2 native and uses `PersistentClient` instead of the old `Settings(chroma_db_impl=...)` API. |
| `pydantic` | `2.0.0` | `>=2.4.0,<3.0.0` | FastAPI 0.104 explicitly excludes `2.0.0`–`2.1.0`. |
| `openai` | `1.0.0` | `>=1.10.0,<2.0.0` | `langchain-openai==0.0.7` requires `openai>=1.10.0`. |
| `sentence-transformers` | `2.2.2` | `>=3.0.0` | 2.2.2 imports `cached_download` from `huggingface_hub`, removed in the `huggingface_hub` version that current `transformers`/`langchain` pull in transitively. |
| `langchain` / `langgraph` / `langchain-community` / `langchain-openai` | exact pins | same versions as floors (`>=`, `<` next minor) | The exact pins depend on an old `langsmith` release with no wheel available for this environment; same minor line, resolvable set. |
| `pandas` / `numpy` / `scikit-learn` | exact pins (`2.0.0`/`1.24.0`/`1.3.0`) | `>=` floors, same versions | Not imported anywhere in `src/`, `evaluation/`, `scripts/`, or `tests/` — kept only because the given file lists them. The exact pins have no wheel on Python 3.14 and fail building from source there; since nothing depends on the exact version, a floor is strictly safer than a pin that works on some machines and not others. |
| `psycopg2-binary` | `2.9.9` | `>=2.9.9` | `2.9.9` has no prebuilt wheel for Python 3.14 and fails to build from source (uses a private CPython API removed in 3.14). Only relevant if `DATABASE_URL` points at Postgres — SQLite, the default, needs no driver at all. |

Everything else installs at the exact pinned version. Ran `pip check` clean
after these changes.

### Verify model access works

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
from src.llm_client import chat_text
print(chat_text('You are a test.', 'Reply with the single word ready.'))
"
```

Do not move on to building on top of this until that returns a real reply.

## Running the system

```bash
# start the API
python -m src.api

# run the full evaluation set, unattended
python -m evaluation.harness --input data/validation_tickets.json --output evaluation/results/

# run the tests
python -m pytest tests/ -v
```

The Chroma index over `data/documentation.json` is built automatically on
first use (by the API's startup hook, the harness, or the test suite) — there
is no separate manual indexing step required for a clean checkout. To rebuild
it explicitly: `python -m scripts.build_index --force`.

### Before the real evaluation run

Two build-time measurements are deliberately left as scripts rather than
hardcoded constants (System_Architecture.md §7, §12) — run them once a model
key works, against `data/development_tickets.json` only, never against
`validation_tickets.json`:

```bash
python -m scripts.compare_thresholds   # sweeps CONFIDENCE_THRESHOLD, prints a trade-off table
python -m scripts.calibrate            # fits confidence calibration, writes storage/calibration.json
```

## Project structure

```
src/
  schemas.py        Pydantic models + the LangGraph state shape
  config.py          env-driven configuration
  llm_client.py        OpenAI-SDK-compatible client (OpenRouter or Groq), retry + backoff
  ingest.py              normalise all 4 channels                              (A2)
  classify.py             intent + urgency + calibrated confidence              (A3)
  retrieve.py               Chroma search over the documentation corpus          (A4)
  route.py                    auto-respond vs escalate, deterministic              (A5)
  generate.py                   grounded, cited drafting (answer or agent summary)   (A6)
  guardrails.py                   blocking checks run on every draft                   (A7)
  decision_log.py                   the decision log (SQLAlchemy, SQLite or Postgres)    (A8)
  metrics.py                         Prometheus counters/histograms
  graph.py                            LangGraph StateGraph wiring the six components
  api.py                                FastAPI app: POST /tickets, /health, /metrics
evaluation/
  harness.py           unattended full-set run + metrics report                (A9, A10)
  report_metrics.py     volume/business/technical/governance metrics, computed by code
scripts/
  build_index.py       (re)build the Chroma index
  compare_thresholds.py  routing threshold sweep against development data
  calibrate.py            confidence calibration against development data
tests/                pytest suite, no real network calls (LLM is monkeypatched)  (A12)
data/                 local dataset copies, gitignored — see Data below
storage/              chroma + sqlite, generated at runtime, gitignored
docs/architecture.md  condensed design notes
```

## Data

`data/documentation.json` **is committed** — it's not test data, it's the
knowledge base the retrieval layer searches, and the system cannot answer
anything without it on a clean checkout.

`development_tickets.json`, `validation_tickets.json` and
`ground_truth_responses.json` are gitignored: they're development/evaluation
aids, not something the system needs to run. The final assessment points
`evaluation.harness` at a hidden 120-ticket file this repo has never seen —
the harness takes `--input`/`--output` paths for exactly that reason, never a
hardcoded filename, so nothing about running it depends on these three files
being present.

## Where this stands

This is a from-scratch build against the architecture design (see
`System_Architecture.md`), using the client's named stack (LangChain +
LangGraph, FastAPI, Chroma, SQLAlchemy over SQLite/Postgres, Prometheus). All
twelve Build Specification criteria are implemented; instrumented and
verified by the test suite. The two data-driven tuning steps above
(confidence threshold, calibration) still need to be run against a live model
key before the honest evaluation run — until then `CONFIDENCE_THRESHOLD=0.80`
in `.env.example` is the brief's illustrative starting point, not a measured
value.

| # | Criterion | Where |
|---|---|---|
| A1 | Clean-checkout run via this README | `requirements.txt` + this file |
| A2 | Four channels ingested and normalised | `src/ingest.py` |
| A3 | Classified with numeric confidence | `src/classify.py` |
| A4 | Retrieval resolves to real passages | `src/retrieve.py` (chunk IDs resolve to `documentation.json`) |
| A5 | Deterministic routing | `src/route.py`, pure function; `tests/test_route.py` |
| A6 | Citations resolve to retrieved passages | `src/generate.py` builds citations only from retrieved indices |
| A7 | Guardrail actually blocks | `src/guardrails.py`; `tests/test_pipeline_e2e.py::test_engineered_guardrail_ticket_gets_blocked_and_escalated` |
| A8 | Complete decision log | `src/decision_log.py`, one row per node per ticket |
| A9 | Unattended full-set run | `evaluation/harness.py` — per-ticket try/except, never drops a ticket |
| A10 | Metrics report, no manual work | `evaluation/report_metrics.py` |
| A11 | Degrades without crashing | fallback paths in `classify.py`/`generate.py`, empty-retrieval handling in `route.py`, per-ticket isolation in `harness.py` |
| A12 | Tests pass on one command | `python -m pytest tests/ -v` — no real network calls required |

## Known limitations, stated plainly

- **Latency (p95 target: under 3s).** `classify` and `retrieve` run concurrently
  (`src/graph.py`'s `node_classify_and_retrieve`, via a thread pool) since neither
  depends on the other's output — a real, verified fix that removes retrieval's
  time from the critical path. It does not close the gap to 3 seconds: `generate`
  still has to wait for the routing decision, so every ticket makes two sequential
  real LLM calls, and a free-tier hosted model's per-call latency alone (several
  seconds, more under rate limiting) makes the 3s target very unlikely to hold
  regardless of scheduling. Measured p95 across the full 500-ticket run was 10.5s;
  a later small-sample re-measurement was worse (rate limiting compounds with the
  volume of API calls already made in a session) rather than better, which is
  itself informative about how this metric behaves in practice on a free tier.
- **`database_issue` classification.** Was 11.5% recall (misclassified as
  `performance_degradation` in 65% of its errors — both describe database-adjacent
  symptoms without a clean vocabulary boundary). A targeted disambiguation rule
  naming connection-pool-exhaustion language explicitly took this to ~81% recall
  in a live re-test (18/23 previously-wrong tickets fixed, 23/23 genuine
  `performance_degradation` tickets held), but this is a single re-test against
  development data, not a re-run of the full evaluation — treat the 81% as
  directionally strong, not as a re-certified metric.
- **Fairness gap (customer_tier, customer_region).** Root-caused to 4 confusable
  intent-category pairs unevenly distributed across groups by sample chance,
  not direct bias (see `docs/architecture.md`'s revision notes / Stage 5
  addendum for the full decomposition). The disambiguation fixes above address
  2 of those 4 pairs directly. Not re-measured end-to-end after the fix; europe's
  residual accuracy gap (the one spread that didn't fully explain away as an
  intent-mix confound) is still open.
