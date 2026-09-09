"""Normalized identities and public errors; no I/O."""
from dataclasses import asdict, dataclass
from typing import Any


class InputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Identity:
    group: str
    kind: str
    name: str
    namespace: str | None

    def report(self) -> dict:
        return asdict(self)


@dataclass
class Resource:
    identity: Identity
    api_version: str
    events: tuple[str, ...]
    weight: int
    delete_policies: tuple[str, ...]
    source: dict
    body: dict[str, Any]

    def report(self) -> dict:
        return {
            "identity": self.identity.report(), "api_version": self.api_version,
            "events": list(self.events), "phase": "hook" if self.events else "main",
            "weight": self.weight if self.events else None,
            "delete_policies": list(self.delete_policies), "source": self.source,
        }
