from typing import Protocol, TypeVar

T = TypeVar("T")


class InferenceProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def is_local(self) -> bool: ...

    def generate_text(self, prompt: str) -> str: ...

    def generate_structured(self, prompt: str, schema: type[T]) -> T: ...

    def healthcheck(self) -> dict: ...

