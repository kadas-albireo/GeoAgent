"""A bare terminal tool: run a shell command.

Exposes one capability to the agent — run a shell command via a subprocess and
return its exit code and raw output. It makes no attempt to classify the command
or steer the agent: for in-QGIS work the agent already has
``run_processing_algorithm`` and ``run_pyqgis_script``; it reaches for the
terminal when it needs an external program (``gdalwarp``, ``ogr2ogr``, ...).

``run_command`` is metadata-flagged ``destructive`` so it always flows through
the host confirmation callback before a subprocess is spawned. It depends only
on the standard library.
"""

from __future__ import annotations

import os
import shlex
import subprocess  # noqa: S404 - confirmation-gated command execution.
from typing import Any, Optional

from geoagent.core.decorators import geo_tool


def terminal_tools() -> list[Any]:
    """Return the terminal tool set: a single ``run_command`` runner."""

    @geo_tool(
        category="terminal",
        requires_confirmation=True,
        destructive=True,
        long_running=True,
    )
    def run_command(
        command: str, timeout_seconds: Optional[int] = None
    ) -> dict[str, Any]:
        """Run a shell command and return its exit code and output.

        Use this for external programs not covered by a QGIS tool, e.g. the
        GDAL/OGR command-line utilities (``gdalwarp``, ``ogr2ogr``). For QGIS
        processing algorithms prefer ``run_processing_algorithm``; for PyQGIS
        prefer ``run_pyqgis_script``. Always requires user confirmation.

        Args:
            command: The exact shell command to run.
            timeout_seconds: Optional timeout; ``None`` waits indefinitely.

        Returns:
            ``{command, success, returncode, stdout, stderr}`` or
            ``{command, success: False, error}``.
        """
        try:
            argv = shlex.split(command or "")
        except ValueError as exc:
            return {"command": command, "success": False, "error": str(exc)}
        if not argv:
            return {"command": command, "success": False, "error": "No command."}

        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell=True.
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return {
                "command": command,
                "success": False,
                "error": f"Command not found: {os.path.basename(argv[0])!r}.",
            }
        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "success": False,
                "error": f"Timed out after {timeout_seconds}s.",
            }

        return {
            "command": command,
            "success": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    return [run_command]


__all__ = ["terminal_tools"]
