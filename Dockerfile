FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.12.3
WORKDIR /service
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
RUN useradd --uid 10001 --create-home sandbox && \
    mkdir /data && chown sandbox:sandbox /data
ENV PATH="/service/.venv/bin:$PATH" SANDBOX_DB_PATH=/data/sandbox.sqlite3
USER sandbox
EXPOSE 9000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
