import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import END, StateGraph

from src import classify, config, decision_log, generate, guardrails, ingest, metrics, route
from src.retrieve import Retriever
from src.schemas import ClassificationResult, DecisionLogEntry, GenerationResult, PipelineState, RoutingDecision, ValidationResult, Ticket

logger = logging.getLogger("cloudserve.graph")

_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def _entry(ticket: Ticket, stage: str, prediction: str, action: str, reason: str, **kw) -> DecisionLogEntry:
    return DecisionLogEntry(
        ticket_id=ticket.ticket_id, channel=ticket.channel, stage=stage,
        prediction=prediction, action=action, reason=reason, **kw,
    )


def node_ingest(state: PipelineState) -> dict:
    ticket = ingest.normalize_ticket(state["raw"])
    return {"ticket": ticket, "log_entries": []}


def _run_classify(ticket: Ticket) -> tuple[ClassificationResult, float]:
    t0 = time.time()
    try:
        classification = classify.classify(ticket)
    except Exception:
        logger.error("unexpected classify failure for %s:\n%s",
                     ticket.ticket_id, traceback.format_exc())
        classification = ClassificationResult(
            intent="unclear_request", urgency="medium", confidence=0.0, fallback_used=True)
    return classification, (time.time() - t0) * 1000


def _run_retrieve(ticket: Ticket, query: str) -> tuple[list, float]:
    t0 = time.time()
    try:
        retrieved = get_retriever().retrieve(query)
    except Exception:
        logger.error("unexpected retrieval failure for %s:\n%s",
                     ticket.ticket_id, traceback.format_exc())
        retrieved = []
    return retrieved, (time.time() - t0) * 1000


def node_classify_and_retrieve(state: PipelineState) -> dict:
    """Classify (an LLM call) and Retrieve (local embedding + Chroma query) don't
    depend on each other's output, so they run concurrently rather than back to
    back — this is the one real win available against the p95 latency target
    without changing the model or dropping a pipeline stage (System_Architecture.md
    componentry unchanged; only the graph's scheduling of two independent nodes)."""
    ticket = state["ticket"]
    query = f"{ticket.subject or ''} {ticket.body}".strip()

    with ThreadPoolExecutor(max_workers=2) as pool:
        classify_future = pool.submit(_run_classify, ticket)
        retrieve_future = pool.submit(_run_retrieve, ticket, query)
        classification, classify_latency_ms = classify_future.result()
        retrieved, retrieve_latency_ms = retrieve_future.result()

    metrics.STAGE_LATENCY.labels(stage="classify").observe(
        classify_latency_ms / 1000)
    metrics.STAGE_LATENCY.labels(stage="retrieve").observe(
        retrieve_latency_ms / 1000)
    metrics.CLASSIFICATION_CONFIDENCE.observe(classification.confidence)

    classify_entry = _entry(
        ticket, "classify", classification.intent, "classified",
        f"urgency={classification.urgency}, fallback={classification.fallback_used}",
        confidence=classification.confidence, latency_ms=classify_latency_ms, model_used=config.MODEL_NAME,
    )
    retrieve_entry = _entry(
        ticket, "retrieve", f"{len(retrieved)} passages", "retrieved",
        ", ".join(
            p.doc_id for p in retrieved) if retrieved else "no passage cleared relevance threshold",
        retrieved_doc_ids=[p.doc_id for p in retrieved], latency_ms=retrieve_latency_ms,
    )
    return {
        "classification": classification,
        "retrieved": retrieved,
        "log_entries": state["log_entries"] + [classify_entry.model_dump(), retrieve_entry.model_dump()],
    }


def node_route(state: PipelineState) -> dict:
    ticket = state["ticket"]
    routing = route.route(
        state["classification"], state["retrieved"], ticket_body=ticket.body or "", threshold=config.CONFIDENCE_THRESHOLD
    )
    metrics.ROUTING_DECISIONS.labels(action=routing.action).inc()
    entry = _entry(
        ticket, "route", routing.action, routing.action, routing.reason,
        confidence=state["classification"].confidence, threshold_used=routing.threshold_used,
        retrieved_doc_ids=[p.doc_id for p in state["retrieved"]],
    )
    return {"routing": routing, "log_entries": state["log_entries"] + [entry.model_dump()]}


