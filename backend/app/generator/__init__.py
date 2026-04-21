"""Sheet-music exercise generator – public API.

This package is a refactored version of the former monolithic generator.py.
External code should only import ``build_exercise``.
"""

from ._entry import build_exercise  # noqa: F401

__all__ = ["build_exercise"]
