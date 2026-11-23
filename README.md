# Gear puzzles

Levels for the gear puzzle game, built with a small Python kit instead of hand-written JSON.

```
docs/LEVEL_SPEC.md      the instructions for whoever builds levels (read this first)
docs/REVIEW.md          how to judge a generated level
tools/gear_kit.py       builder + checker + solver (the readable source)
tools/gear_kit_cell.py  the same kit without comments: what an AI pastes into a code-execution cell
tools/build.py          builds all levels: check, solve, write puzzles/*.json
tools/test_kit.py       tests of the kit (python tools/test_kit.py)
tools/make_cell.py      regenerates gear_kit_cell.py after a change of gear_kit.py (Python 3.9+)
levels/                 one Python file per level (level_NN_slug.py), _template.py is the skeleton
puzzles/                generated JSON (the game's files) + the *.solution.json of every level
examples/puzzle_4.json  a puzzle exported by the game, the format reference
```

## For a human

```
python tools/test_kit.py        # the kit tests, should print "all passed"
python tools/build.py           # all levels; --only 03 for one; --solve-seconds 15 for a longer search
```
A level that passes is written to `puzzles/<name>.json` (open it in the editor) and
`puzzles/<name>.solution.json` (the same puzzle with the intended solution already placed).

## For Gemini (AI Studio): kickoff prompt

> You build levels for a 2D gear puzzle game. First read `README.md` and `docs/LEVEL_SPEC.md` completely, then
> `levels/_template.py`, `levels/level_01_idlers.py` and `levels/level_02_compound_gear.py`, then `tools/gear_kit_cell.py`.
> Follow the loop in section 2 of the spec exactly: your code execution has no files and no network, so every run
> pastes the whole `tools/gear_kit_cell.py` first, then `selfcheck()`, then one level, then `report(build(), solve_seconds=6)`.
> Make the levels I ask for, one at a time. For each: write the design card, build it, run the report, fix, repeat until
> PASS and the quality bar of section 3 is met. Deliver only new files `levels/level_NN_slug.py` and, for each, the real
> RESULT and decoys lines of your last report. Never write JSON by hand, never edit `tools/`.
>
> This batch: levels NN to MM. Difficulty: ... Ideas I want covered: ...

## What the kit models (and what it does not)

Models: gear geometry from the game's `Gear2D` (pitch radius `teeth * size / 2`, tip radius + `size`), meshing, axles,
speeds, jams, objectives (`speed` with `approx`, `all`, `any`, `not`, `hold`), rules (limits, layers, areas, place/move),
start-not-won, solution-wins, and a search over how the stock can be placed.
Does not model: torque and stalls, one-way and slip gears, ring gears, chains, other objective properties. Levels using
them have to be checked in the editor. The mesh tolerance and clearance rules of the game engine are not in the sources
the kit was written from, so the kit is stricter than the game on purpose.
