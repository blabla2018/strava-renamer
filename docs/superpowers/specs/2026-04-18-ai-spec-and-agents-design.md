# AI Spec And Agents Design

## Purpose

Replace the current fragmented documentation set with two authoritative files:

- `docs/spec.md` as the single product specification for the activity naming system
- `AGENTS.md` as the single operational guide for AI agents working in this repository

The new documentation must be written primarily for AI agents, not for frequent
human reading. The goal is to make future code changes, dataset updates, and
behavior adjustments more consistent, less ad hoc, and easier to validate.

## Problem Statement

The repository currently contains useful but fragmented documents:

- `docs/product.md`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/migration-plan.md`
- `docs/acceptance.md`

These documents capture real project knowledge, but they are no longer a clean
single source of truth for an AI agent. The practical consequences are:

- product behavior rules are spread across multiple files
- operational AI workflow rules are mixed into conversation history instead of a
  durable repository file
- the codebase can drift from intended behavior because there is no one document
  that defines the system contract
- future AI agents must reconstruct intent from multiple sources instead of
  reading one clear product spec and one clear workflow guide

## Decision Summary

The project will adopt exactly two authoritative documentation files:

1. `docs/spec.md`
2. `AGENTS.md`

The current multi-file documentation set will be removed after the new files are
written and validated.

This is a hard replacement, not an archive-based migration.

## File Roles

### `docs/spec.md`

`docs/spec.md` will be the only product specification for the activity naming
system.

Its role is to define:

- what the product does
- what inputs it may use
- what outputs it produces
- which rules are mandatory
- which heuristics are preferred but not absolute
- how route interpretation works
- how title anchors are selected
- how ambiguity is resolved
- what failure and fallback behavior is allowed
- how evaluation against Golden Set is interpreted
- what good and bad naming outcomes look like

`docs/spec.md` must be:

- rules-first
- implementation-agnostic
- optimized for AI-agent interpretation
- written as a mixed contract of hard invariants plus softer heuristics

It must not be written as a narrative design essay.

It must not depend on the current file layout or current module names.

### `AGENTS.md`

`AGENTS.md` will be the operational guide for AI agents working in the
repository.

Its role is to define:

- how the agent should approach product changes
- what must be checked before and after edits
- how Golden Set must be used
- when `expected_title` may be changed
- when user confirmation is required
- how tests and eval must be run
- how to report outcomes and unresolved risks
- what kinds of changes are forbidden without explicit approval

`AGENTS.md` is process-oriented, not product-oriented.

It must not redefine product behavior. It must refer to `docs/spec.md` as the
source of truth for product behavior.

## Specification Style

The new `docs/spec.md` will use a mixed rule model:

- hard invariants expressed as mandatory rules
- heuristics expressed as preferred behavior with explicit room for ambiguity

This style matches the actual product problem:

- some rules are absolute, such as not overwriting manual titles
- some rules are contextual, such as choosing between a locality and a climb
- some outcomes may legitimately have more than one acceptable title

The spec will therefore avoid pretending that every naming decision has only one
objective answer.

## Baseline Product Mode

The product is `deterministic-first`.

This means:

- deterministic route analysis is the default path
- AI is not the primary naming engine
- AI may be used only as a bounded tie-breaker when deterministic logic has
  already produced multiple plausible candidates

The spec must make this explicit so future AI agents do not silently convert the
product into an AI-first naming system.

## Golden Set Policy

Golden Set remains the main evaluation contract, but not an untouchable oracle.

The agreed policy is:

- Golden Set is the default source of truth for behavior validation
- mismatches are treated as regressions unless there is a clear reason not to
- the agent may propose revising Golden Set when a new behavior is clearly
  better or already user-approved
- the agent may update `expected_title` only when the user has explicitly
  approved the new title or the new naming rule in conversation

This policy belongs in both files:

- product interpretation in `docs/spec.md`
- operational workflow in `AGENTS.md`

## Required Sections For `docs/spec.md`

The new product spec will contain these sections:

1. `Purpose`
2. `System Boundaries`
3. `Inputs`
4. `Outputs`
5. `Hard Invariants`
6. `Route Interpretation Rules`
7. `Title Construction Rules`
8. `Anchor Selection Rules`
9. `Ambiguity Resolution`
10. `Failure And Fallback Rules`
11. `Evaluation Contract`
12. `Positive Examples`
13. `Negative Patterns And Examples`

The examples section is required because Golden Set contains accepted outcomes,
but does not explain bad outcomes. The spec must explicitly define bad naming
patterns so an AI agent can avoid them even when no exact negative test exists.

## Required Sections For `AGENTS.md`

The agent guide will contain these sections:

1. `Purpose And Priority`
2. `Source Of Truth`
3. `Change Workflow`
4. `Golden Set Rules`
5. `Expected Title Update Rules`
6. `Testing And Eval Requirements`
7. `Reporting Requirements`
8. `Forbidden Actions`
9. `When To Ask The User`

The guide should be detailed enough to standardize common work, but not so long
that it becomes a second product spec.

## Migration Plan

The documentation migration should happen in this order:

1. write `docs/spec.md`
2. write `AGENTS.md`
3. verify that all important behavior and workflow rules from the old documents
   are represented in the new files
4. remove:
   - `docs/product.md`
   - `docs/requirements.md`
   - `docs/architecture.md`
   - `docs/migration-plan.md`
   - `docs/acceptance.md`
5. leave the repository with only the new authoritative files plus any
   implementation-facing docs that may be created later for separate purposes

This migration should not preserve the old files in an archive directory because
the explicit goal is to eliminate outdated parallel sources of truth.

## Risks And Mitigations

### Risk: The new spec becomes too abstract

If `docs/spec.md` is written at too high a level, AI agents will still fall back
to reading code and guessing behavior.

Mitigation:

- keep the document rule-oriented
- include explicit negative patterns
- include concrete positive examples
- define failure behavior, not only ideal behavior

### Risk: `AGENTS.md` duplicates the spec

If `AGENTS.md` starts restating naming behavior, the project will again have two
behavioral sources of truth.

Mitigation:

- keep `AGENTS.md` focused on process
- make `docs/spec.md` the only behavior contract

### Risk: deletion of old docs removes useful nuance

The old documents contain valid context gathered over multiple sessions.

Mitigation:

- migrate content intentionally, not mechanically
- compare old documents against the new files before deletion
- only delete the old docs after coverage is confirmed

## Acceptance Criteria

This design is considered successful when:

- `docs/spec.md` can stand alone as the single product contract
- `AGENTS.md` can stand alone as the single agent workflow contract
- an AI agent can read those two files and make consistent changes without
  consulting the removed legacy documents
- the old documentation set is no longer needed and can be deleted safely
