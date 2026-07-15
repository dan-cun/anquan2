# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system secmind \
    && useradd --system --gid secmind --home-dir /app --shell /usr/sbin/nologin secmind

COPY pyproject.toml README.md ./

RUN python - <<'PY'
from pathlib import Path
import tomllib

project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
requirements = list(project["dependencies"])
for extra in ("checkpoint", "postgres", "qdrant"):
    requirements.extend(project["optional-dependencies"][extra])
Path("/tmp/requirements.txt").write_text("\n".join(requirements), encoding="utf-8")
PY

RUN python -m pip install --timeout 120 --retries 5 -r /tmp/requirements.txt

COPY . .

RUN python -m pip install --no-deps . \
    && mkdir -p /app/data/inputs /app/data/uploads /app/data/runs /app/data/runtime /app/data/ledger \
    && chown -R secmind:secmind /app

USER secmind

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
