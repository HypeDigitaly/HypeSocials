"""Shared pytest fixtures for the HypeSocials suite.

pytest-asyncio runs in ``asyncio_mode = "auto"`` (configured once in
``pyproject.toml`` under ``[tool.pytest.ini_options]``), so bare ``async def
test_*`` functions are collected without an ``@pytest.mark.asyncio`` marker.
Keep the mode setting in pyproject only — a second declaration here would be
drift.

Fixtures land here as the waves add them (temp run dirs, fake config, fake
clock). Nothing is needed yet at scaffold time.
"""
