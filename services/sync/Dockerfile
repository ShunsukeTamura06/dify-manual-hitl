FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# プロジェクトのビルドには pyproject.toml / README.md / app が必要
COPY pyproject.toml README.md ./
COPY app ./app
RUN uv pip install --system --no-cache .

EXPOSE 8002

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
