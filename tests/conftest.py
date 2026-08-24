"""Shared fixtures for the Epsilon test suite."""

import pytest

from epsilon.kernel.bootstrap import bootstrap
from epsilon.project import Session


@pytest.fixture(scope="session")
def kernel_env():
    """A freshly bootstrapped kernel environment (no standard library)."""
    return bootstrap()


@pytest.fixture(scope="session")
def stdlib_session():
    """A Session with the standard library loaded (reused; do not mutate)."""
    return Session()


@pytest.fixture()
def fresh_session():
    """A fresh Session for tests that add their own declarations."""
    return Session()
