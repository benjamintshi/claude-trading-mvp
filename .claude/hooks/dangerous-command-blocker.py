#!/usr/bin/env python3
"""PreToolUse hook: Block dangerous shell commands in trading system."""
import json
import sys
import re

BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r"rm\s+-rf\s+\.",
    r"git\s+push\s+.*--force",
    r"git\s+reset\s+--hard",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
    r"DELETE\s+FROM\s+(?!.*WHERE)",  # DELETE without WHERE
    r"TRUNCATE\s+TABLE",
    r">\s*/dev/sd",
    r"mkfs\.",
    r"dd\s+if=",
    r"chmod\s+-R\s+777",
    r"curl.*\|\s*(?:bash|sh)",
]

def main():
    try:
        tool_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        json.dump({"decision": "approve"}, sys.stdout)
        return

    tool_name = tool_input.get("tool_name", "")
    if tool_name != "Bash":
        json.dump({"decision": "approve"}, sys.stdout)
        return

    command = tool_input.get("tool_input", {}).get("command", "")

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            json.dump({
                "decision": "block",
                "reason": f"BLOCKED: Dangerous command detected matching '{pattern}'. If you need to run this, ask the user first."
            }, sys.stdout)
            return

    json.dump({"decision": "approve"}, sys.stdout)

if __name__ == "__main__":
    main()
