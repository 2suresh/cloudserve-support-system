from pathlib import Path

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

from src import config
from src.schemas import DecisionLogEntry

Base = declarative_base()


class DecisionLog(Base):
    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, index=True, nullable=False)
    channel = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    prediction = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    retrieved_doc_ids = Column(Text, default="")  # comma-separated
    action = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    guardrail_checks = Column(Text, default="")  # comma-separated
    guardrail_blocked = Column(Integer, default=0)  # 0/1, sqlite has no bool
    latency_ms = Column(Float, default=0.0)
    model_used = Column(String, nullable=True)
    threshold_used = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


_engine = None
_SessionLocal = None


def _connect_args() -> dict:
    if config.DATABASE_URL.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine():
    global _engine
    if _engine is None:
        if config.DATABASE_URL.startswith("sqlite:///"):
            db_path = Path(config.DATABASE_URL.replace("sqlite:///", "", 1))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(config.DATABASE_URL, connect_args=_connect_args())
    return _engine


def init_db():
    Base.metadata.create_all(get_engine())


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def log_decision(entry: DecisionLogEntry) -> None:
    session = get_session()
    try:
        row = DecisionLog(
            ticket_id=entry.ticket_id,
            channel=entry.channel,
            stage=entry.stage,
            prediction=entry.prediction,
            confidence=entry.confidence,
            retrieved_doc_ids=",".join(entry.retrieved_doc_ids),
            action=entry.action,
            reason=entry.reason,
            guardrail_checks=",".join(entry.guardrail_checks),
            guardrail_blocked=int(entry.guardrail_blocked),
            latency_ms=entry.latency_ms,
            model_used=entry.model_used,
            threshold_used=entry.threshold_used,
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


def count_distinct_tickets() -> int:
    session = get_session()
    try:
        return session.query(DecisionLog.ticket_id).distinct().count()
    finally:
        session.close()


def rows_for_ticket(ticket_id: str) -> list[DecisionLog]:
    session = get_session()
    try:
        return session.query(DecisionLog).filter(DecisionLog.ticket_id == ticket_id).all()
    finally:
        session.close()


def all_rows() -> list[DecisionLog]:
    session = get_session()
    try:
        return session.query(DecisionLog).all()
    finally:
        session.close()
