from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml


def kebab_slug(value: str) -> str:
    lowered = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered)
    return cleaned.strip("-")
