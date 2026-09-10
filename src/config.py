import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

if GROQ_API_KEY and not OPENROUTER_API_KEY:
    LLM_API_KEY = GROQ_API_KEY
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
else:
    LLM_API_KEY = OPENROUTER_API_KEY
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

MODEL_NAME = os.getenv("MODEL_NAME", "meta-llama/llama-3.1-8b-instruct")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

CHROMA_PATH = os.getenv("CHROMA_PATH", str(BASE_DIR / "storage" / "chroma"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'storage' / 'decisions.db'}")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))
RETRIEVAL_RELEVANCE_THRESHOLD = float(os.getenv("RETRIEVAL_RELEVANCE_THRESHOLD", "0.30"))

# Intent categories that never auto-respond regardless of confidence (Brief §05, §07).
POLICY_EXCLUDED_INTENTS = {
    "security_incident",
    "compliance_request",
    "data_residency",
}

# Kill switch: set AUTO_RESPONSE_ENABLED=false to disable every auto-response without a
# code deploy. Checked at the last possible moment (node_finalize), so flipping it takes
# effect on the next ticket with no restart needed. When off, every ticket that would have
# been sent to the customer is escalated instead -- the system keeps processing, it just
# stops sending anything automatically.
AUTO_RESPONSE_ENABLED = os.getenv("AUTO_RESPONSE_ENABLED", "true").lower() not in ("false", "0", "no")

LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
LLM_BACKOFF_BASE_SECONDS = float(os.getenv("LLM_BACKOFF_BASE_SECONDS", "1.5"))
