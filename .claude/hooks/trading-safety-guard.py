#!/usr/bin/env python3
"""PreToolUse hook: Protect critical trading parameters from unreviewed modification.

Warns when editing risk management code, position sizing, or trading configuration.
Does NOT block — just surfaces a warning so the user sees the change.
"""
import json
import sys
import re

# Files/patterns that contain critical trading logic
PROTECTED_FILES = [
    "lib/db.py",       # Position tracking, PnL calculation, config values
    "lib/binance.py",  # Order execution, position sizing (calc_quantity)
    ".env",            # API keys, database URL
]

# Code patterns that indicate risk parameter changes
RISK_PATTERNS = [
    r"risk_per_trade",
    r"max_positions",
    r"capital\s*=",
    r"leverage\s*=",
    r"commission\s*=",
    r"calc_quantity",
    r"place_order",
    r"open_long|open_short|close_long|close_short",
    r"INSERT INTO config",
    r"UPDATE config",
]

def main():
    try:
        tool_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        json.dump({"decision": "approve"}, sys.stdout)
        return

    tool_name = tool_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        json.dump({"decision": "approve"}, sys.stdout)
        return

    inp = tool_input.get("tool_input", {})
    file_path = inp.get("file_path", "")
    new_string = inp.get("new_string", "") or inp.get("content", "")

    # Check if editing a protected file
    for pf in PROTECTED_FILES:
        if file_path.endswith(pf):
            json.dump({
                "decision": "approve",
                "reason": f"⚠️ TRADING SAFETY: Editing protected file '{pf}'. Verify risk parameters are unchanged or intentionally modified."
            }, sys.stdout)
            return

    # Check if new content touches risk patterns
    for pattern in RISK_PATTERNS:
        if re.search(pattern, new_string, re.IGNORECASE):
            json.dump({
                "decision": "approve",
                "reason": f"⚠️ TRADING SAFETY: Change touches risk-related code ('{pattern}'). Run tests after this change."
            }, sys.stdout)
            return

    json.dump({"decision": "approve"}, sys.stdout)

if __name__ == "__main__":
    main()
