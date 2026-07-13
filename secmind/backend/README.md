# SecMind Backend

FastAPI scaffold for the competition backend. The current implementation is a
working skeleton: REST APIs, WebSocket event streaming, a mock orchestrator,
append-only decision ledger, and extension interfaces for future agents, tools,
LLM providers, knowledge stores, and sandboxes.

## Run

```powershell
cd C:\kaifa\tool\anquan2\secmind\backend
python -m pip install -e .[dev]
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Useful endpoints:

- `GET /health`
- `GET /api/v1/info`
- `POST /api/v1/flows`
- `POST /api/v1/flows/{flow_id}/messages`
- `GET /api/v1/ledger/{flow_id}`
- `GET /api/v1/ledger/{flow_id}/verify`
- `WS /ws/flows/{flow_id}`

The existing `fronted` directory is intentionally left as a visual entry page.
Future feature pages can navigate to workbench, audit replay, knowledge, and
settings routes while using this backend API.

## Qwen Configuration

Set these values in `.env`. The key is intentionally blank in `.env.example`.

```dotenv
SECMIND_LLM_PROVIDER=qwen
SECMIND_LLM_API_KEY=your-key-here
SECMIND_LLM_BASE_URL=https://ws-6a97xnb0sh5clxp6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
SECMIND_LLM_MODEL=qwen-plus
```

The mock orchestrator does not call the model yet. This config prepares the
provider for later LangGraph/agent integration without spending tokens during
framework tests.
