"""Production workflow utilities for E3-seeded DeepClust analysis."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("e3-discovery-engine-m1")
except PackageNotFoundError:
    __version__ = "0.1.3"

__all__ = ["__version__"]
