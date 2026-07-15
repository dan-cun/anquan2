# SecMind deployment

The repository root `compose.yaml` is the only Compose entry point. It starts the
frontend, backend, one-shot migration service, PostgreSQL, and Qdrant. PostgreSQL
and Qdrant are only attached to the internal `data` network and are not published
to the host.

## Prerequisites

- Docker Desktop with the Linux container daemon running.
- Docker Compose v2.17 or newer. The frontend build uses a named build context.
- At least 4 GB of memory available to Docker.

## Environment preparation

From the repository root in PowerShell:

```powershell
Copy-Item .\docker\compose.env.example .\.env
```

Edit `.env` before starting services. `POSTGRES_PASSWORD` and
`SECMIND_DATABASE_URL` are required by `compose.yaml`; there is deliberately no
database-password default. Keep the PostgreSQL password and the password embedded
in both database URLs identical. The example uses a URL-safe password. Percent-encode
reserved URL characters when constructing a SQLAlchemy URL.

Do not commit `.env` or real API keys. For a production deployment, inject secrets
through the deployment platform and use the backend's `SECMIND_API_KEY_FILE`,
`SECMIND_LLM_API_KEY_FILE`, and `SECMIND_QDRANT_API_KEY_FILE` settings with mounted
read-only secret files.

## Development startup

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

Endpoints:

- Frontend: `http://127.0.0.1:5173`
- Frontend health: `http://127.0.0.1:5173/healthz`
- Direct backend health: `http://127.0.0.1:8000/health`
- API through Nginx: `http://127.0.0.1:5173/api/v1/info`
- Workbench WebSocket through Nginx: `ws://127.0.0.1:5173/ws/flows/{flow_id}`

Follow logs or stop the stack with:

```powershell
docker compose logs -f backend frontend migrate
docker compose down
```

Do not use `docker compose down -v` unless all PostgreSQL, Qdrant, and SecMind data
may be deleted.

## Migration behavior

The `migrate` service runs before the backend. If an `alembic.ini` file and Alembic
migration directory are present in the backend build context, it runs:

```text
alembic upgrade head
```

Until the persistence thread supplies Alembic revisions, it performs the existing
SQLAlchemy metadata bootstrap for the runtime ledger. This fallback creates missing
tables but cannot alter existing table definitions. Production schema changes must
therefore be represented by Alembic revisions before release.

To rerun migrations explicitly:

```powershell
docker compose run --rm migrate
```

## Production startup

1. Pin reviewed image tags in `docker/backend.Dockerfile`, `fronted/Dockerfile`, and
   `compose.yaml`.
2. Set `SECMIND_FRONTEND_BIND=0.0.0.0` only when the host firewall or an external TLS
   reverse proxy controls access.
3. Keep `SECMIND_BACKEND_BIND=127.0.0.1`; normal browser traffic should enter through
   Nginx on the frontend service.
4. Inject PostgreSQL and model credentials from the deployment secret store.
5. Back up PostgreSQL and Qdrant volumes before every schema or application upgrade.
6. Start and verify the stack:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 200 migrate backend
```

The frontend and backend application containers run as non-root users, use read-only
root filesystems, drop Linux capabilities, and only receive writable tmpfs/data
mounts. PostgreSQL and Qdrant also use read-only root filesystems; their persistent
state is restricted to named volumes. The data network is marked internal.

## Backend environment contract

The Compose layer supplies these existing backend settings and does not modify
`app/core/config.py`:

| Setting | Purpose |
| --- | --- |
| `SECMIND_DATABASE_URL` | PostgreSQL URL for ledger, state, and projections |
| `SECMIND_CHECKPOINT_BACKEND` | `postgres` in the Compose deployment |
| `SECMIND_CHECKPOINT_DATABASE_URL` | PostgreSQL URL used by LangGraph checkpoints |
| `SECMIND_PROJECTION_ENABLED` | Enables event projections when implemented |
| `SECMIND_DATA_DIR`, `SECMIND_LEDGER_DIR` | Persistent application data paths |
| `SECMIND_RUNTIME_*` | Runtime roots, demo mode, and execution budgets |
| `SECMIND_LLM_*` | Qwen provider, models, endpoint, and credential |
| `SECMIND_QDRANT_*` | Qdrant endpoint, collections, and vector size |
| `SECMIND_API_KEY` | Optional SecMind API authentication key |
| `SECMIND_CORS_ORIGINS` | Direct-backend development origins |
| `SECMIND_RATE_LIMIT_*` | Backend request-rate limits |

`VITE_API_BASE_URL=/` and `VITE_WS_BASE_URL=/` compile the frontend for same-origin
access. Nginx preserves `/api` and `/ws` paths and forwards WebSocket upgrade headers.

## Troubleshooting

- `failed to connect to the docker API`: start Docker Desktop and wait for the Linux
  engine to become ready.
- `required variable ... is missing`: create the root `.env` and set both required
  PostgreSQL values.
- `migrate` exits unsuccessfully: inspect `docker compose logs migrate`; the backend
  will remain stopped by design.
- Qdrant remains unhealthy: inspect `docker compose logs qdrant` and verify port 6333
  is listening inside the container.
- WebSocket returns 502: verify `backend` is healthy and that the request uses `/ws/`
  or `/api/v1/runs/.../events` through the frontend port.
