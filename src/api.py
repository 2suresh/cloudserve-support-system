import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from src import config, decision_log, metrics
from src.graph import get_graph, get_retriever, run_pipeline

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    decision_log.init_db()
    get_retriever()
    get_graph()
    yield


app = FastAPI(title="CloudServe Support System", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    checks = {"database": False, "vector_store": False, "model_key_configured": bool(config.LLM_API_KEY)}
    try:
        decision_log.get_session().close()
        checks["database"] = True
    except Exception as exc:
        logging.getLogger("cloudserve.api").warning("health check db failure: %s", exc)
    try:
        get_retriever()
        checks["vector_store"] = True
    except Exception as exc:
        logging.getLogger("cloudserve.api").warning("health check vector store failure: %s", exc)
    healthy = checks["database"] and checks["vector_store"]
    return {"status": "ok" if healthy else "degraded", "checks": checks}


@app.post("/tickets")
def submit_ticket(raw_ticket: dict):
    if not raw_ticket:
        raise HTTPException(status_code=422, detail="ticket body must not be empty")
    return run_pipeline(raw_ticket)


@app.get("/metrics")
def metrics_endpoint():
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=False)
