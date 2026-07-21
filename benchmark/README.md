# SecMind Benchmark Harness

This directory keeps benchmark control code separate from application runtime state.

The harness enforces three boundaries:

1. Only `题目集_Agent可见/` is extracted and uploaded to SecMind.
2. Evaluator metadata stays in the source archive or the local control directory.
3. A case is purged only after its result and ledger are exported and hashed.

## Commands

Prepare and validate the 40-case fused dataset without calling a model:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py prepare `
  --archive "C:\path\to\融合测试集.zip"

..\venv\Scripts\python.exe benchmark\harness.py preflight
```

Run one static smoke case and purge its SecMind runtime records after export:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py smoke `
  --case-id BB-01 `
  --base-url http://127.0.0.1:15173 `
  --cleanup
```

If a terminal run is interrupted during export, recover the same run without another model call:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py recover `
  --experiment-id <experiment-id> `
  --case-id BB-01 `
  --run-id <run-uuid> `
  --upload-ref <upload-ref> `
  --cleanup
```

The first `BB-01` run is a pipeline smoke test and always records
`score_status=SMOKE_NOT_SCORED`. It is not a formal fused-suite score.

Run the fixed 12-case current-system baseline sequentially. Every case is
exported and purged before the next case starts:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py baseline `
  --selection benchmark\selections\fused-12-v1.json
```

Score an exported baseline locally. Private answers are used only for exact
matching and are never written to the evaluation output:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py evaluate-baseline `
  --experiment-id <baseline-experiment-id> `
  --archive "C:\path\to\融合测试集.zip"
```

Runtime artifacts are written under `benchmark/.state/` and are intentionally ignored by Git.
The API key is never read or persisted by this harness.

## Isolated current-source backend

Build and start the benchmark backend without replacing the normal SecMind images or volumes:

```powershell
docker compose -f compose.benchmark.yaml up -d --build
docker compose -f compose.benchmark.yaml exec backend python -c `
  "from agents.langgraph_runtime import LangGraphRuntime as G; print([n for n in ('collaborate','secondary_review','completion_gate') if n in G.NODE_NAMES])"
```

The isolated API listens on `http://127.0.0.1:18100` by default. Use that URL for harness
commands. Its image is `secmind-backend:benchmark-current` and its persistent volume is
`secmind_benchmark_data`; neither name overlaps the regular `secmind` Compose project.
