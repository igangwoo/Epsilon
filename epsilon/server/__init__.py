"""The Epsilon web server: a FastAPI backend for the web IDE.

The REST API is defined in ``docs/CONTRACTS.md`` (Server REST API section)
and consumed by the vanilla-JS frontend in ``epsilon/server/static``. Every
response is derived from the shared ``epsilon.project.Session`` pipeline.
"""

from .app import app, create_app

__all__ = ["app", "create_app"]
