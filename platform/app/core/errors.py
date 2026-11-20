from fastapi import HTTPException


class ApiError(HTTPException):
    """HTTP error with a stable machine-readable code for the apps to switch on."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
