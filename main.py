from __future__ import annotations

import sys
import os
import traceback
from pathlib import Path
from typing import Callable


_run_app: Callable[[], None] | None = None
_app_import_failure: str | None = None
try:
    # Keep the normal application import first. Besides making startup behavior
    # explicit, this preserves PyInstaller's Qt hook order for qtawesome/PySide6.
    from src.hexsolver_cn.app import run_app as _run_app
except Exception:
    _app_import_failure = traceback.format_exc()


def _write_smoke_failure(message: str) -> None:
    log_path = os.environ.get("HEXSOLVER_PACKAGE_SMOKE_LOG")
    if not log_path:
        return
    with Path(log_path).open("a", encoding="utf-8") as stream:
        stream.write(message)
        if not message.endswith("\n"):
            stream.write("\n")


def main() -> int:
    if _app_import_failure is not None:
        if "--package-smoke-test" in sys.argv:
            _write_smoke_failure("application-import-failure")
            _write_smoke_failure(_app_import_failure)
            return 1
        raise RuntimeError("应用模块加载失败。\n" + _app_import_failure)

    if "--package-smoke-test" in sys.argv:
        try:
            from src.hexsolver_cn.package_smoke import run_package_smoke_test
        except Exception:
            _write_smoke_failure("package-smoke-import-failure")
            _write_smoke_failure(traceback.format_exc())
            return 1

        return run_package_smoke_test()
    assert _run_app is not None
    _run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