def node_generate(state: PipelineState) -> dict:
    ticket, routing = state["ticket"], state["routing"]
    t0 = time.time()
    try:
        generation = generate.generate(
            ticket, state["classification"], state["retrieved"], routing)
    except Exception:
        logger.error("unexpected generation failure for %s:\n%s",
                     ticket.ticket_id, traceback.format_exc())
        mode = "answer" if routing.action == "auto_respond" else "summary"
        generation = GenerationResult(
            draft_text="Unable to draft a response right now.", mode=mode, refused=True)
    latency_ms = (time.time() - t0) * 1000
    metrics.STAGE_LATENCY.labels(stage="generate").observe(latency_ms / 1000)
    entry = _entry(
        ticket, "generate", generation.mode, "drafted",
        f"refused={generation.refused}, citations={len(generation.citations)}", latency_ms=latency_ms, model_used=config.MODEL_NAME,
    )
    return {"generation": generation, "log_entries": state["log_entries"] + [entry.model_dump()]}


def node_validate(state: PipelineState) -> dict:
    ticket = state["ticket"]
    try:
        validation = guardrails.validate(state["generation"], ticket)
    except Exception:
        logger.error("unexpected validation failure for %s:\n%s",
                     ticket.ticket_id, traceback.format_exc())
        validation = ValidationResult(
            passed=False, checks_run=[], blocked_reason="internal_error")
    if not validation.passed:
        check_name = (validation.blocked_reason or "unknown").split(":")[0]
        metrics.GUARDRAIL_BLOCKS.labels(check=check_name).inc()
    entry = _entry(
        ticket, "validate", "passed" if validation.passed else "blocked",
        "guardrail_pass" if validation.passed else "guardrail_block",
        validation.blocked_reason or "all checks passed",
        guardrail_checks=[c.name for c in validation.checks_run], guardrail_blocked=not validation.passed,
    )
    return {"validation": validation, "log_entries": state["log_entries"] + [entry.model_dump()]}


_AI_DISCLOSURE = "\n\n---\nThis response was drafted automatically from our documentation, not written by a person."


def node_finalize(state: PipelineState) -> dict:
    ticket, routing, validation, generation = state["ticket"], state[
        "routing"], state["validation"], state["generation"]
    if validation.passed and routing.action == "auto_respond" and config.AUTO_RESPONSE_ENABLED and not generation.refused:
        final_action, final_text = "sent_to_customer", generation.draft_text + _AI_DISCLOSURE
        reason = routing.reason
    else:
        final_action, final_text = "escalated", generation.draft_text
        if generation.refused:
            reason = "model declined to answer (refused=true) -- escalated rather than auto-sending a non-answer"
        elif not config.AUTO_RESPONSE_ENABLED and validation.passed and routing.action == "auto_respond":
            reason = "kill switch active (AUTO_RESPONSE_ENABLED=false) -- auto-response withheld"
        else:
            reason = validation.blocked_reason or routing.reason
    entry = _entry(ticket, "finalize", final_action, final_action, reason)
    return {"final_action": final_action, "final_text": final_text, "log_entries": state["log_entries"] + [entry.model_dump()]}


def build_graph():
    graph = StateGraph(PipelineState)
    for name, fn in [
        ("ingest", node_ingest), ("classify_and_retrieve", node_classify_and_retrieve),
        ("route", node_route), ("generate",
                                node_generate), ("validate", node_validate),
        ("finalize", node_finalize),
    ]:
        graph.add_node(name, fn)
    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "classify_and_retrieve")
    graph.add_edge("classify_and_retrieve", "route")
    graph.add_edge("route", "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def run_pipeline(raw_ticket: dict) -> dict:
    t0 = time.time()
    result = get_graph().invoke({"raw": raw_ticket, "log_entries": []})
    total_latency_ms = (time.time() - t0) * 1000
    metrics.PIPELINE_LATENCY.observe(total_latency_ms / 1000)
    metrics.TICKETS_PROCESSED.labels(channel=result["ticket"].channel).inc()

    for entry_dict in result["log_entries"]:
        decision_log.log_decision(DecisionLogEntry(**entry_dict))

    return {
        "ticket_id": result["ticket"].ticket_id,
        "channel": result["ticket"].channel,
        "classification": result["classification"].model_dump(),
        "retrieved": [p.model_dump() for p in result["retrieved"]],
        "routing": result["routing"].model_dump(),
        "generation": result["generation"].model_dump(),
        "validation": result["validation"].model_dump(),
        "final_action": result["final_action"],
        "final_text": result["final_text"],
        "latency_ms": total_latency_ms,
        "log_entries_written": len(result["log_entries"]),
    }
