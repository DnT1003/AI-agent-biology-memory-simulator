"""Port of: src/tools/PowerShellTool/"""

POWERSHELL_TOOL_NAME = "PowerShell"

try:
    from hare.tools_impl.PowerShellTool.prompt import *  # noqa: F401,F403
except ImportError:
    pass
