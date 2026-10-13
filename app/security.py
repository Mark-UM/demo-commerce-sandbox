from hmac import compare_digest

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.errors import SourceError

key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def authenticate(request: Request, key: str | None = Security(key_header)):
    expected = request.app.state.api_key
    if not expected:
        return
    if key is None:
        raise SourceError(401, "UNAUTHORIZED", "X-API-Key is required")
    if not compare_digest(key.encode(), expected.encode()):
        raise SourceError(403, "FORBIDDEN", "Invalid Sandbox API key")
