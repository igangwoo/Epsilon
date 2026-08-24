"""Running Python and C++ — the languages a piece of mathematics turns into.

Execution here is real: a fresh interpreter or a real compiler, in a
subprocess, with a timeout and an output cap. Nothing in this package is
part of the trusted kernel, and nothing here can mark a result proven.
"""

from .runner import RunResult, run_code, available_languages  # noqa: F401
