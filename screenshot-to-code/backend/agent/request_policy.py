"""Explicit policy for bounded consumers; native Agent defaults stay unchanged."""
from dataclasses import dataclass, field
from typing import Callable


class RequestLimitError(Exception):
    pass


@dataclass
class RequestPolicy:
    limit: int
    before_request: Callable[[str, str], None] | None = None
    timeout: float = 180
    allowed_tools: frozenset[str] = frozenset({"create_file", "edit_file", "retrieve_option"})
    requests: int = field(default=0, init=False)

    def claim(self, provider: str, model: str) -> None:
        # No await between checking, durable reservation and local accounting.
        # The callback must atomically reserve the shared Run's remaining quota.
        if self.requests >= self.limit:
            raise RequestLimitError("Model request limit reached; no automatic retry.")
        if self.before_request is not None:
            self.before_request(provider, model)
        self.requests += 1
