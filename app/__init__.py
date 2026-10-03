"""Tagwerk: a self-hosted music library manager."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tagwerk")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "0.0.0-dev"
