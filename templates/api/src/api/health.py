"""Liveness, as a domain function rather than as a route.

The route is one line of HTTP plumbing; this is the thing worth testing. Keeping them apart
is what lets the test suite assert behaviour without standing up a server.
"""

from typing import Literal, TypedDict


class Health(TypedDict):
    """The response body `/healthz` returns. Mirrors `Health` in the contract."""

    status: Literal["ok"]


def health() -> Health:
    """The service is running and able to answer."""
    return {"status": "ok"}
