# System Architecture — CloudServe Support System

**Status:** Design only. No implementation code in this document. This defines the shape of the
system, the contract between its parts, and the decisions that still need to be settled with
evaluation data during the build.

**Traceability:** every section below references the Project Brief section (§) or Build
Specification acceptance criterion (A#) it satisfies, so the chain from discovery → requirement
→ design stays visible.

---

## 0. Framing

CloudServe asked for a chatbot. Discovery data supports a narrower, more defensible system:
71% of development tickets are `answerable_from_docs: true` (357/500), yet historical
first-contact resolution sits at 42% and escalation at 58%. The gap between "the answer already
exists" and "the customer waited eight hours" is a **retrieval-and-routing failure**, not an
answer-generation failure. This shapes every decision below: the system is designed to know when
it knows, and to make escalation a high-quality handoff rather than a fallback (Brief §02, §05).

87 of 500 tickets (17%) also carry `must_not_auto_respond: true` — categories such as
`security_incident`, `compliance_request`, and `data_residency` are policy-excluded from
automation regardless of confidence. That is a design input, not a build afterthought.

---

## 1. High-level architecture

Six components run in sequence. Three concerns cut across all of them rather than sitting at
the end (Brief §04, Figure 3).

```
┌────────┐  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌──────────┐  ┌──────────┐
│ Ingest │→ │ Classify │→ │ Retrieve │→ │ Route │→ │ Generate │→ │ Validate │→ out
└────────┘  └──────────┘  └──────────┘  └───────┘  └──────────┘  └──────────┘
   ───────────────────────  Security & Privacy  ───────────────────────────
   ───────────────────────  Observability        ───────────────────────────
   ───────────────────────  Governance & Decision Log ───────────────────────
```

See the companion visual (`System_Architecture.html`) for the diagram form of this and the four
other figures referenced below.

| Component | Responsibility | Primary failure mode designed against |
|---|---|---|
| Ingest | Normalise 4 channels into one representation | Channel quirks leaking downstream |
| Classify | Intent + urgency + calibrated confidence | Confidence that doesn't track real accuracy |
| Retrieve | Find grounding passages, with identifiers | Plausible-but-irrelevant retrieval |
| Route | Auto-respond vs. escalate, deterministically | Threshold picked by feel, not data |
| Generate | Grounded, cited draft (answer or summary) | Fluent text unsupported by its sources |
| Validate | Block on private data / unsupported claims | Guardrail that only warns |

---

## 2. End-to-end flow (the mechanism that matters)

The detail that a linear box diagram hides: **Generate and Validate run on both branches**, not
only the auto-respond path. Route decides *what kind* of draft to produce and *who* ultimately
reads it — a customer or an agent — not whether a draft gets produced at all. This is what makes
escalation a feature (Brief §05): the agent receives a drafted summary, the retrieved sources,
and a stated reason, not a bare ticket.

```
Ingest → Classify → Retrieve → Route ──┬── auto-respond path ──┐
                                        └── escalate path ──────┤
                                                                 ↓
                                                            Generate
                                              (customer answer | agent-facing summary)
                                                                 ↓
                                                             Validate
                                              (private data · unsupported claims · tone)
                                          ┌──────────────────────┴───────────────────────┐
                                   pass + auto-respond                     fail, or pass + escalate
                                          ↓                                              ↓
                                  send to customer                          queue to agent, with
                                                                       drafted summary + sources + reason
                                                                 ↓ (always)
                                                          Decision Log
```

A Validate failure on the auto-respond path does not drop the ticket — it **converts to an
escalation** with the guardrail reason attached, satisfying A11 (no silent failure) and A7
(guardrails actually block) at once.

---

## 3. Component scope

### 3.1 Ingest — Brief §04, Build Spec A1/A2/A11

- **Inputs:** raw payloads from four sources — email, live chat, docs-comment, forum — each with
  different native fields (e.g. email has a subject line and thread ID; chat has no subject;
  forum has a thread context other customers may have already replied in).
- **Output contract (fields, not code):** `ticket_id`, `channel`, `subject` (nullable),
  `body`, `received_at`, `customer_id`, `customer_tier`, `customer_region`,
  `language_fluency`, plus a `raw_payload` passthrough so the original text is never lost.
- **Design decisions:**
  - One adapter per channel, one shared output schema. New channels add an adapter, not a
    rewrite of downstream components.
  - Empty body, missing subject, and non-UTF-8 characters are normalised, not rejected —
    `development_tickets.json` already contains an empty-subject chat ticket, so this is a
    certainty, not an edge case.
  - `language_fluency` and `customer_tier`/`customer_region` are carried through untouched
    for later use in the fairness audit (§8.3) — Ingest does not act on them, only preserves
    them.

### 3.2 Classify — Brief §04, Build Spec A3

- **Output contract:** `intent` (one of the ~22 categories observed in discovery, plus an
  `unclear_request`/fallback category that already exists in the data), `urgency`
  (`low`/`medium`/`high`), `confidence` (0–1, float), and `alternatives` — the next-best
  intent(s) considered, per Build Spec ("records the alternatives it considered, not only the
  option it chose").
- **Design decisions:**
  - Confidence must be **calibrated**, not a raw model logit dressed up as a probability. Plan:
    hold out a slice of `development_tickets.json`, compare stated confidence against actual
    correctness in bins (e.g. 0.7–0.8, 0.8–0.9, 0.9–1.0), and apply a calibration step
    (temperature scaling or isotonic regression) if the bins disagree with the labels — this is
    what the governance target "confidence within five points of observed accuracy" requires.
  - Never raises on an unparseable or ambiguous ticket — returns the defined fallback
    (`intent = unclear_request`, low confidence) so Route can act on it deterministically.
  - Classification and confidence estimation are logically separate steps even if implemented
    as one model call, so either can be swapped independently later.

### 3.3 Retrieve — Brief §04, Build Spec A4

- **Corpus:** 29 documents, Markdown-formatted with consistent internal structure (Symptoms /
  Common causes / Resolution / Notes headings), organised into 10 categories (authentication,
  deployment, api, performance, billing, data, security, account, integration, onboarding).
- **Chunking strategy:** chunk by heading section, not by fixed token windows. The corpus's own
  structure (Symptoms, Causes, Resolution) is the natural retrieval unit — a "Resolution"
  section retrieved on its own is more useful and more citable than an arbitrary 512-token
  slice that straddles two headings. Each chunk keeps `doc_id`, `title`, and `category` as
  metadata so a citation always resolves to a real, addressable passage (A4's explicit
  requirement).
- **Output contract:** ranked list of `{doc_id, chunk_id, title, score}`, filtered by a
  relevance threshold. Below threshold → **empty list**, which Route must treat as a first-class
  signal, not an error ("returning nothing is a valid and often correct answer" — Build Spec
  §08).
- **Design decisions:**
  - Embedding model fixed at `all-MiniLM-L6-v2` per the technical constraint (Brief §09).
  - `related_docs` links already present in the corpus are a candidate signal for a second-pass
    re-ranking step, to be validated during build rather than assumed useful.
  - The relevance threshold and `top_k` are tuned against `development_tickets.json`'s
    `expected_doc_ids` labels (357 tickets have them) — this gives a measurable retrieval hit
    rate to tune against, not a guess.

### 3.4 Route — Brief §04, §05, Build Spec A5

- **Output contract:** `decision` (`auto_respond` | `escalate`), `reason` (a short string a
  support manager could read, e.g. "confidence 0.62 below threshold 0.80"), `threshold_used`.
- **Design decisions — the decision tree (see Figure 5 in the companion HTML):**
  1. No retrieval hit above threshold → escalate (`reason: no_grounding`).
  2. Intent is in the policy-excluded set (mirrors `must_not_auto_respond` in the data —
     security, compliance, data-residency categories) → escalate (`reason: policy_excluded`),
     **checked before confidence**, because no confidence score justifies auto-answering a
     security incident.
  3. Confidence below threshold → escalate (`reason: low_confidence`).
  4. Otherwise → proceed to Generate as an auto-respond candidate, subject to Validate's final
     gate.
  - **Determinism (A5):** routing is a pure function of `(confidence, retrieval_result, intent,
    threshold)` with no randomness or hidden state — same input, same decision, every time.
  - **The threshold itself is not fixed here.** 0.80 is the brief's illustrative starting point.
    The real value is set by sweeping thresholds against `development_tickets.json`'s
    `expected_route` labels and plotting the trade-off in §7.

### 3.5 Generate — Brief §04, Build Spec A6, A11

- **Two modes on one component**, selected by the Route decision already in state:
  - *Customer-facing answer* (auto-respond candidates): direct, grounded, cited response.
  - *Agent-facing summary* (escalations): what the customer is asking, what was found (or not
    found) in the docs, what's uncertain, and why it escalated — so the agent starts ahead
    rather than at zero.
- **Output contract:** `draft_text`, `citations` (list of `{claim_span, doc_id, chunk_id}` —
  every claim maps to a retrieved chunk, not a free-floating reference), `mode`
  (`answer`|`summary`), `refused` (boolean, set when the model states it doesn't know rather
  than fills the gap).
- **Design decisions:**
  - **Prompt injection defense:** ticket body is passed as untrusted data in a clearly
    delimited field, never concatenated into the instruction text. The system prompt states
    explicitly that content inside the ticket cannot alter instructions — this is what "customer
    text cannot redirect the system" (Build Spec) actually requires architecturally, not just
    as a stated intent.
  - **Structured output** (a defined schema Generate must return) rather than free text with a
    citations section hand-parsed afterward — this is what makes A6 checkable by code rather than
    by eyeballing.
  - If retrieval returned nothing, Generate is not called for an "answer" — Route already sent
    this to escalate, so Generate only ever drafts a summary here. No hallucinated grounding is
    possible because there is nothing to fabricate a citation against.

### 3.6 Validate — Brief §04, Build Spec A7, A11

- **Runs on every draft, both modes, unconditionally** — this single rule is what stops
  guardrails degrading into a testing-only checklist (Build Spec §08).
- **Checks (minimum set, each independently able to block):**
  1. **Private data** — pattern/entity detection for secrets, card numbers, other customers'
     identifiers appearing in the draft (the governance condition of zero tolerance, Brief §07).
  2. **Unsupported claims** — every sentence carrying a factual claim must map to a citation
     from Generate's own `citations` list; claims with no matching citation fail this check.
  3. **Tone** — flags responses that are curt, hedge excessively, or contradict the "states
     plainly when it doesn't know" requirement.
- **Output contract:** `passed` (boolean), `checks_run` (list, always populated — "records what
  it checked and what it found, whether or not it blocked"), `blocked_reason` (nullable).
- **On failure:** the ticket routes to escalation regardless of the original Route decision, the
  guardrail reason is attached, and the event is logged as a guardrail activation — this is the
  measurable event A7's test ("a ticket engineered to trigger it") checks for.

---

## 4. Low-level architecture — three layers

Separating these is what lets the model provider or vector store change without touching the
component logic (Brief §04, Figure 4).

| Layer | Owns | Contains |
|---|---|---|
| **Interface & Orchestration** | Request handling, step sequencing | FastAPI app (ingress, health, metrics endpoints); LangGraph `StateGraph` wiring the six components as nodes with conditional edges; the evaluation harness as a batch-mode caller of the same graph |
| **Intelligence** | Model-backed reasoning | Classifier (LLM call + calibration), Retriever (Chroma query + `all-MiniLM-L6-v2` embedding), Generator (LLM call via OpenRouter/Groq client, provider-agnostic behind one interface), Guardrail checks (rule-based checks + one LLM-based unsupported-claim check) |
| **Persistence & Ops** | State that outlives a single request | Chroma collection (on-disk vector store); decision log (Postgres or SQLite — same schema either way, per the technical constraint); Prometheus metrics; structured JSON logs |

The provider client (OpenRouter/Groq) and the vector store client (Chroma) are each accessed
through one narrow interface each. Swapping either is a Layer 2 change with no ripple into
Layer 1's orchestration or Layer 3's schemas.

---

## 5. Orchestration as a state graph

LangGraph is the right tool here specifically because routing is conditional, not linear — the
brief calls this out directly (Brief §09). Nodes: `ingest`, `classify`, `retrieve`, `route`
(conditional), `generate`, `validate` (conditional), `deliver`, `escalate`. Every node writes
its own record to the decision log as a side effect of running — logging is not a final node
bolted on the end, because that pattern is exactly how partial runs lose their tail-end
decisions (Build Spec §08, "a decision log written only for the tickets that succeeded").

**Resilience is graph structure, not an afterthought (A11):**

- Each Intelligence-layer node (`classify`, `retrieve`, `generate`) wraps its model/DB call with
  timeout + bounded retry + backoff.
- Retries exhausted on `classify` → falls back to the `unclear_request` default rather than
  failing the node.
- Retries exhausted on `generate` (provider outage) → falls back to a template response stating
  the system cannot draft an answer right now, which still passes through `validate` and still
  logs, and the ticket escalates. This is the graceful-degradation path the brief explicitly
  rewards (Brief §01, "a system that degrades gracefully during an outage gains credit").
- Malformed/empty ticket bodies are caught at `ingest` and produce a valid (if minimal)
  normalised record rather than raising — everything downstream can assume a well-formed input.

---

## 6. Cross-cutting concerns

### 6.1 Security & privacy

- No credential ever committed — configuration is environment-variable driven
  (`OPENROUTER_API_KEY`, `DATABASE_URL`, etc.), matching the constraint that no key may appear in
  source (Brief §09).
- Prompt injection defense is structural (§3.5), not a denylist of phrases.
- PII/private-data detection is a Validate check (§3.6), not a UI-layer suggestion.
- `customer_id`, `customer_name` are retained in the decision log (needed for audit and repeat
  contact tracking) but never interpolated into a customer-facing draft unless the ticket's own
  content already contains them.

### 6.2 Observability

- **Metrics (Prometheus):** requests per channel, classification confidence distribution,
  retrieval hit rate, routing decision counts, guardrail activation counts, latency per
  component and end-to-end, at median and 95th percentile.
- **Structured logs:** one JSON line per component execution per ticket, correlated by
  `ticket_id` and a `run_id`, so a single ticket's path through all six components can be
  reconstructed from logs alone, independent of the decision log table.

### 6.3 Governance & decision log

This is Layer 3 by design, not an afterthought (Brief §04: "the decision log sits in the
persistence layer alongside the metrics"). One row per automated decision, minimum fields:

| Field | Purpose |
|---|---|
| `decision_id`, `ticket_id`, `channel` | Identify and reconcile against tickets processed (A8) |
| `stage` | Which component made this decision (classify / route / validate) |
| `input_summary` | What was decided on |
| `prediction`, `confidence` | What was decided, and how sure |
| `retrieved_doc_ids` | Sources used, if any |
| `action`, `reason` | What happened, and why, in manager-readable language |
| `guardrail_checks`, `guardrail_blocked` | What Validate checked and whether it blocked |
| `latency_ms` | Per-decision timing, rolls up into the p95 metric |
| `model_used`, `threshold_used` | Reproducibility of the decision |
| `timestamp` | When |

A8 is verified by **reconciling row count against tickets processed** — this schema is designed
so every node write is atomic and independent, so a crash mid-run leaves a partial-but-honest
log rather than a gap that silently drops the failing ticket.

The fairness audit (Brief §08) reads this same table, grouped by `customer_tier`,
`customer_region`, and `language_fluency` (already present on every ticket from Ingest, §3.1),
comparing confidence, routing outcome, and guardrail-block rate across groups — no separate data
pipeline required.

---

## 7. Routing threshold — how it gets set, not what it is

The brief is explicit that 0.80 is illustrative and the real number must be earned from data
(Brief §05). Method:

1. Run Classify over `development_tickets.json` (500 labelled tickets) — never the validation or
   hidden set — and record confidence vs. actual correctness.
2. Sweep candidate thresholds; for each, compute the resulting automation rate, precision on
   auto-answered tickets, and the count that would have been auto-answered incorrectly.
3. Choose the threshold that satisfies the governance floor first (near-zero wrong auto-answers
   in the sample) and only then maximises automation — not the other way round.
4. Record the chosen value, the sweep data, and the reasoning in the evaluation report,
   including what was traded away (Brief §05 table: too low harms customers, too high wastes the
   build).

This sweep, and the resulting number, is explicitly **out of scope for this document** — it is a
build-time, data-driven decision, not an architectural one.

---

## 8. Failure handling — mapped to A11

| Condition | Behaviour |
|---|---|
| No retrieval hit above threshold | Route treats as a valid signal → escalate, not an error |
| Provider timeout | Bounded retry with backoff, then graceful fallback text, ticket still logged and escalated |
| Full provider outage | Same fallback path; system keeps processing subsequent tickets rather than halting the batch |
| Rate limiting | Backoff + local response cache (development-time) to stay inside free-tier limits, per Brief §07 |
| Malformed / empty ticket | Normalised to a minimal valid record at Ingest; never raises downstream |
| Guardrail block | Converts to escalation, logged as a guardrail activation, never silently dropped |

---

## 9. API surface (contract only)

| Endpoint | Purpose |
|---|---|
| `POST /tickets` | Submit a single ticket, synchronous response — used for the four-channel smoke test in the test procedure |
| `GET /health` | Liveness/readiness, checks provider and vector store reachability |
| `GET /metrics` | Prometheus scrape endpoint |
| Evaluation harness (CLI, not HTTP) | `--input <path> --output <path>`, processes a full file unattended, emits the metrics report — deliberately a CLI, not an endpoint, so A9's "single documented command" has no server lifecycle to manage |

---

## 10. Evaluation harness — architecture only

A thin driver over the same LangGraph graph used by the API, run in batch: read every ticket
from the input file, invoke the graph once per ticket, accumulate decision log rows, and at the
end compute and write the metrics report (Build Spec §04) without further manual steps — volume
counts, business metrics (FCR, response time, escalation rate), technical metrics
(classification precision/recall per class, retrieval hit rate, latency percentiles), and
governance metrics (decisions logged, guardrail activations by type, private-data detections),
each computed by code against the decision log, not compiled by hand afterward.

---

## 11. Acceptance criteria traceability

| # | Criterion | Satisfied by |
|---|---|---|
| A1 | Clean-checkout run | §9 CLI/API separation; no hidden local state |
| A2 | Four-channel ingest | §3.1 per-channel adapters, one output schema |
| A3 | Classify + confidence | §3.2 |
| A4 | Retrieval resolves to real passages | §3.3 chunk-level `doc_id`/`chunk_id` metadata |
| A5 | Deterministic routing | §3.4 pure function of state, no randomness |
| A6 | Citations resolve to retrieved text | §3.5 structured `citations` output |
| A7 | Guardrail actually blocks | §3.6, always-on, converts to escalation |
| A8 | Complete decision log | §6.3, one row per node execution, per ticket |
| A9 | Unattended full-set run | §5 resilience design, §10 harness |
| A10 | Metrics report, no manual work | §10 |
| A11 | Degrades without crashing | §5 retry/fallback, §8 failure table |
| A12 | Tests pass on one command | Out of scope for this document — test design follows once components are built |

---

## 12. Explicitly deferred to build

This document defines shape and contracts. The following are measured decisions, not
architectural ones, and are deliberately left open here:

- The exact confidence threshold (§7).
- The exact relevance threshold and `top_k` for retrieval (§3.3).
- Whether calibration needs temperature scaling or isotonic regression, and its parameters
  (§3.2).
- The specific guardrail rule set for "unsupported claim" beyond citation-mapping (e.g. any
  additional heuristics found necessary once real generations are inspected).

Each will be set against `development_tickets.json` and reported with the method used, per
Brief §06's rule not to touch the validation or hidden sets during tuning.
