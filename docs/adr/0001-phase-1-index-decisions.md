# ADR 0001 — Phase 1 index decisions

Status: accepted · 2026-09-27

Decisions made while building Phase 0/1 where CLAUDE.md leaves a choice open.

## In-house PageRank instead of networkx

A ~40-line power iteration (`prism/graph/ranking.py`) with a fixed summation order and scores
rounded to 6 decimals. It keeps runtime dependencies minimal and makes byte-stable output easy to
guarantee across platforms and library versions.

## Marker format for AGENTS.md regions

CLAUDE.md shows only opening markers. Regions use explicit open/close pairs
(`<!-- prism:narrative:purpose -->` … `<!-- /prism:narrative:purpose -->`) so the writer can
replace generated regions and carry narrative regions over without guessing where one ends.

## Entry points live in `dependency_graph.json`

The artifact list in CLAUDE.md Section 7 has no file for entry points. They are stored as a
top-level `entry_points` list in `dependency_graph.json`, and each module node carries an
`entry_point` kind. No new artifact file was added.

## Call resolution confidence

- `high`: resolved through a local definition or an explicit import, including package
  re-exports and `*` imports.
- `medium`: resolved through `self`/`cls`/`super()` into a base class, or through a variable whose
  type comes from a parameter annotation or a `x = Class(...)` assignment.
- `low`: `obj.method()` where exactly one function/method in the repo has that name.

Ambiguous calls are dropped rather than guessed.

## Module names

Derived from the path, with configured `source_roots` (default `src`) stripped. When an absolute
import does not match a module exactly, a *unique* dotted-suffix match is accepted, so repos whose
import root is a subdirectory (`backend/app/...` imported as `app...`) still resolve.

## Ignore precedence

`.gitignore` files are applied with git's precedence: deeper files override shallower ones, and
`!pattern` re-includes. `.prismignore` and config `ignore` patterns always exclude and cannot be
overridden by `.gitignore` negations.
