"""Observation command boundary supplied by the composition root."""

from typing import Any, Protocol


class ObservationPort(Protocol):
    def record_observation(self, **kwargs: Any) -> dict[str, Any]:
        """Append through the observation owner's validated public use case."""
        ...
