import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


DEFAULT_MAX_SECONDS = int(os.getenv("SANDBOX_MAX_SECONDS", "30"))
DEFAULT_MAX_OUTPUT_BYTES = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", str(1024 * 1024)))


def _truncate_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return value
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return f"{truncated}\n...[truncated to {max_bytes} bytes]"


def _safe_env() -> Dict[str, str]:
    return {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _script_for(code: str) -> str:
    return f"""
import json
from pathlib import Path


def _json_default(value):
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    try:
        import pandas as pd
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
    except Exception:
        pass
    return str(value)


with open("inputs.json", "r", encoding="utf-8") as _inputs_file:
    _payload = json.load(_inputs_file)

inputs = {{
    "analysis_goal": _payload.get("analysis_goal", ""),
    "layers": _payload.get("layers", []),
    "params": _payload.get("params", {{}}),
}}
params = inputs["params"]
result = None
geojson_outputs = []
artifacts = []

{code}

Path("result.json").write_text(
    json.dumps(
        {{
            "result": result,
            "geojson_outputs": geojson_outputs,
            "artifacts": artifacts,
        }},
        default=_json_default,
    ),
    encoding="utf-8",
)
"""


def execute_python(payload: Dict[str, Any]) -> Dict[str, Any]:
    code = payload.get("code") or ""
    layers = payload.get("layers") or []
    max_seconds = int(payload.get("max_seconds") or DEFAULT_MAX_SECONDS)
    max_output_bytes = int(payload.get("max_output_bytes") or DEFAULT_MAX_OUTPUT_BYTES)

    if not code.strip():
        layer_names = [layer.get("title") or layer.get("name") for layer in layers]
        return {
            "ok": True,
            "summary": (
                "Python analysis sandbox is available. "
                f"Received {len(layers)} layer(s): {', '.join(filter(None, layer_names))}."
            ),
            "stdout": "",
            "stderr": "",
            "result": {
                "layer_count": len(layers),
                "layers": layer_names,
            },
            "artifacts": [],
            "geojson_outputs": [],
        }

    with tempfile.TemporaryDirectory(prefix="nalamap-analysis-", dir="/tmp") as workdir:
        workdir_path = Path(workdir)
        (workdir_path / "inputs.json").write_text(
            json.dumps(payload, default=str),
            encoding="utf-8",
        )
        (workdir_path / "analysis.py").write_text(_script_for(code), encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, "analysis.py"],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=max_seconds,
                env=_safe_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "summary": "Python analysis timed out.",
                "stdout": _truncate_text(exc.stdout or "", max_output_bytes),
                "stderr": _truncate_text(exc.stderr or "", max_output_bytes),
                "result": None,
                "artifacts": [],
                "geojson_outputs": [],
                "error": f"Execution exceeded {max_seconds} seconds.",
            }

        stdout = _truncate_text(completed.stdout or "", max_output_bytes)
        stderr = _truncate_text(completed.stderr or "", max_output_bytes)

        result_path = workdir_path / "result.json"
        result_payload: Dict[str, Any] = {}
        if result_path.exists():
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                stderr = f"{stderr}\nFailed to parse result.json: {exc}".strip()

        ok = completed.returncode == 0
        return {
            "ok": ok,
            "summary": (
                "Python analysis completed."
                if ok
                else f"Python analysis failed with exit code {completed.returncode}."
            ),
            "stdout": stdout,
            "stderr": stderr,
            "result": result_payload.get("result"),
            "artifacts": result_payload.get("artifacts") or [],
            "geojson_outputs": result_payload.get("geojson_outputs") or [],
            "error": (
                None if ok else f"Process exited with code {completed.returncode}."
            ),
        }
