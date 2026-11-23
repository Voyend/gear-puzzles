# Review sheet for a generated level

Run `python tools/build.py`, then open `puzzles/<name>.json` in the editor (Play it), and the matching
`puzzles/<name>.solution.json` to see the intended solution. Score each line 0 (no) or 1 (yes).

**Technical (must all be 1)**
- [ ] The puzzle file loads in the editor without an error dialog.
- [ ] The start state is not won; the objective list shows it unmet.
- [ ] The solution file loads, and in Play the objective turns green (and the win panel shows after the hold time).
- [ ] No gear is shown red/blocked in the solution file; the start view frames everything on a normal window.
- [ ] A player can really drag the stock gears from the palette to the positions of the solution (snapping helps).

**Design**
- [ ] One clear idea; you can say it in a sentence.
- [ ] The stock is exactly what the solution needs (no spare gear, no missing one).
- [ ] There is a decoy (levels 3 and later) that fits but gives a wrong speed.
- [ ] You could not find a cheaper or different way to win that was not intended.
- [ ] The description says what to do, not how.
- [ ] The level is a little harder than the one before.

**If the editor and the report disagree**, copy the editor's message, the report, and the level file and send them
to Claude: the kit's geometry is the part that most needs calibration (the engine's exact mesh tolerance and
clearance rules were not in the sources, so the kit is stricter than the game on purpose).
