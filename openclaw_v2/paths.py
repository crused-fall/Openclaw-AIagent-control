from __future__ import annotations

import ntpath
import os
import posixpath


def _is_posix_absolute(path: str) -> bool:
    return posixpath.isabs(path)


def _looks_like_windows_path(path: str) -> bool:
    drive, _ = ntpath.splitdrive(path)
    return bool(drive) or path.startswith("\\") or path.startswith("//") or "\\" in path


def normalize_runtime_path(path: str) -> str:
    if _is_posix_absolute(path):
        return path.replace("\\", "/")
    if _looks_like_windows_path(path):
        return path.replace("/", "\\")
    return path


def is_absolute_runtime_path(path: str) -> bool:
    return _is_posix_absolute(path) or ntpath.isabs(path)


def join_runtime_path(base_path: str, *parts: str) -> str:
    normalized_base = normalize_runtime_path(base_path)
    if not parts:
        return normalized_base

    if _is_posix_absolute(normalized_base):
        normalized_parts = [part.replace("\\", "/") for part in parts]
        return posixpath.join(normalized_base, *normalized_parts)

    if _looks_like_windows_path(normalized_base):
        normalized_parts = [part.replace("/", "\\") for part in parts]
        return ntpath.join(normalized_base, *normalized_parts)

    return os.path.join(normalized_base, *parts)
