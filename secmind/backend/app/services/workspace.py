from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ledger.runtime_store import RuntimeLedgerStore


class WorkspaceNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeWorkspaceResolver:
    ledger: RuntimeLedgerStore
    run_root: Path

    def resolve(self, run_id: str) -> Path:
        state = self.ledger.load_state(run_id)
        if state is None or not state.workspace:
            raise WorkspaceNotReadyError(f"Workspace is not ready for run {run_id}")
        workspace = Path(state.workspace).resolve()
        expected = (self.run_root.resolve() / run_id / "workspace").resolve()
        if workspace != expected:
            raise WorkspaceNotReadyError("Runtime state references an unexpected workspace path")
        if not workspace.is_dir() or workspace.is_symlink():
            raise WorkspaceNotReadyError("Runtime workspace is missing or unsafe")
        return workspace

    def scope(self, run_id: str) -> dict[str, object]:
        workspace = self.resolve(run_id)
        return {
            "workspace": str(workspace),
            "allowed_paths": [str(workspace)],
        }

    def context_refs(self, run_id: str) -> list[str]:
        state = self.ledger.load_state(run_id)
        if state is None:
            raise WorkspaceNotReadyError(f"Runtime state is missing for run {run_id}")
        self.resolve(run_id)
        root_ref = f"workspace://{quote(run_id, safe='')}/"
        refs = [root_ref, f"{root_ref}manifest"]
        refs.extend(
            f"{root_ref}{quote(item.relative_path, safe='/')}"
            for item in state.input_artifacts
        )
        return refs
