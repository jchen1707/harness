"""The application entry point.

`uvicorn api.main:app` serves this; `harness.config.json` names that command under `dev.run`
so `/run` starts it without knowing anything about this stack.
"""

from fastapi import FastAPI

from api.health import Health, health

app = FastAPI(title="__PROJECT__")


@app.get("/healthz")
def healthz() -> Health:
    """Liveness probe. The shape is `packages/contracts/openapi.yaml`'s `Health`."""
    return health()
