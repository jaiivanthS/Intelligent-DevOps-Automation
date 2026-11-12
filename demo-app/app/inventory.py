"""A tiny in-memory inventory store standing in for a real database."""

from __future__ import annotations

import itertools
import threading

from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=0, le=1_000_000)
    price: float = Field(ge=0)


class Item(ItemIn):
    id: int


class DependencyUnavailable(RuntimeError):
    """Raised when the (simulated) inventory database cannot be reached."""


class InventoryStore:
    def __init__(self, seed: bool = True) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, Item] = {}
        self._ids = itertools.count(1)
        if seed:
            for name, qty, price in (
                ("widget", 120, 2.5),
                ("gadget", 40, 12.0),
                ("sprocket", 300, 0.75),
            ):
                self.create(ItemIn(name=name, quantity=qty, price=price))

    def list(self) -> list[Item]:
        with self._lock:
            return list(self._items.values())

    def get(self, item_id: int) -> Item | None:
        with self._lock:
            return self._items.get(item_id)

    def create(self, data: ItemIn) -> Item:
        with self._lock:
            item = Item(id=next(self._ids), **data.model_dump())
            self._items[item.id] = item
            return item

    def delete(self, item_id: int) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._items)
