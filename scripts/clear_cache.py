#!/usr/bin/env python3
"""
Clear lightkurve cache completely
"""

import shutil
from pathlib import Path

cache_dir = Path.home() / ".lightkurve" / "cache"

if cache_dir.exists():
    print(f"Removing cache: {cache_dir}")
    shutil.rmtree(cache_dir)
    print("✅ Cache cleared!")
else:
    print("No cache found.")
