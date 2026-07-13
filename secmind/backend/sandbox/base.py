from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class SandboxCommand(BaseModel):
    command: str
    cwd: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=10800)


class SandboxResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class SandboxBackend(ABC):
    name: str

    @abstractmethod
    async def run(self, command: SandboxCommand) -> SandboxResult:
        """Run a command in an isolated environment."""


class DisabledSandbox(SandboxBackend):
    name = "disabled"

    async def run(self, command: SandboxCommand) -> SandboxResult:
        return SandboxResult(
            exit_code=127,
            stdout="",
            stderr="Sandbox backend is not configured.",
        )

