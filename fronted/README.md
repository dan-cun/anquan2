# SecMind Frontend

The frontend contains the Three.js visual entry and the operational SecMind
agent collaboration workbench. The workbench consumes the existing REST,
WebSocket, replay, approval, audit-ledger, and model-configuration contracts.

The runtime collaboration map is derived from LangGraph node events. The full
backend reproduction scope and remaining specialist-agent work are documented
in `../docs/pentagi-core-reproduction.md`.

## Run

```bash
npm install
npm run dev
```

The browser uses same-origin `/api` and `/ws` routes by default. During local
development Vite proxies both routes to `http://127.0.0.1:8000`. Override the
development target when needed:

```bash
VITE_DEV_BACKEND_TARGET=http://localhost:9000 npm run dev
```

For deployments, configure Nginx to proxy `/api` and `/ws` to the FastAPI
service. `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` remain available when the
backend must be hosted on a separate origin.

Run the connection and replay checks with:

```bash
npm test
```

Model assets are served from `public/model`, and Draco decoders are served from
`public/draco`.
