"""SIFT's interactive terminal interface (package façade)."""

from .app import SiftApp
from .cli import build_parser, main

__all__ = ["SiftApp", "build_parser", "main"]
