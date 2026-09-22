from fastapi import Request


class SourceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def store(request: Request):
    return request.app.state.store


def require(request: Request, collection: str, key: str, code: str):
    rows = store(request).get(collection, key)
    if not rows:
        raise SourceError(404, code, f"Record {key} was not found")
    return rows[0]
