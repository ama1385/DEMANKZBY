from typing import Protocol


class Auth(Protocol):
    def token(self) -> str: ...
