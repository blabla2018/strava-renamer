# Strava Renamer Product Specification

This file is the product behavior contract for the activity naming system.

It is written for AI agents. It defines what the product must do, what it must
not do, and how naming decisions should be evaluated. It intentionally avoids
references to the current implementation structure so the code can evolve
without making this document obsolete.

## 1. Purpose

The product generates human-friendly titles for outdoor cycling activities.

Generated titles should help a cyclist understand where a ride went by naming
recognizable geographic or cycling-relevant route anchors. A title should sound
like something a cyclist might use when describing the ride to another cyclist.

The product is deterministic-first:

- deterministic route analysis is the default naming path
- AI may advise only after deterministic logic has produced plausible candidates
- AI must not invent route geography or become the primary naming engine

## 2. System Boundaries

The product generates candidate names and decides whether they are safe to apply.

The product may:

- analyze route shape
- extract route-derived geographic entities
- build and rank candidate titles
- produce a confidence score and reason
- decide whether a generated title may be applied

The product must not:

- invent places not supported by route-derived data
- overwrite a manually renamed activity unless explicitly configured or approved
- treat noisy segment fragments as final names
- silently change Golden Set expectations without user approval
- rely on place-specific hacks as the normal way to improve naming quality

## 3. Inputs

The product may use these inputs:

- activity payload
- sport type and activity metadata
- route polyline or cached route points
- reverse geocoding results
- segment efforts and segment metadata
- detected route landmarks
- athlete profile, including profile city when available
- athlete naming history when available
- Golden Set for offline evaluation

Golden Set is an evaluation input only. It must not be used as online inference
data for naming a live activity.

## 4. Outputs

For each processed activity, the product should produce:

- generated title, or no title if the system lacks enough confidence
- confidence score
- human-readable reason
- rename eligibility decision
- rename rejection reason when the title should not be applied

## 5. Hard Invariants

The following rules are mandatory.

### 5.1 Manual Titles

The system must not overwrite an activity title that appears to have been
manually set by the athlete.

Default titles such as `Morning Ride`, `Lunch Ride`, and similar Strava default
names may be replaced. User-written titles must be preserved unless the user
explicitly requests overwrite behavior.

### 5.2 No Invented Places

Every title component must be supported by route-derived evidence.

Allowed evidence includes:

- reverse geocoding
- route points
- segment data
- detected landmarks
- athlete history only as a ranking signal, not as proof that a place exists on
  the current route

### 5.3 No Low-Confidence Application

A title with confidence below the configured application threshold must not be
applied automatically.

Low-confidence titles may be shown for inspection, but must not be written back
to Strava without explicit user approval.

### 5.4 No Noisy Final Titles

The final title must not be made of unclear technical fragments, jokes,
directional leftovers, or local segment noise.

The system should prefer no rename or a conservative city-level title over a
noisy title.

### 5.5 No Core Region Hacks

Core naming behavior must not depend on hardcoded local place names or local
exceptions.

The system may understand generic concepts such as city, town, village, hamlet,
climb, pass, lighthouse, landmark, road fragment, segment noise, support
strength, and route position.

## 6. Route Interpretation Rules

Route shape influences title composition.

### 6.1 Point-To-Point

For rides with distinct start and finish locations, the default title structure
is:

`Start - Main Anchor - Finish`

The main anchor should be omitted if it is weak, noisy, or redundant.

### 6.2 Out-And-Back

For rides that go from a start location to a main destination and return, the
default title structure is:

`Start - Destination`

If a major intermediate anchor is important for understanding the route, a
three-component title may be used.

### 6.3 Loop

For loop rides, the title should name the start area and the main destination or
route-defining anchor.

Typical structure:

`Start - Destination`

Ring-like loops may use multiple major route anchors when they add meaning.

### 6.4 Branched Or Star-Like Routes

For branched routes, the title should try to represent each meaningful branch
apex or route-defining vertex while staying readable.

The system should avoid pretending that a branched route has only one simple
destination when two or more branches clearly define the ride.

### 6.5 Short Intra-City Rides

For short rides that remain inside one city, the system should not build a title
from segment noise.

Preferred behavior:

- return the city name with low confidence
- or decline to rename

Examples:

- acceptable conservative output: `València`
- bad output: `Semaforo - Tunel`

## 7. Title Construction Rules

### 7.1 Component Count

Preferred title length is two components.

Three components are appropriate when an intermediate anchor clearly improves
route understanding.

Four components are acceptable for long or complex rides, especially above
roughly 120 km.

Five components are the hard upper bound and should be reserved for very long or
complex rides such as 160 to 200 km routes.

### 7.2 Start Component

Include the start location when:

- the ride starts outside the athlete's home city
- the route is point-to-point
- omitting the start would make the title ambiguous

Omit the start location when:

- home-start suppression is enabled
- the start city matches the athlete profile city
- the remaining title still contains at least one meaningful route anchor

Home city comparison should use city name matching. Region and country should
not block a match because APIs may return different representations such as
`Spain`, `España`, or `ES`.

### 7.3 Intermediate Components

Intermediate anchors should be included only when they are large, recognizable,
or route-defining.

Do not add extra components merely because a sampled point or segment exists.

### 7.4 Compactness

Titles should be compact. A shorter title is better when it preserves the
meaning of the route.

The system should avoid:

- repeated place names
- redundant parent and child places
- weak trailing fragments
- long segment composites

## 8. Anchor Selection Rules

### 8.1 Preferred Anchors

Prefer anchors that cyclists naturally use:

- cities
- towns
- recognizable villages
- main destination localities
- well-known climbs
- mountain passes
- route-defining lighthouses
- route-defining landmarks
- major coastal or geographic features

