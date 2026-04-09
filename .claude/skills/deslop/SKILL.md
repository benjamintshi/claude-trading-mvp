---
name: deslop
description: >-
  Review and remove AI-generated code slop: unnecessary defensive code, redundant comments,
  excessive type casts, lint ignores, placeholder text, debug leftovers. Use after AI-assisted
  coding sessions or before PR submission.
allowed-tools: Read, Edit, Bash, Grep, Glob
argument-hint: "[file-or-branch]"
---

# AI Code Slop Remover

Review code changes and remove AI-generated "slop" — defensive noise, unnecessary additions, and patterns that don't match project conventions.

## Slop Categories

### Category 1: Redundant Defensive Code
- Null checks where value is guaranteed non-null by types/framework
- Try/catch wrapping code that can't throw
- Validation on internal function inputs (already validated at boundary)
- Redundant `|| ''`, `?? 0`, `|| []` on typed values

### Category 2: Unnecessary Comments
- Comments that restate the code: `// increment counter` above `counter++`
- Comments on self-explanatory functions: `// Returns the user` above `getUser()`
- Section dividers that add no information: `// --- Helper Functions ---`
- JSDoc/docstrings on private/internal functions with obvious signatures

### Category 3: Over-Engineering
- Abstraction layers for one-time operations
- Feature flags for non-optional features
- Backwards-compatibility shims for code that just changed
- Utility functions used exactly once
- Extra configurability nobody asked for

### Category 4: Debug & Placeholder Leftovers
- `console.log`, `print()`, `dbg!()` debug statements
- `// TODO`, `// FIXME`, `// HACK` without issue references
- Commented-out code blocks
- Placeholder error messages: "Something went wrong", "An error occurred"

### Category 5: Lint/Type Workarounds
- `// eslint-disable`, `// @ts-ignore`, `# type: ignore`, `#[allow(...)]`
- `as any`, `as unknown as X` type assertions
- `unwrap()` / `expect("should never happen")`
- `_ = unused_var` without justification

## Process

### Step 1: Gather Diff
```bash
# If branch specified:
git diff main...HEAD -- '*.ts' '*.tsx' '*.py' '*.rs' '*.java'

# If file specified:
git diff HEAD -- {file}

# If no arg — check staged + unstaged:
git diff HEAD
```

### Step 2: Scan for Slop Patterns
For each added/modified line in the diff:
1. Match against slop categories above
2. For each candidate, read the **full file context** (surrounding 20 lines)
3. Judge: is this genuinely unnecessary, or does it serve a real purpose?

### Step 3: Cross-Reference Project Conventions
Before removing anything:
- Check if the pattern exists elsewhere in the codebase (Grep)
- If the project consistently uses this pattern, it's convention, not slop
- If only AI-generated code has this pattern, it's slop

### Step 4: Apply Fixes
For each confirmed slop item:
- Remove it with minimal edit (don't rewrite surrounding code)
- Group related removals in the same file

### Step 5: Verify
```bash
# Build must still pass
npm run build  # or cargo build, etc.

# Tests must still pass
npm test  # or cargo test, etc.

# Lint must still pass
npm run lint  # or cargo clippy, etc.
```

## Guardrails — DO NOT Remove

- Trust boundary validation (API input checks, auth guards)
- Error handling on external calls (HTTP, DB, file I/O)
- Type narrowing that prevents runtime errors
- Comments explaining **why** (not what) — business logic rationale
- Defensive code in security-critical paths
- Test assertions (even if they seem redundant)

## Output Format

```markdown
## Deslop Report

### Removed ({count} items)
| File | Line | Category | What was removed |
|------|------|----------|-----------------|
| src/api/users.ts | 42 | Redundant comment | `// Get the user from database` |
| src/services/auth.ts | 78 | Debug leftover | `console.log('token:', token)` |

### Kept (reviewed but intentional)
- src/api/users.ts:15 — null check kept (external API input)

### Verification
- Build: PASS
- Tests: PASS (N tests)
- Lint: PASS
```

## Key Principles
- **Context over pattern** — same code can be slop in one place and essential in another
- **Convention wins** — if the project does it consistently, don't fight it
- **Minimal edits** — remove slop, don't refactor surrounding code
- **Safety first** — when in doubt, keep it
- **Verify after** — always run build + test after changes
