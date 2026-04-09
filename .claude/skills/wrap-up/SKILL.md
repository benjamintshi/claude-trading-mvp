---
name: wrap-up
description: >-
  End-of-session lifecycle management. Commits outstanding changes, extracts learnings
  from the session, detects patterns, and persists insights. Use when finishing a work
  session or before switching to a different task.
allowed-tools: Read, Write, Bash, Grep, Glob
argument-hint: "[save|review|full]"
---

# Session Wrap-Up

Structured session closure to ensure nothing is lost between conversations.

## Modes

- `/wrap-up save` — Quick: commit + status summary only
- `/wrap-up review` — Extract learnings + patterns only (no git operations)
- `/wrap-up full` — All 4 phases (default)

## Phase 1: Ship Outstanding Work

### 1a. Check for uncommitted changes
```bash
git status
git diff --stat
```

### 1b. If changes exist:
- Review the diff — are changes complete and coherent?
- If YES: stage and commit with conventional commit message
- If PARTIAL: stash with descriptive message: `git stash push -m "WIP: {description}"`
- If BROKEN: do NOT commit. Note in wrap-up report.

### 1c. Check for untracked files
- New files that should be tracked? → `git add` + commit
- Generated/temp files? → Verify .gitignore covers them

## Phase 2: Extract Learnings

Review the current session's work and extract:

### Decisions Made
- What technical decisions were made and why?
- What alternatives were considered and rejected?
- Save significant decisions to `/knowledge record`:
  ```
  Decision: [what]
  Context: [why this choice]
  Alternatives: [what was rejected]
  Date: YYYY-MM-DD
  ```

### Surprises & Gotchas
- What was unexpected? (API behavior, library quirk, performance cliff)
- What took longer than expected and why?
- These are candidates for project rules or CLAUDE.md gotchas

### Patterns Observed
- Did we repeat a workflow that should be a skill?
- Did we copy-paste code that should be extracted?
- Did we work around a limitation that should be documented?

## Phase 3: Detect Reusable Patterns

Analyze the session's tool calls and edits:

1. **Repeated workflows** — Same sequence of read → edit → test done 3+ times?
   → Suggest: create a skill or script
2. **Repeated searches** — Same grep/glob patterns used across sessions?
   → Suggest: document the search pattern in project rules
3. **Manual steps** — Things that were done manually that could be automated?
   → Suggest: add a hook or npm script

## Phase 4: Persist & Report

### Write session summary
Save to `docs/sessions/YYYY-MM-DD.md` (create dir if needed):

```markdown
# Session: YYYY-MM-DD

## What was done
- [1-3 bullet summary of work completed]

## Files changed
- [list from git diff --stat]

## Decisions
- [key decisions with rationale]

## Learnings
- [surprises, gotchas, patterns]

## Open items
- [ ] [anything left unfinished]
- [ ] [follow-up tasks for next session]

## Suggested improvements
- [workflow optimizations, new rules, new skills]
```

### Update project state
- If specs were involved: update task status in `specs/{feature}/TASKS.md`
- If bugs were fixed: update status in `specs/bugs/BUG-*.md`

### Present to user
```
Session wrap-up complete:
- Committed: {N} files in {M} commits
- Learnings: {N} extracted
- Open items: {N} for next session
- Session log: docs/sessions/YYYY-MM-DD.md
```

## Key Principles
- **File-as-truth** — if it's not written to a file, it didn't happen
- **Ship or stash** — never leave uncommitted changes in limbo
- **Lightweight** — this should take < 2 minutes, not a full retrospective
- **Idempotent** — running wrap-up twice doesn't create duplicate entries
