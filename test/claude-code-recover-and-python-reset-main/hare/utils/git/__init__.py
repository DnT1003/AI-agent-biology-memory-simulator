"""Git utilities."""

from hare.utils.git.git_diff import compute_git_diff
from hare.utils.git.git_status import get_git_status


async def find_git_root(cwd: str = "") -> str | None:
    """Find the git root directory."""
    import asyncio, os
    search = cwd or os.getcwd()
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--show-toplevel",
            cwd=search, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except Exception:
        pass
    return None
