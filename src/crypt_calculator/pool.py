from __future__ import annotations

from dataclasses import dataclass, field

MAX_POOL_SIZE = 10


@dataclass
class Pool:
    names: list[str] = field(default_factory=lambda: [f"Card {i}" for i in range(MAX_POOL_SIZE)])

    def __post_init__(self) -> None:
        if len(self.names) > MAX_POOL_SIZE:
            raise ValueError(f"Pool can have at most {MAX_POOL_SIZE} names (got {len(self.names)})")
        if len(set(self.names)) != len(self.names):
            raise ValueError("Pool names must be unique")

    def index(self, name: str) -> int:
        return self.names.index(name)

    def has(self, name: str) -> bool:
        return name in self.names

    def size(self) -> int:
        return len(self.names)
