"""Cscape Project Package.

Legacy adapter interface delegating cleanly to src.cscape without Straton K5 dependencies.
"""
from .manager import CscapeProject, POUInfo

__all__ = ["CscapeProject", "POUInfo"]
