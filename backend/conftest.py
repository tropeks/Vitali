"""
Root conftest.py — pytest hooks for the full test suite.

Fixes the "database test_vitali does not exist" cascade that occurs when
TenantTestCase.tearDownClass() drops the 'test' schema and leaves database
connections in a broken state for the next TenantTestCase class.

After each test class boundary we close all Django DB connections so every
new TenantTestCase.setUpClass() opens a fresh connection to test_vitali.

We use hookwrapper=True so the yield defers to the normal teardown chain
(which includes tearDownClass / schema DROP) BEFORE we close connections.
"""

import pytest
from django.db import connections


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Close all DB connections at every test-class boundary, AFTER tearDownClass."""
    yield  # let tearDownClass (and all other teardown) run first

    current_cls = getattr(item, "cls", None)
    next_cls = getattr(nextitem, "cls", None) if nextitem else None

    if current_cls is not None and current_cls is not next_cls:
        connections.close_all()
