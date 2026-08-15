from collections.abc import Callable
from dataclasses import dataclass

from .base import BaseChatProvider
from .exceptions import ProviderAlreadyRegisteredError, ProviderNotFoundError
from .schemas import ProviderDescriptor

ProviderFactory = Callable[[], BaseChatProvider]
ProviderConfigurationCheck = Callable[[], bool]


@dataclass(frozen=True)
class ProviderRegistration:
    factory: ProviderFactory
    descriptor: ProviderDescriptor
    configuration_check: ProviderConfigurationCheck

class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(
        self,
        name: str,
        factory: ProviderFactory,
        *,
        replace: bool = False,
        descriptor: ProviderDescriptor | None = None,
        configuration_check: ProviderConfigurationCheck | None = None,
    ) -> None:
        if name in self._factories and not replace:
            raise ProviderAlreadyRegisteredError(f"Provider already registered: {name}")
        resolved_descriptor = descriptor or ProviderDescriptor(name=name)
        if resolved_descriptor.name != name:
            raise ValueError("Provider descriptor name must match registration name.")
        resolved_check = configuration_check or (lambda: True)
        self._factories[name] = factory
        self._registrations[name] = ProviderRegistration(
            factory=factory,
            descriptor=resolved_descriptor,
            configuration_check=resolved_check,
        )

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

    def describe(self, name: str) -> ProviderDescriptor:
        try:
            return self._registrations[name].descriptor
        except KeyError as exc:
            raise ProviderNotFoundError(f"Provider not found: {name}") from exc

    def configured(self, name: str) -> bool:
        try:
            check = self._registrations[name].configuration_check
        except KeyError as exc:
            raise ProviderNotFoundError(f"Provider not found: {name}") from exc
        try:
            return bool(check())
        except Exception:
            return False
