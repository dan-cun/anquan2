from __future__ import annotations

from typing import Any

import ormsgpack


class CheckpointSerializationError(TypeError):
    pass


def checkpoint_roundtrip(value: dict[str, Any]) -> dict[str, Any]:
    """Fail before checkpoint persistence if graph state is not msgpack-safe."""

    try:
        restored = ormsgpack.unpackb(ormsgpack.packb(value))
    except (TypeError, ValueError) as error:
        raise CheckpointSerializationError(
            f"Graph state is not msgpack serializable: {type(error).__name__}"
        ) from error
    if not isinstance(restored, dict) or restored != value:
        raise CheckpointSerializationError("Graph state changed during msgpack roundtrip")
    return restored
