# Agent Guide

This file defines how AI agents must work in this repository.

For product behavior, read `docs/spec.md`. That file is the source of truth for
what the activity naming system should do.

This file is about process: how to change the repository safely.

## 1. Purpose And Priority

Agents must optimize for safe, explainable improvements to activity naming.

Priority order:

1. preserve user data and manual activity titles
2. follow `docs/spec.md`
3. keep Golden Set behavior observable
4. make small, testable changes
5. explain outcomes clearly

If this file and `docs/spec.md` appear to conflict, product behavior comes from
`docs/spec.md`; workflow behavior comes from this file.

## 2. Source Of Truth

Use these sources in this order:

1. explicit user instruction in the current conversation
2. `docs/spec.md`
3. `AGENTS.md`
4. Golden Set and eval reports
5. current code and tests

Do not rely on old chat history when a repository file can define the rule.

## 3. Change Workflow

Before changing behavior:

1. identify which product rule in `docs/spec.md` applies
2. inspect the relevant code and tests
3. inspect the relevant Golden Set entries when naming behavior may change
4. explain the intended edit before modifying files

After changing behavior:

1. add or update focused tests
2. run the relevant test suite
3. run Golden Set evaluation when naming output may change
4. inspect important mismatches
5. report what changed, what improved, and what risks remain

For documentation-only changes, run tests when practical and at least verify the
affected files exist and references are consistent.

## 4. Golden Set Rules

Golden Set is the primary offline evaluation contract.

Agents must use Golden Set when:

- changing naming logic
- changing geocoding interpretation
- changing candidate ranking
- changing title validation
- changing home-start suppression
- changing rename policy

Golden Set mismatches are regressions by default. They may be accepted only with
a clear explanation or user approval.

When reporting eval results, include:

- number of activities
- exact match count
- normalized exact match count when available
- average similarity when available
- important improved and worsened examples

## 5. Expected Title Update Rules

Do not change `expected_title` just because the current code generates something
different.

`expected_title` may be updated only when:

- the user explicitly approves the new title
- or the user explicitly approves the broader naming rule that produces it

When multiple titles are valid, prefer `accepted_titles` over replacing the main
expected title unless the user clearly chooses a new primary expected title.

When updating Golden Set:

- preserve useful `review_comment` context
- add a comment when the reason for the expected value is not obvious
- run eval afterward and confirm the affected row

## 6. Testing And Eval Requirements

After each code change, run focused tests that cover the edited behavior.

For naming behavior changes, also run Golden Set evaluation in cache-only mode
when possible.

Use network only when needed to refresh missing Strava or geocoding cache, and
make clear when live data was used.

Recommended checks:

- unit tests for the edited module
- naming tests for title behavior
- geocoding tests for locality interpretation
- eval for Golden Set behavior

Do not claim a change is safe if tests or eval were not run. Say what was not
run and why.

## 7. Manual Title Safety

Protecting manual titles is safety-critical.

Agents must not weaken manual-title protection unless the user explicitly asks
for overwrite behavior.

If overwrite is needed for a one-off command, prefer a temporary environment
override over changing persistent configuration.

## 8. Reporting Requirements

Final reports should be concise and concrete.

Include:

- what changed
- where it changed
- what tests or eval were run
- key outputs for important activities
- remaining risks or follow-up items

For activity-specific investigations, include the intermediate decision chain:

- route shape
- start and end places
- turnaround or destination
- via places
- ordered highlights
- candidates considered
- reason the final title won

## 9. Forbidden Actions

Do not:

- overwrite manual titles without explicit user approval
- update Golden Set expected titles without user approval
- add place-specific hacks as a first response to a naming bug
- move local hacks from code into config and call that a fix
- use AI to invent route places
- hide eval regressions behind summary metrics
- delete or rewrite user changes unrelated to the task

## 10. When To Ask The User

Ask the user before:

- changing Golden Set expected titles without a prior explicit approval
- applying names to Strava in bulk
- enabling behavior that changes many generated titles
- accepting a title that is plausible but not clearly better
- deleting data or changing persistent configuration

Do not ask when the next step is a routine inspection, focused test, or
non-destructive dry-run.

## 11. Documentation Maintenance

Keep `docs/spec.md` and `AGENTS.md` aligned.

Product behavior belongs in `docs/spec.md`.

Agent workflow belongs in `AGENTS.md`.

If a future change adds a new naming policy, update `docs/spec.md`.

If a future change adds a new repository workflow rule, update `AGENTS.md`.
