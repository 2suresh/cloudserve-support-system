import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="cloudserve_test_")
os.environ["CHROMA_PATH"] = str(Path(_tmp) / "chroma")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.80")
os.environ.setdefault("RETRIEVAL_RELEVANCE_THRESHOLD", "0.30")

import pytest  # noqa: E402

from src import config  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def build_test_index():
    doc_path = config.BASE_DIR / "data" / "documentation.json"
    if doc_path.exists():
        from src.retrieve import build_index

        build_index(doc_path, force=True)
