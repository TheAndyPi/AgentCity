class DomainError(Exception):
    def __init__(
        self, code: str, message: str, status: int = 409, field: str | None = None, reason: str | None = None
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = [] if reason is None else [{"field": field, "reason": reason}]


def require(
    condition,
    code="INVALID_STATE",
    message="Operation is not allowed in the current state",
    status=409,
    **kwargs,
):
    if not condition:
        raise DomainError(code, message, status, **kwargs)
