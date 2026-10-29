"""Byte-bounded LRU of finished HTTP responses."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable


class ResponseCache:
    def __init__(self, max_bytes: int) -> None:
        self._max = max_bytes
        self._size = 0
        self._items: OrderedDict[Hashable, tuple[bytes, dict[str, str]]] = OrderedDict()

    def get(self, key: Hashable) -> tuple[bytes, dict[str, str]] | None:
        item = self._items.get(key)
        if item is not None:
            self._items.move_to_end(key)
        return item

    def put(self, key: Hashable, body: bytes, headers: dict[str, str]) -> None:
        if len(body) > self._max // 8:
            return  # never let one response dominate the cache
        if key in self._items:
            self._size -= len(self._items.pop(key)[0])
        self._items[key] = (body, headers)
        self._size += len(body)
        while self._size > self._max:
            _, (old, _) = self._items.popitem(last=False)
            self._size -= len(old)

    def __len__(self) -> int:
        return len(self._items)
