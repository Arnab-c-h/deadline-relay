from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

Record = dict[str, Any]
Snapshot = dict[str, Any]


class ProviderError(RuntimeError):
    VALID_KINDS: ClassVar[set[str]] = {"transient", "uncertain", "stale", "permanent", "auth"}

    def __init__(self, message: str, *, kind: str = "permanent", retry_after: float = 0):
        if kind not in self.VALID_KINDS:
            raise ValueError(f"Invalid provider error kind: {kind}")
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


class Provider(ABC):
    @abstractmethod
    def snapshot(self) -> Snapshot: ...

    @abstractmethod
    def read(self, record_key: str) -> Record: ...

    @abstractmethod
    def write(self, record_key: str, changes: dict[str, Any], etag: str | None = None) -> None: ...

    @abstractmethod
    def health(self) -> list[dict[str, str]]: ...
