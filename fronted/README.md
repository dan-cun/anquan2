# AULA Robot Hero

Minimal Three.js reproduction of the AULA Hub robot hero. It keeps the
full-screen dark stage, 3D robot model, environment reflection, camera intro,
and mouse-follow motion. The background logo and business UI are intentionally
omitted.

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
