"""Top-level package exports for ai_deney."""

from __future__ import annotations

__all__: list[str] = []

try:
    from .random_cropping import random_crop_bchw, random_crop_chw, random_crop_pair

    __all__.extend(["random_crop_chw", "random_crop_bchw", "random_crop_pair"])
except Exception:
    # Keep package importable in environments without optional heavy deps (e.g. torch).
    pass
