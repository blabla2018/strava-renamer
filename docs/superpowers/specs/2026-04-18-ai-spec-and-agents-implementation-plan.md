# AI Spec And Agents Implementation Plan

## Goal

Implement the approved documentation redesign by producing:

- `docs/spec.md` as the single product behavior contract
- `AGENTS.md` as the single AI workflow contract

Then remove the legacy documentation files that previously split this knowledge
across multiple partial documents.

## Scope

This implementation plan covers only documentation migration.

It does not include:

- code refactoring
- behavior changes in the naming engine
- Golden Set rewrites unrelated to documentation
- workflow automation beyond what is written into `AGENTS.md`

## Inputs

The implementation should draw from:

- `docs/product.md`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/migration-plan.md`
- `docs/acceptance.md`
- `docs/refactor-backlog.md`
- the approved design document:
  - `docs/superpowers/specs/2026-04-18-ai-spec-and-agents-design.md`
- current repository workflow already practiced in the project

## Deliverables

1. `docs/spec.md`
2. `AGENTS.md`
3. removal of:
   - `docs/product.md`
   - `docs/requirements.md`
   - `docs/architecture.md`
   - `docs/migration-plan.md`
   - `docs/acceptance.md`

## Implementation Phases

### Phase 1: Build `docs/spec.md`

Write a rules-first, implementation-agnostic product specification.

Required content:

- product purpose
- system boundaries
- inputs and outputs
- hard invariants
- route interpretation rules
- title construction rules
- anchor selection rules
- ambiguity resolution
- failure and fallback rules
- evaluation contract
- positive examples
- negative patterns and examples

Requirements for this phase:

- the document must be optimized for AI-agent consumption
- the document must not depend on current module names or current file layout
- the document must distinguish mandatory rules from softer heuristics
- the document must explicitly describe what bad naming looks like

Completion check:

- a future agent should be able to understand how the product is expected to
  behave without reading the legacy docs

### Phase 2: Build `AGENTS.md`

Write the operational repository guide for AI agents.

Required content:

- source-of-truth rules
- workflow before editing code
- Golden Set handling rules
- expected title update rules
- testing and eval requirements
- reporting requirements
- forbidden actions
- escalation rules for user confirmation

Requirements for this phase:

- `AGENTS.md` must not redefine product behavior
- `AGENTS.md` must point to `docs/spec.md` as the product contract
- the document must reflect the actual desired workflow for this repository, not
  a generic AI coding guide

Completion check:

- a future agent should be able to follow the repo workflow without relying on
  chat history

### Phase 3: Coverage Review

Perform a deliberate migration review before deleting legacy docs.

Review checklist:

- every important product rule from the old docs appears in `docs/spec.md`
- every important workflow rule appears in `AGENTS.md`
- no critical concept exists only in a file scheduled for deletion
- `docs/spec.md` and `AGENTS.md` do not contradict each other
- `AGENTS.md` does not contain product logic that belongs in `docs/spec.md`

If any gap is found, update the new documents before continuing.

### Phase 4: Delete Legacy Docs

Delete the replaced documentation files only after coverage review succeeds.

Files to remove:

- `docs/product.md`
- `docs/requirements.md`
- `docs/architecture.md`
- `docs/migration-plan.md`
- `docs/acceptance.md`

This deletion is part of the implementation, not a later cleanup task.

### Phase 5: Validate Repository State

After the migration:

- confirm the new documents exist in the expected paths
- confirm the legacy docs are gone
- verify links and references are still valid
- run repository tests that are appropriate for this documentation-only change
- summarize the migration outcome and remaining risks

## Execution Order

The recommended order is strict:

1. write `docs/spec.md`
2. review and refine `docs/spec.md`
3. write `AGENTS.md`
4. review and refine `AGENTS.md`
5. run coverage review across old and new documents
6. delete legacy docs
7. run final validation

Do not delete legacy docs before both new files are written and reviewed.

## Acceptance Criteria

The plan is complete when all of the following are true:

- `docs/spec.md` exists and is the only product behavior contract
- `AGENTS.md` exists and is the only AI workflow contract
- legacy docs listed in this plan are removed
- the repository no longer depends on those legacy docs to explain product
  behavior or AI workflow
- the new documentation is clear enough that future AI agents can operate from
  repository files rather than implicit conversation context

## Risks

### Risk: over-compression

Trying to make the new files too short may omit important rules or examples.

Mitigation:

- compress wording, not meaning
- keep negative examples where they teach product boundaries

### Risk: duplication

The same rule may end up in both `docs/spec.md` and `AGENTS.md`.

Mitigation:

- move product behavior into `docs/spec.md`
- keep `AGENTS.md` process-only

### Risk: incomplete migration

Useful content may remain only in soon-to-be-deleted legacy docs.

Mitigation:

- perform explicit coverage review before deletion
