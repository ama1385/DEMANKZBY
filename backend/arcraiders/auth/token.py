from functools import cache


class TokenAuth:
    def __init__(self, token: str) -> None:
        self._value = token

    @cache
    def token(self) -> str:
        return self._value
