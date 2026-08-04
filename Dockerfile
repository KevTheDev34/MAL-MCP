FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN mkdir -p /data

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY alembic.ini ./
COPY docs ./docs
COPY AGENTS.md PROJECT_SPEC.md IMPLEMENTATION_CHECKLIST.md ./

RUN pip install --upgrade pip \
    && pip install .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
