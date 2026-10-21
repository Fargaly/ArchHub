"""Process-local, verified first-use registry indexes; never persisted truth.

Factories retain the existing graph projectors and migrations. A failed read is
not memoized and no value is exposed before the complete factory succeeds.
"""
from collections.abc import Mapping
from threading import RLock


class DeferredRegistryGroup:
    def __init__(self, factory):
        self.factory = factory
        self._values = None
        self._lock = RLock()

    def get(self, name):
        with self._lock:
            if self._values is None:
                values = self.factory()
                self._values = values
                self.factory = None
            return self._values[name]

    def field(self, name):
        return DeferredRegistryField(self, name)


class DeferredRegistryField:
    def __init__(self, group, name):
        self.group, self.name = group, name

    def resolve(self):
        return self.group.get(self.name)


class VerifiedLazyRegistry:
    """Resolve deferred fields without changing callers' public value types."""
    __slots__ = ()

    def __getattribute__(self, name):
        value = object.__getattribute__(self, name)
        if isinstance(value, DeferredRegistryField):
            return value.resolve()
        return value


class VerifiedLazyMapping(Mapping):
    """A per-key index whose misses use the original verified graph reader."""
    def __init__(self, initial, loader, keys=None):
        self._values = dict(initial)
        self._loader = loader
        self._keys = keys
        self._lock = RLock()
        self._pending = {}
        self._generation = 0

    def __getitem__(self, key):
        with self._lock:
            if key in self._values:
                return self._values[key]
            pending = self._pending.get(key)
            if pending is None:
                pending = [RLock(), 0]
                self._pending[key] = pending
            pending[1] += 1
        try:
            # A key's verified loader may enter another scope/index. Keep the
            # shared inventory lock free; only same-key readers wait here.
            with pending[0]:
                while True:
                    with self._lock:
                        if key in self._values:
                            return self._values[key]
                        generation = self._generation
                    value = self._loader(key)
                    with self._lock:
                        # Provisioning can publish a newer verified view while
                        # this loader is running. Its published value wins.
                        if key in self._values:
                            return self._values[key]
                        if generation != self._generation:
                            continue
                        self._values[key] = value
                        return value
        finally:
            with self._lock:
                pending[1] -= 1
                if pending[1] == 0:
                    self._pending.pop(key, None)

    def __iter__(self):
        keys = tuple(self._keys()) if self._keys is not None else ()
        with self._lock:
            return iter(tuple(dict.fromkeys((*self._values, *keys))))

    def __len__(self):
        return sum(1 for _ in self)

    def loaded_values(self):
        with self._lock:
            return tuple(self._values.values())

    def invalidate(self):
        with self._lock:
            self._values.clear()
            self._generation += 1


class VerifiedLazyViews(VerifiedLazyMapping):
    """Retain the existing provisioner's mutable, verified view index."""
    def __setitem__(self, key, value):
        with self._lock:
            self._values[key] = value
