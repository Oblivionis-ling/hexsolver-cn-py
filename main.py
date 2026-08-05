from __future__ import annotations

import sys

from src.hexsolver_cn.app import run_app


def main() -> int:
    if "--package-smoke-test" in sys.argv:
        from src.hexsolver_cn.package_smoke import run_package_smoke_test

        return run_package_smoke_test()
    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
