"""Atomic file write helpers.

Provides atomic_write() which uses a temporary file + os.replace() to ensure
every target file is either the complete old version or the complete new version.
Partial writes (from crashes mid-write) are never visible to readers.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to path atomically using a temp file + os.replace().

    The target file is either unchanged (if an error occurs) or contains
    the complete new content.  A `.tmp` orphan may remain on crash but
    will never be read as the target file.

    Args:
        path: Destination file path.  Parent directory must exist or be
              creatable.
        content: Text content to write.
        encoding: File encoding (default: utf-8).

    Raises:
        OSError: If the temporary file cannot be written or renamed.
    """
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
