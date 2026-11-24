"""FastAPI app: GET /health, POST /chat, GET /sessions/{session_id}/messages."""
import logging
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings, load_settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMGateway, elapsed_ms, parse_simulation
from .schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.sqlite_path)
    db.init()  # schema is created automatically on startup
    gateway = LLMGateway(settings)

    app = FastAPI(title="AI Chat Gateway", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/health")
    def health():
        keys = len(gateway.pool)
        if not db.ping() or keys < 1:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "keys_configured": keys, "cache_enabled": gateway.cache_enabled},
            )
        return {"status": "ok", "keys_configured": keys, "cache_enabled": gateway.cache_enabled}

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
        start = time.perf_counter()

        requested_prompt = req.system_prompt.strip() if req.system_prompt else None
        system_prompt = requested_prompt or db.get_system_prompt(req.session_id) or settings.default_system_prompt
        messages = (
            [{"role": "system", "content": system_prompt}]
            + db.get_history(req.session_id)
            + [{"role": "user", "content": req.message}]
        )

        simulate = parse_simulation(x_simulate_failure) if settings.enable_failure_simulation else {}
        try:
            result = gateway.complete(messages, simulate)
        except AllProvidersUnavailable:
            raise HTTPException(status_code=503, detail="all providers unavailable")

        metadata = {
            "resolution_source": result.resolution_source,
            "model": result.model,
            "latency_ms": elapsed_ms(start),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key_id": result.key_id,
            "fallback_attempts": result.fallback_attempts,
        }
        db.save_exchange(req.session_id, req.message, result.reply, metadata, requested_prompt)
        return {"session_id": req.session_id, "reply": result.reply, "metadata": metadata}

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str):
        messages = db.get_messages(session_id)
        if not messages:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": messages}

    return app


app = create_app()
