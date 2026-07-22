from collections.abc import Callable
from .base import BaseChatProvider
from .exceptions import ProviderAlreadyRegisteredError, ProviderNotFoundError

ProviderFactory = Callable[[], BaseChatProvider]

class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, name: str, factory: ProviderFactory, *, replace: bool = False) -> None:
        if name in self._factories and not replace:
            raise ProviderAlreadyRegisteredError(f"Provider already registered: {name}")
        self._factories[name] = factory

    def get(self, name: str) -> BaseChatProvider:
        try:
            factory = self._factories[name]
        except KeyError as exc:
            available = ", ".join(self.list())
            raise ProviderNotFoundError(
                f"Provider not found: {name}. Available: {available}"
            ) from exc
        return factory()

    def list(self) -> list[str]:
        return sorted(self._factories)

    def contains(self, name: str) -> bool:
        return name in self._factories
