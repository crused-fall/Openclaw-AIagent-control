from __future__ import annotations

import asyncio
import re


def normalize_github_repo(remote_url: str) -> str:
    text = remote_url.strip()
    if not text:
        return ""

    patterns = [
        r"^git@github\.com:([^/\s]+)/([^/\s]+?)(?:\.git)?$",
        r"^https://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return ""


async def resolve_github_repo_from_origin(repo_path: str) -> tuple[str, str, str]:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        "remote",
        "get-url",
        "origin",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    origin_url = stdout.decode("utf-8", errors="replace").strip()
    error_output = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        return "", origin_url, error_output
    return normalize_github_repo(origin_url), origin_url, error_output
