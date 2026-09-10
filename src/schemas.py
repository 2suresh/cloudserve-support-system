from datetime import datetime, timezone
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

Channel = Literal["email", "chat", "docs_comment", "forum"]
Urgency = Literal["low", "medium", "high"]
RouteAction = Literal["auto_respond", "escalate"]
GenerationMode = Literal["answer", "summary"]


class Ticket(BaseModel):
    ticket_id: str
    channel: Channel
    subject: Optional[str] = None
    body: str
    received_at: Optional[str] = None
    customer_id: Optional[str] = None
    customer_tier: Optional[str] = None
    customer_region: Optional[str] = None
    language_fluency: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)


class Alternative(BaseModel):
    intent: str
    confidence: float


class ClassificationResult(BaseModel):
    intent: str
    urgency: Urgency
    confidence: float
    alternatives: list[Alternative] = Field(default_factory=list)
    fallback_used: bool = False


class RetrievedPassage(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    category: Optional[str] = None
    text: str
    score: float


class RoutingDecision(BaseModel):
    action: RouteAction
    reason: str
    threshold_used: float


class Citation(BaseModel):
    claim_span: str
    doc_id: str
    chunk_id: str


class GenerationResult(BaseModel):
    draft_text: str
    citations: list[Citation] = Field(default_factory=list)
    mode: GenerationMode
    refused: bool = False


class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class ValidationResult(BaseModel):
    passed: bool
    checks_run: list[GuardrailCheck] = Field(default_factory=list)
    blocked_reason: Optional[str] = None


class DecisionLogEntry(BaseModel):
    ticket_id: str
    channel: str
    stage: str
    prediction: str
    confidence: Optional[float] = None
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    action: str
    reason: str
    guardrail_checks: list[str] = Field(default_factory=list)
    guardrail_blocked: bool = False
    latency_ms: float = 0.0
    model_used: Optional[str] = None
    threshold_used: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PipelineState(TypedDict, total=False):
    raw: dict
    ticket: Ticket
    classification: ClassificationResult
    retrieved: list[RetrievedPassage]
    routing: RoutingDecision
    generation: GenerationResult
    validation: ValidationResult
    final_action: str
    final_text: Optional[str]
    error: Optional[str]
    log_entries: list[dict[str, Any]]
