from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest


class StartupTests(unittest.TestCase):
    def test_app_import_defers_cp_sat_until_background_warmup(self) -> None:
        code = textwrap.dedent(
            """
            import json
            import sys

            import hexsolver_cn.app
            from hexsolver_cn.demo_board import build_demo_board
            from hexsolver_cn.solver import (
                HexReasoningSolver,
                global_solver_is_ready,
                warm_up_global_solver,
            )

            before_local_step = global_solver_is_ready()
            move = HexReasoningSolver().next_step(build_demo_board())
            after_local_step = global_solver_is_ready()
            warm_up_global_solver()
            print(json.dumps({
                "before_local_step": before_local_step,
                "after_local_step": after_local_step,
                "after_warmup": global_solver_is_ready(),
                "move_found": move is not None,
                "module_loaded": "ortools.sat.python.cp_model" in sys.modules,
            }))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1])

        self.assertFalse(payload["before_local_step"])
        self.assertFalse(payload["after_local_step"])
        self.assertTrue(payload["move_found"])
        self.assertTrue(payload["after_warmup"])
        self.assertTrue(payload["module_loaded"])


if __name__ == "__main__":
    unittest.main()
