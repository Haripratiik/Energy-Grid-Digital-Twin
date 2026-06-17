"""Ensures the backend package root is importable when running pytest.

pytest inserts the directory containing this conftest onto sys.path, so tests
can ``import physics``, ``import decisions`` etc. exactly as the app does.
"""
