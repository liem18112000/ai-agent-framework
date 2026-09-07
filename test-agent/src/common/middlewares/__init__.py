"""Starlette middlewares for the A2A server."""

from common.middlewares.auth import BearerAuthMiddleware

__all__ = ["BearerAuthMiddleware"]
