#!/usr/bin/env python3
"""PostToolUse hook: Remind to run tests after editing Python files."""
import json
import sys

def main():
    try:
        tool_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        json.dump({}, sys.stdout)
        return

    tool_name = tool_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        json.dump({}, sys.stdout)
        return

    file_path = tool_input.get("tool_input", {}).get("file_path", "")

    if file_path.endswith(".py") and "/test" not in file_path:
        json.dump({
            "decision": "approve",
            "reason": "📋 Edited Python file. Remember: `pytest tests/` to verify."
        }, sys.stdout)
        return

    json.dump({}, sys.stdout)

if __name__ == "__main__":
    main()
