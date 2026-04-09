---
name: code-review
description: Multi-perspective code review with 2-stage separation. Stage 1 validates spec conformance ("right thing?"), Stage 2 checks code quality ("done right?"). Use for PR reviews or pre-commit checks.
allowed-tools: Read, Bash, Grep
context: fork
argument-hint: "[file-or-pr]"
---

# Code Review Skill (2-Stage)

## Core Insight
**"Did we build the right thing?" and "Did we build it right?" must be checked separately.** Combined reviews miss spec gaps because reviewers get distracted by code style.

## 1. Understand Context
- Read the changed files and their surrounding context
- Understand the purpose of the change (commit message, PR description, or ask)
- If specs exist: read `specs/{feature}/PRD.md` and `TASKS.md`

---

## Stage 1: Spec Validation ("Built the right thing?")

Skip this stage if no spec exists (go directly to Stage 2).

### Checklist
- Does the implementation match what the PRD describes?
- Are all acceptance criteria addressed in code?
- Are there implemented features NOT in the spec? (scope creep)
- Are there spec requirements NOT implemented? (gaps)
- Does the API contract match DESIGN.md?

### Stage 1 Output
```
## Spec Validation
- Spec coverage: {N}/{M} AC addressed
- Scope creep: [list of unspecified additions, if any]
- Gaps: [list of missing requirements, if any]
- Verdict: MATCH / PARTIAL / MISMATCH
```

---

## Stage 2: Code Quality ("Built it right?")

### Correctness
- Does the code do what it claims?
- Edge cases handled? (null, empty, overflow, concurrency)
- Error handling complete and correct?
- No off-by-one errors?

### Security
- Input validation on all external data?
- No SQL injection, XSS, or path traversal?
- Secrets handled properly?
- Auth/authz checks present?

### Performance
- No N+1 queries?
- Appropriate indexing for new queries?
- No unnecessary allocations in hot paths?
- Caching where appropriate?

### Maintainability
- Functions < 50 lines? Clear naming?
- No duplication? DRY?
- Tests added/updated?
- Documentation updated?

### AI Slop Check
- Redundant defensive code not matching project patterns?
- Comments that restate the code?
- Over-abstraction for one-time operations?
- Debug/placeholder leftovers?

---

## 3. Combined Output

```
## Review Summary

### Stage 1: Spec Validation
**Verdict**: MATCH / PARTIAL / MISMATCH
- [findings]

### Stage 2: Code Quality
**Verdict**: APPROVE / APPROVE WITH COMMENTS / REQUEST CHANGES

### Critical Issues (must fix)
- [file:line] Description — [spec|correctness|security|performance|maintainability|slop]

### Suggestions (nice to have)
- [file:line] Description

### Positives
- What was done well
```

## Multi-Agent Review (Subagent Mode)
When invoked with `/code-review --team`:

**Stage 1** (spec validation) — orchestrator handles directly

**Stage 2** (code quality) — launch 3 subagents in parallel:
- `@security-reviewer` — OWASP, auth, injection, secrets
- `@perf-reviewer` — N+1, caching, allocations, indexes
- `@arch-reviewer` — patterns, coupling, maintainability, AI slop

Each subagent returns independent findings (<200 word summary).
Orchestrator merges Stage 1 + Stage 2 findings into single prioritized review.

## Guardrails
- DO NOT skip Stage 1 when specs exist — the most impactful bugs are "works perfectly but solves the wrong problem"
- DO NOT mix spec feedback and code feedback — keep stages separate in output
- DO NOT review files not in the diff — stay focused on what changed
- DO flag AI slop but distinguish from project conventions (grep for existing patterns before flagging)
