from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.schemas.runtime import CircuitState


class CircuitBreakerOpenError(RuntimeError):
    def __init__(self, key: str, retry_after_seconds: float) -> None:
        self.key = key
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"Circuit {key} is open; retry after {self.retry_after_seconds:.3f} seconds"
        )


@dataclass(frozen=True, slots=True)
class CircuitTransition:
    key: str
    previous_state: CircuitState
    state: CircuitState
    reason: str


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    key: str
    state: CircuitState
    failure_count: int
    retry_after_seconds: float


@dataclass(slots=True)
class _Circuit:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    opened_at: float | None = None
    probe_in_flight: bool = False


class CircuitBreakerRegistry:
    """Concurrency-safe circuit breakers shared by tool and MCP server keys."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if reset_timeout_seconds <= 0:
            raise ValueError("reset_timeout_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._clock = clock
        self._circuits: dict[str, _Circuit] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, keys: Iterable[str]) -> list[CircuitTransition]:
        normalized = tuple(dict.fromkeys(keys))
        now = self._clock()
        async with self._lock:
            for key in normalized:
                circuit = self._circuits.setdefault(key, _Circuit())
                retry_after = self._retry_after(circuit, now)
                if circuit.state == CircuitState.OPEN and retry_after > 0:
                    raise CircuitBreakerOpenError(key, retry_after)
                if circuit.state == CircuitState.HALF_OPEN and circuit.probe_in_flight:
                    raise CircuitBreakerOpenError(key, self.reset_timeout_seconds)

            transitions: list[CircuitTransition] = []
            for key in normalized:
                circuit = self._circuits[key]
                if circuit.state == CircuitState.OPEN:
                    previous = circuit.state
                    circuit.state = CircuitState.HALF_OPEN
                    circuit.probe_in_flight = True
                    transitions.append(
                        CircuitTransition(key, previous, circuit.state, "cooldown_elapsed")
                    )
                elif circuit.state == CircuitState.HALF_OPEN:
                    circuit.probe_in_flight = True
            return transitions

    async def record_success(self, keys: Iterable[str]) -> list[CircuitTransition]:
        async with self._lock:
            transitions: list[CircuitTransition] = []
            for key in dict.fromkeys(keys):
                circuit = self._circuits.setdefault(key, _Circuit())
                previous = circuit.state
                circuit.state = CircuitState.CLOSED
                circuit.failure_count = 0
                circuit.opened_at = None
                circuit.probe_in_flight = False
                if previous != CircuitState.CLOSED:
                    transitions.append(
                        CircuitTransition(key, previous, circuit.state, "probe_succeeded")
                    )
            return transitions

    async def record_failure(self, keys: Iterable[str]) -> list[CircuitTransition]:
        now = self._clock()
        async with self._lock:
            transitions: list[CircuitTransition] = []
            for key in dict.fromkeys(keys):
                circuit = self._circuits.setdefault(key, _Circuit())
                previous = circuit.state
                circuit.failure_count += 1
                circuit.probe_in_flight = False
                if (
                    previous == CircuitState.HALF_OPEN
                    or circuit.failure_count >= self.failure_threshold
                ):
                    circuit.state = CircuitState.OPEN
                    circuit.opened_at = now
                    if previous != CircuitState.OPEN:
                        transitions.append(
                            CircuitTransition(key, previous, circuit.state, "failure_threshold")
                        )
            return transitions

    async def record_cancelled(self, keys: Iterable[str]) -> list[CircuitTransition]:
        now = self._clock()
        async with self._lock:
            transitions: list[CircuitTransition] = []
            for key in dict.fromkeys(keys):
                circuit = self._circuits.setdefault(key, _Circuit())
                if circuit.state == CircuitState.HALF_OPEN:
                    previous = circuit.state
                    circuit.state = CircuitState.OPEN
                    circuit.opened_at = now
                    circuit.probe_in_flight = False
                    transitions.append(
                        CircuitTransition(key, previous, circuit.state, "probe_cancelled")
                    )
            return transitions

    async def snapshot(self, key: str) -> CircuitSnapshot:
        now = self._clock()
        async with self._lock:
            circuit = self._circuits.setdefault(key, _Circuit())
            return CircuitSnapshot(
                key=key,
                state=circuit.state,
                failure_count=circuit.failure_count,
                retry_after_seconds=self._retry_after(circuit, now),
            )

    def _retry_after(self, circuit: _Circuit, now: float) -> float:
        if circuit.state != CircuitState.OPEN or circuit.opened_at is None:
            return 0.0
        return max(0.0, self.reset_timeout_seconds - (now - circuit.opened_at))
