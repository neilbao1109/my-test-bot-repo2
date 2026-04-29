"""ClawFS - content-addressed filesystem."""
from .core import ClawFS
from .factory import make_storage

__version__ = "0.2.0"
__all__ = ["ClawFS", "make_storage"]
