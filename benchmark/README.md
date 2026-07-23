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
matching and are never written to the evaluation output. This also writes
`task-scores.jsonl`, `task-scores.csv`, and a deterministic `report.md` beside
`evaluation.json`:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py evaluate-baseline `
  --experiment-id <baseline-experiment-id> `
  --archive "C:\path\to\融合测试集.zip"
```

The report is valid only when all 12 selected case IDs have exactly one score
record. Cases without a connected deterministic evaluator are retained in the
denominator and marked `MANUAL_REVIEW_REQUIRED`; the resulting score is
provisional until those cases are reviewed or their private evaluator is
connected. The model never computes or changes benchmark scores.

Re-render an existing evaluation without reopening private evaluator data:

```powershell
..\venv\Scripts\python.exe benchmark\harness.py render-report `
  --evaluation benchmark\.state\results\<experiment-id>\evaluation.json
```

Runtime artifacts are written under `benchmark/.state/` and are intentionally ignored by Git.
The API key is never read or persisted by this harness.

## PentAGI target adapter

PentAGI can be used as the solver while this harness remains the private,
deterministic evaluator. Private answers and evaluator metadata must never be
copied into PentAGI, its containers, or its prompts.

Create a dedicated automation token in PentAGI under **Settings -> API Tokens**,
then put it only in the ignored `benchmark/pentagi.env` file:

```text
PENTAGI_BASE_URL=https://127.0.0.1:8443
PENTAGI_PROVIDER=deepseek
PENTAGI_API_TOKEN=<dedicated-token>
PENTAGI_TLS_VERIFY=false
```

`PENTAGI_TLS_VERIFY=false` is accepted only for the current loopback-only,
self-signed deployment. Use a CA bundle path instead for any non-loopback
deployment.

Check connectivity, authentication, and provider availability:

```powershell
..\venv\Scripts\python.exe -m benchmark.pentagi_adapter preflight
```

Each PentAGI case must finish with one Task whose complete `result` is a JSON
object in this shape. A flag appearing in prose, logs, tool calls, or another
field is intentionally not accepted:

```json
{
  "final_answer": "exact answer or flag",
  "evidence": [],
  "findings": [],
  "reproduction_steps": []
}
```

Normalize a completed PentAGI Flow into the existing score input layout:

```powershell
..\venv\Scripts\python.exe -m benchmark.pentagi_adapter export-flow `
  --flow-id <pentagi-flow-id> `
  --case-id CY-WEB-01 `
  --experiment-id baseline-fused-12-pentagi-<timestamp>
```

Or let the adapter upload the public archives and run all 12 cases sequentially:

```powershell
..\venv\Scripts\python.exe -m benchmark.pentagi_adapter baseline `
  --selection benchmark\selections\fused-12-v1.json `
  --timeout-seconds 1800 `
  --cleanup
```

The baseline command creates a deterministic failure record for every failed or
timed-out case, so all 12 selected IDs remain in the score denominator. After
the run, pass the returned experiment ID to `evaluate-baseline`. PentAGI never
receives the private archive; only the evaluator process opens it while
calculating scores.

### PentAGI DOCX diagnostic report

After `evaluate-baseline` writes `evaluation.json`, generate a decision report
from the deterministic score and the exported `round-1` records:

```powershell
python benchmark\pentagi_docx_report.py `
  --evaluation benchmark\.state\results\<experiment-id>\evaluation.json `
  --template-docx "C:\path\to\reference-report.docx" `
  --output benchmark\.state\results\<experiment-id>\PentAGI-跑分诊断报告.docx
```

The report generator requires `python-docx` and Pillow. In Codex document
workflows, invoke it with the bundled workspace Python runtime. The generator
checks the per-case export target and refuses to label unlabeled or non-PentAGI
data as a PentAGI report. `--preview` exists only for structural testing and
adds a visible non-PentAGI warning to the cover.

The DOCX includes the fixed-suite score, eight-category view, per-case table,
runtime/evidence diagnostics, deterministic remediation priorities, and
provenance. It never reads or exports private answers and cannot change a score.

PentAGI currently cannot prove removal of its residual flow data directory and
does not provide a hash-chained decision ledger. The adapter records those
limitations instead of awarding the corresponding cleanup or decision-log
points.

## Unified immutable backend and isolated data

Online and benchmark backends use the same commit-tagged image, shared read-only MCP definition,
shared non-secret model profile, and shared local secret file. Their data remains isolated:
online uses PostgreSQL and benchmark uses its own SQLite volume.

After committing all intended changes, build and deploy both backends with one command:

```powershell
Copy-Item benchmark\runtime.env.example benchmark\runtime.env
# Edit benchmark/runtime.env and set the local model API key.
.\scripts\Deploy-UnifiedRuntime.ps1 -Target Both
```

The deployment script refuses a dirty worktree, builds one
`secmind-backend:git-<commit>` image, obtains its immutable `sha256:` image ID, and recreates
both backend services with `--no-build --force-recreate`. It writes the ignored provenance
manifest to `benchmark/.state/deployment.json` only after both deployments become healthy.

Validate the benchmark runtime without a model call:

```powershell
docker compose -f compose.benchmark.yaml exec backend python -c `
  "from agents.langgraph_runtime import LangGraphRuntime as G; print([n for n in ('collaborate','secondary_review','completion_gate') if n in G.NODE_NAMES])"
..\venv\Scripts\python.exe benchmark\harness.py preflight `
  --base-url http://127.0.0.1:18100
```

The isolated API listens on `http://127.0.0.1:18100` by default. Its persistent volume is
`secmind_benchmark_data`; it does not overlap the regular `secmind` Compose project or its
PostgreSQL data.

Both Compose files load non-secret model settings from `config/model-public.env`, the model key
from ignored `benchmark/runtime.env`, and mount `config/mcp-servers.json` read-only. The common MCP
catalog expects Fetch, Chrome DevTools, Web Security, and CyberChef on host ports 9011-9014.

Preflight validates the exact seven Server IDs, all-connected state, 88 unified tools
(10 native and 78 MCP), runtime image ID, source commit, clean Git state, and the deployment
manifest. It also records SHA-256 summaries for the Prompt workbook, public model profile, MCP
definition, and live tool definitions. Real benchmark execution defaults to demo mode off; any
failed provenance check or missing model key blocks the static smoke run.
