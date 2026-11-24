# ---- build stage: install dependencies into an isolated prefix ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---- runtime stage: small image, non-root user ----
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    DATABASE_URL=sqlite:////data/app.db
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown app:app /data
COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=app:app app ./app
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8000'),timeout=4)" || exit 1
# $PORT is set by Render/Railway/Fly; defaults to 8000 locally
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
