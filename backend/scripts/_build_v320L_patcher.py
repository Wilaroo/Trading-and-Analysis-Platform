#!/usr/bin/env python3
"""_build_v320L_patcher.py — generator for patch_v320L_naked_sweep_datetime_fix.py

Removes the function-local `from datetime import datetime, timezone` at
trading_bot_service.py:5958 (inside _naked_position_sweep) that shadowed the
module-global datetime/timezone for the whole function and caused
UnboundLocalError at the naked-sweep telemetry write (~L6530). Replaced with a
marker comment; bare uses now resolve to the module import (line 19).
"""
from pathlib import Path

import _build_v320ij_patchers as M

HERE = Path(__file__).resolve().parent
TBS = HERE.parent / "services" / "trading_bot_service.py"
TBS_PRE = "b4cb8a7dfcabe6fb02108b0f40283dc05f596351bcdb3ec45a17960604c2d8b6"

OLD = (
    "                from routers.ib import _pushed_ib_data\n"
    "                from datetime import datetime, timezone\n"
    "                _lu = (_pushed_ib_data or {}).get(\"last_update\")\n"
)
NEW = (
    "                from routers.ib import _pushed_ib_data\n"
    "                # v19.34.320L — use module-global datetime/timezone (line 19).\n"
    "                # The prior local \"from datetime import datetime, timezone\" here\n"
    "                # bound them function-wide, causing UnboundLocalError at the\n"
    "                # naked-sweep telemetry write (~L6530) when this branch wasn't taken.\n"
    "                _lu = (_pushed_ib_data or {}).get(\"last_update\")\n"
)


def main():
    M.emit(
        "patch_v320L_naked_sweep_datetime_fix.py", "v19.34.320L",
        "patch_v320L_naked_sweep_datetime_fix.py",
        ("Bug fix (pre-existing v19.34.31): _naked_position_sweep had a\\n"
         "function-local `from datetime import datetime, timezone` (L5958) inside\\n"
         "a conditional branch, making datetime/timezone LOCALS for the whole\\n"
         "function. The naked-sweep telemetry write (~L6530) then raised\\n"
         "UnboundLocalError every cycle when that branch wasn't taken. Removes\\n"
         "the redundant local import; module-global (L19) now resolves.\\n"
         "trading_bot_service.py."),
        "V320L_TBS_TARGET", "backend/services/trading_bot_service.py",
        "v19.34.320L", "/tmp/v320L_naked_sweep_datetime.applied",
        TBS_PRE, TBS.read_text(encoding="utf-8"),
        [(OLD, NEW)],
    )


if __name__ == "__main__":
    main()
