from __future__ import annotations

import asyncio
import datetime
import enum
import logging
import time
from functools import wraps
from typing import Any, Callable, Coroutine, Mapping, MutableMapping, Optional, Protocol, TypeVar

from aiohttp import ClientSession
from lru import LRU

from .bases.errors import SomethingWentWrong

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

R = TypeVar("R")


class KeysCache:
    """KeysCache

    This class caches the data from public json-urls
    for a certain amount of time just so we have somewhat up-to-date data
    and don't spam GET requests too often.
    """

    def __init__(self) -> None:
        self.cached_data: dict[Any, Any] = {}
        self.lock: asyncio.Lock = asyncio.Lock()
        self.last_updated: datetime.datetime = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)

    async def get_response_json(self, url: str) -> Any:
        """Get response.json() from url with data"""
        async with ClientSession() as session:
            async with session.get(url) as response:
                if response.ok:
                    return await response.json()

            # response not ok
            if any(self.cached_data.values()):
                # let's hope that the previously cached data is still fine
                return self.cached_data
            else:
                status = response.status
                response_text = await response.text()
                log.debug(f"Key Cache response error: %s %s", status, response_text)
                raise SomethingWentWrong(f"Key Cache response error: {status} {response_text}")

    async def fill_data(self) -> dict:
        """Fill self.cached_data with the data from various json data"""
        ...

    @property
    def need_updating(self) -> bool:
        return datetime.datetime.now(datetime.timezone.utc) - self.last_updated < datetime.timedelta(hours=6)

    async def get_data(self, force_update: bool = False) -> dict[Any, Any]:
        """Get data and update the cache if needed"""
        if self.need_updating and not force_update:
            return self.cached_data

        async with self.lock:
            if self.need_updating and not force_update:
                return self.cached_data

            self.cached_data = await self.fill_data()
            self.last_updated = datetime.datetime.now(datetime.timezone.utc)
        return self.cached_data

    async def get(self, cache: str, key: Any, default: Optional[Any] = None) -> Any:
        """Get a key value from cache"""
        data = await self.get_data()
        try:
            log.debug("KeyCache item %s %s %s", cache, key, data[cache].get(key)) # todo: comment
            return data[cache].get(key)
        except KeyError:
            # let's try to update cache in case it's a new patch
            # and hope the data is up-to-date in those json-files elsa return default
            data = await self.get_data(force_update=True)

            try:
                return data[cache].get(key)
            except KeyError:
                if default:
                    return default
                else:
                    raise

    async def get_value_or_none(self, cache: str, key: Any) -> Any:
        """Get a key value from cache"""
        data = await self.get_data()
        return data[cache].get(key, None)


# Can't use ParamSpec due to https://github.com/python/typing/discussions/946
class CacheProtocol(Protocol[R]):
    cache: MutableMapping[str, asyncio.Task[R]]

    def __call__(self, *args: Any, **kwds: Any) -> asyncio.Task[R]:
        ...

    def get_key(self, *args: Any, **kwargs: Any) -> str:
        ...

    def invalidate(self, *args: Any, **kwargs: Any) -> bool:
        ...

    def invalidate_containing(self, key: str) -> None:
        ...

    def get_stats(self) -> tuple[int, int]:
        ...


class ExpiringCache(dict):
    def __init__(self, seconds: float):
        self.__ttl: float = seconds
        super().__init__()

    def __verify_cache_integrity(self):
        # Have to do this in two steps...
        current_time = time.monotonic()
        to_remove = [k for (k, (v, t)) in super().items() if current_time > (t + self.__ttl)]
        for k in to_remove:
            del self[k]

    def get(self, key: str, default: Any = None):
        v = super().get(key, default)
        if v is default:
            return default
        return v[0]

    def __contains__(self, key: str):
        self.__verify_cache_integrity()
        return super().__contains__(key)

    def __getitem__(self, key: str):
        self.__verify_cache_integrity()
        v, _ = super().__getitem__(key)
        return v

    def __setitem__(self, key: str, value: Any):
        super().__setitem__(key, (value, time.monotonic()))

    def values(self):
        return map(lambda x: x[0], super().values())

    def items(self):
        return map(lambda x: (x[0], x[1][0]), super().items())


class Strategy(enum.Enum):
    lru = 1
    raw = 2
    timed = 3


def cache(
    maxsize: int = 128,
    strategy: Strategy = Strategy.lru,
    ignore_kwargs: bool = False,
) -> Callable[[Callable[..., Coroutine[Any, Any, R]]], CacheProtocol[R]]:
    def decorator(func: Callable[..., Coroutine[Any, Any, R]]) -> CacheProtocol[R]:
        if strategy is Strategy.lru:
            _internal_cache = LRU(maxsize)
            _stats = _internal_cache.get_stats
        elif strategy is Strategy.raw:
            _internal_cache = {}
            _stats = lambda: (0, 0)
        elif strategy is Strategy.timed:
            _internal_cache = ExpiringCache(seconds=maxsize)
            _stats = lambda: (0, 0)

        def _make_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
            # this is a bit of a cluster fuck
            # we do care what 'self' parameter is when we __repr__ it
            def _true_repr(o):
                if o.__class__.__repr__ is object.__repr__:
                    return f"<{o.__class__.__module__}.{o.__class__.__name__}>"
                return repr(o)

            key = [f"{func.__module__}.{func.__name__}"]
            key.extend(_true_repr(o) for o in args)
            if not ignore_kwargs:
                for k, v in kwargs.items():
                    # note: this only really works for this use case in particular
                    # I want to pass asyncpg.Connection objects to the parameters
                    # however, they use default __repr__ and I do not care what
                    # connection is passed in, so I needed a bypass.
                    if k == "connection" or k == "pool":
                        continue

                    key.append(_true_repr(k))
                    key.append(_true_repr(v))

            return ":".join(key)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            key = _make_key(args, kwargs)
            try:
                task = _internal_cache[key]
            except KeyError:
                _internal_cache[key] = task = asyncio.create_task(func(*args, **kwargs))
                return task
            else:
                return task

        def _invalidate(*args: Any, **kwargs: Any) -> bool:
            try:
                del _internal_cache[_make_key(args, kwargs)]
            except KeyError:
                return False
            else:
                return True

        def _invalidate_containing(key: str) -> None:
            to_remove = []
            for k in _internal_cache.keys():
                if key in k:
                    to_remove.append(k)
            for k in to_remove:
                try:
                    del _internal_cache[k]
                except KeyError:
                    continue

        # TODO: investigate those # type: ignore
        wrapper.cache = _internal_cache  # type: ignore
        wrapper.get_key = lambda *args, **kwargs: _make_key(args, kwargs)  # type: ignore
        wrapper.invalidate = _invalidate  # type: ignore
        wrapper.get_stats = _stats  # type: ignore
        wrapper.invalidate_containing = _invalidate_containing  # type: ignore
        return wrapper  # type: ignore

    return decorator