### 8.2 Climb Versus Locality

When choosing between a small locality and a well-known climb, the climb should
usually win if it better identifies the ride.

Example:

- `Calicanto` may be better than a weak nearby municipality when the climb is the
  recognizable cycling identity of the ride.

### 8.3 Parent Locality Versus Micro-Location

When reverse geocoding returns a tiny place inside or near a recognizable parent
town, the title should usually use the parent town.

Examples:

- `Masia del Raco` should generalize to `Cullera`
- a hamlet or isolated dwelling should not beat a recognizable town

Village-level places can still be valid when they are the meaningful settlement
visited by the route.

Example:

- `el Perellonet` is acceptable for a short destination ride when it is the
  actual village reached by the route.

### 8.4 Landmark Versus Noise

Route-defining landmarks are allowed. Weak local POIs are not.

Allowed when route-defining:

- lighthouse
- famous viewpoint
- mountain pass
- major climb

Discouraged when incidental:

- isolated monument
- tiny local attraction
- arbitrary road object
- local business or facility

### 8.5 Segment Data

Segment data is useful as evidence, especially for climbs, but segment names are
often noisy.

Segment-derived anchors require stronger validation than reverse-geocoded
localities.

The system should reject or down-rank:

- jokes
- challenge names
- technical workout terms
- road numbers without geographic identity
- generic direction words
- short segment fragments with no stable place meaning

## 9. Ambiguity Resolution

Some routes have more than one acceptable title.

The system should resolve ambiguity in this order:

1. deterministic route evidence and candidate scoring
2. athlete naming history, if available
3. bounded AI tie-breaking, if enabled and needed
4. user review for important or unclear changes

AI tie-breaking may only compare already extracted candidates. AI must not add
new places or rewrite geography.

The system should support accepted alternatives in evaluation when the user has
approved more than one reasonable title.

## 10. Failure And Fallback Rules

### 10.1 Incomplete Geocoding

If reverse geocoding is incomplete, the system should still try to produce a
reasonable candidate from available strong evidence.

However, it must prefer no rename over a bad title.

If only weak evidence exists, return no title or a low-confidence conservative
title.

### 10.2 Missing Start Or End

If start or end locality is missing, the system may build a title from strong
via places and route-defining highlights.

Example:

- `Calvià - Sa Creu`

But it must not build a title from weak segment fragments just to avoid returning
empty.

### 10.3 Segment-Only Routes

If the only anchors are segment-derived, the title must pass strict noise
validation.

If segment names are noisy, prefer no rename.

### 10.4 Short Urban Routes

Short city rides should not be renamed into segment fragments.

If the route is short and stays inside one city, acceptable outcomes are:

- no rename
- low-confidence city title

## 11. Evaluation Contract

Golden Set is the primary offline behavior contract.

After meaningful product behavior changes, the Golden Set should be regenerated
and compared against expected titles.

Useful metrics include:

- exact match
- normalized exact match
- string similarity
- token Jaccard similarity

Metrics are not the final arbiter. Human review may approve a new title that is
better but textually different.

Golden Set expectations may be updated only when:

- the user explicitly approves the new title
- or the user explicitly approves the new naming rule that produces the title

When multiple titles are acceptable, use accepted alternatives rather than
forcing a single false truth.

## 12. Positive Examples

Good titles are compact and recognizable.

Examples:

- `València - Cullera`
- `Cullera`
- `Olocau - Canteras`
- `València - Olocau - Canteras`
- `Oronet - Garbi`
- `València - Oronet - Garbi`
- `El Perellonet`
- `Buñol - Calicanto`
- `Platja De Muro - Sa Creu - Palma`
- `Cullera - Tavernes De La Valldigna`

These examples are not hardcoded rules. They show the desired style.

## 13. Negative Patterns And Examples

Bad titles are titles that make the athlete ask what the words mean or why they
were selected.

### 13.1 Segment Joke Or Story Fragments

Reject names built from jokes, story phrases, or non-geographic text.

Bad examples:

- `There - Back - Contrarreloj`
- `There - Back`

Reason:

- these are not route anchors
- they came from segment names, not meaningful geography

### 13.2 Technical Or Workout Fragments

Reject names built from generic training terms.

Bad examples:

- `Contrarreloj`
- `Sprint - Semaforo`
- `Semaforo - Tunel`

Reason:

- they do not describe the route in a stable geographic way

### 13.3 Overly Small Localities

Avoid micro-localities when a recognized parent town is the better cycling
destination.

Bad example:

- `València - Masia Del Raco`

Better example:

- `València - Cullera`

Reason:

- `Masia del Raco` is too local for this ride
- the route-facing destination is better represented as `Cullera`

### 13.4 Weak Segment Chains

Reject long or unclear chains of segment fragments.

Bad examples:

- `Sueca - Sollana - Bega`
- `Mareny - Barraquetes - Mareny De B...`
- `Poligono - Belcaire - Oronet - Nort`

Reason:

- they are hard to understand
- they often contain technical leftovers
- they are less human than a clearer locality or climb title

### 13.5 Incidental POI Hybrids

Reject titles created by accidentally merging nearby locality and POI signals.

Bad examples:

- `Torre - Guaita`
- `Puntal - Dels`

Reason:

- these are malformed fragments
- they are not how a cyclist would describe the ride

## 14. Change Policy

Future changes should make naming behavior:

- more explainable
- less dependent on local hacks
- easier to evaluate
- safer around manual titles
- more aligned with cyclist-facing route language

If a change improves code structure but worsens generated names, it is not
complete until the naming regression is addressed or explicitly accepted by the
user.
