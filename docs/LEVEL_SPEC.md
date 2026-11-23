# LEVEL SPEC: how to build gear-puzzle levels (read completely before writing anything)

You are building levels for a 2D puzzle game about meshing gears. A level is a short Python file
(`levels/level_NN_slug.py`) that uses the kit in `tools/gear_kit.py`. The kit writes the game's JSON, checks the
level with an offline model of the game, and searches for the ways a player could solve it. **You never write
JSON by hand.** A level is only done when the kit's report says `RESULT: PASS` and you have read its WARNINGS
and NOTES.

## 1. Hard rules

1. Never write puzzle JSON by hand and never edit anything under `tools/`. If you think the kit is wrong, say so
   in your answer with a minimal example. Do not patch it.
2. Never claim a level passes unless you ran `report()` in your code execution and the output you quote is
   real. Quote the `RESULT:` line and the `decoys` line in your answer.
3. Compute every position with `mesh_pos()` (and `Gear.pos`). Never type a coordinate for a gear that has to mesh.
4. Use only what section 5 lists. Everything else (chains, ring gears, one-way gears, slip gears, torque,
   resistance, min_speed, other objective types) is **not supported**: the kit cannot check it.
5. Design the level on paper first (the design card in the file's docstring), then write `build()`.
6. Deliver only new files `levels/level_NN_slug.py`. The JSON files are generated later by `python tools/build.py`.

## 2. The loop (the sandbox keeps no files and has no network)

Your code execution starts empty every time, so each run is ONE script made of, in this order:

1. The **entire** text of `tools/gear_kit_cell.py`, unchanged (it is the kit without comments).
2. The line `selfcheck()`. It must print `KIT OK`. If it does not, the paste was damaged: paste it again.
3. The text of your level file (keep its `try: from gear_kit import *` lines, they are harmless there).
4. `res = report(build(), solve_seconds=6)`

The whole run must finish in 30 seconds, so run **one level per execution**. Then:

- Read the report. Fix every ERROR. Think about every WARNING and NOTE (section 7). Run again.
- Repeat until `RESULT: PASS` and the quality bar (section 3) is met. Do not stop at the first PASS.
- If the report says the search stopped by its budget, reduce the stock, the number of layers or the free space.

## 3. The quality bar (what makes a level good)

A good level is small, exact and has a reason. The reference is `levels/level_02_compound_gear.py`: a fixed 12-tooth
motor on layer 0, a fixed 16-tooth target on layer 1, and a stock of exactly one 16-tooth and one 32-tooth gear.

1. **One idea.** The level teaches exactly one new thing. Say it in the design card.
2. **Tight stock.** The stock is exactly the gears of the intended solution. A report warning "spare stock" is
   acceptable only in the first two levels of a batch.
3. **A decoy** (from the third level on). At least one wrong arrangement must fit and move the goal gear but give
   a different speed (the report's `decoys` line shows it). Level 02: the same two gears with the big one on the low
   layer also bridge the gap, but give 11.25 instead of 45 deg/s. Fitting is not enough, the player must reason.
4. **Few ways to win.** Aim for 1 solution family. If the report shows more, each must be intended, otherwise tighten
   the stock, the layers or the areas.
5. **Clear numbers.** Motor speeds 15 to 60 deg/s, target speeds 5 to 180. An objective accepts the target within 1%
   (at least 0.5 deg/s), so a decoy must differ from the goal by at least 10%.
6. **Readable.** Everything fits one screen (about 1600 x 900 px at most), `p.fit_view()` is called, the title is
   short (under 40 characters), the description says WHAT to achieve in one or two sentences and never HOW.
7. **Difficulty rises slowly.** In a batch: levels 1-2 are tutorials (stock up to 3 gears), 3-5 use up to 4, later
   ones up to 5. A level may add one new element to the previous one, never two.

## 4. Game facts you can rely on (from the game's own code)

- Pitch radius = `teeth * size / 2`. The tip (outer) radius = pitch radius + `size`. The house `size` is 10.
  A gear has 6 to 128 teeth; `size` is a whole number from 1 to 100.
- Two gears **mesh** when they are on the **same layer**, have the **same size**, and their centers are exactly
  `pitch_a + pitch_b` apart. Always use `mesh_pos()`.
- Gears of one layer that do not mesh must stay apart: tip circles must not touch (the kit keeps 1 px extra). A gear
  placed 1 to 3 px off the mesh distance is refused as "almost meshed".
- Meshed neighbours turn in opposite directions: `speed_out = -speed_in * teeth_in / teeth_out`.
- Gears on one **axle** share one position, sit on **different layers**, and turn together at the same speed.
  Axle ids are whole numbers; use `p.new_axle()`. Only axles connect layers.
- Speeds are degrees per second. **Positive = clockwise** on screen. Screen coordinates: +x right, **+y down**.
- A gear is a **motor** when its template has `motor_speed != 0`. It is always fixed and hidden from the player.
- The player's stock for a template is `limit - (unfixed gears of that template already on the board)`. Fixed gears
  never count. A template without a limit is unlimited; a limit of 0 hides the template from the player.
- A fixed gear can never be moved or deleted by the player. Objectives may only mention named fixed gears.
- The player can place a gear on the same position as a gear of another layer and key it to that gear's axle. To
  support this on a fixed gear, give that fixed gear an axle (`axle=p.new_axle()`) and use the same id for the
  player's gear. (The report then warns "axle N has a single gear" for the start state: that is expected.)

## 5. API (everything else is off limits)

```python
p = Puzzle("Title", "Description")                  # title <= 80, description <= 1000 characters

t = p.template(teeth, size=10, motor_speed=0, color="gray")   # color: gray|gold|blue|red|"rrggbb"
t.pitch  t.outer  t.teeth  t.size                           # radii and counts of a template

g = p.gear(t, (x, y), layer=0, id="Name", fixed=True, axle=-1)  # what the player finds. id: [A-Za-z][A-Za-z0-9_]{0,15}
g.pos  g.x  g.y  g.id  g.layer  g.axle

p.limit(t, n)            # EVERY template needs a limit. 0 hides it (motors: always 0)
p.set_rules(chain=False) # REQUIRED in every level. Also: move=False, place=False
p.lock_layers(0, (2, 4)) # optional: the player may only work on these layers
p.allow_area(x, y, w, h, layers=None)   # optional: gears must stand inside ONE allow area (where one applies)
p.block_area(x, y, w, h, layers=None)   # optional: gears must not overlap it. Block beats allow.

p.goal_speed("Name", value, "Objective title", required=True, hold=1.0)   # the gear turns at value deg/s
p.objective(node, "title", required=True)   # advanced: node from speed_node(g, v), all_of(...), any_of(...),
                                            # not_of(n), hold_of(seconds, n)

s = p.player_gear(t, (x, y), layer=0, axle=-1)  # a gear of the INTENDED SOLUTION (what the player will place)
a = p.new_axle()                                 # a free axle id
p.fit_view()                                     # frame everything (required)

mesh_pos(center, r_a, r_b, angle_deg)   # center of a gear of pitch radius r_b meshing a gear of pitch radius r_a at
                                        # center. 0 deg = right, 90 deg = DOWN. Returns [x, y].
pitch_radius(teeth, size=10)  outer_radius(teeth, size=10)
report(p, solve_seconds=6)              # checks + search + verdict. Always print it.
```

Level file skeleton: `levels/_template.py`. Worked examples: `levels/level_01_idlers.py`, `levels/level_02_compound_gear.py`.

## 6. Archetypes and recipes

Each recipe says what the level teaches and how to get the numbers right. Combine at most one new recipe per level.

- **A. Idlers (parity).** A row of equal gears between motor and target: each gear reverses the turning direction, the
  teeth of idlers cancel out. The number of gears in the row decides the sign. Gap between motor and target =
  `motor.pitch + 2 * k * idler.pitch + target.pitch` for `k` straight idlers (`mesh_pos` with angle 0 does it).
  A bent row is always shorter, so a straight gap with exactly `k` idlers cannot be solved with a bend.
- **B. Compound gear (axle across layers).** Two gears of different size on one axle: the small one is driven, the
  big one drives (or the reverse). Ratio = (teeth of the driven gear on the first layer) / (teeth of the driving gear
  on the second layer), see level 02. Build the solution with one `p.new_axle()` and `layer=` 0/1.
- **C. Decoy by ratio.** Offer two gears that can each take either role. The wrong assignment still fits and gives a
  different speed. Check the numbers with the report's `decoys` line.
- **D. Obstacle.** A fixed gear without an id on the same layer in the way of the straight row forces a detour or a
  layer change. Keep it at least 20 px from every other same-layer gear's tip circle unless it is meant to mesh.
- **E. Workshop (areas).** `p.allow_area(...)` limits where the player may build, `p.block_area(...)` forbids a
  region. Use them to remove an unintended solution, never to make the level fiddly. The intended solution must obey them.
- **F. Two outputs.** Two named targets: `p.objective(hold_of(1, all_of(speed_node("A", 30), speed_node("B", -60))), "Both")`.
  Use a required main objective plus an optional bonus one with `required=False` if you want a bonus.

## 7. Reading the report

```
stock the player has ...           what the player can place
start state ... not won (good)     the level must not be solved at the start
intended solution ... WON          your player_gear() gears must win
search: N states                   how much the solver tried
search found K solution(s) in F family(ies); fewest gears: m of n in stock
decoys (...): 11.25 deg/s x2 ...   wrong arrangements and the speed they give the goal gear
ERRORS / WARNINGS / NOTES
RESULT: PASS | FAIL
```

- **ERRORS** always mean fix it (overlap, almost meshed, jam, unknown name, missing limit, chain rule, ...).
- **"spare stock"**: a solution needs fewer gears than the player has. Remove the spare gear (not in levels 1-2).
- **"no decoy found"**: fine in tutorials, otherwise add a decoy (recipe C).
- **"N different ways to win"**: look at the listed families. Keep only the intended ones.
- **"the search did not rediscover the intended solution"**: fine when the intended solution validated; the search
  samples positions every 30 degrees plus exact two-gear fits.
- **"search stopped by the budget"**: results are partial. Make the level smaller or reduce free space.
- A solution that "keys a new gear onto the axle of a FIXED gear" is possible in the game; check it is intended.

The search is a model, not the game. Anything it finds is valid in the model, anything it does not find is not proof
that it is impossible. Torque, stalls, one-way and slip gears and chain geometry are never simulated.

## 8. Delivering

For each level, answer with:

1. The new file `levels/level_NN_slug.py` (as a diff/file, nothing else changed).
2. Three lines: what it teaches, the intended solution, the decoy (or "none" with the reason).
3. The real `RESULT:` line and `decoys` line from your last report, and any WARNING you decided to keep, with why.

Name files `level_NN_slug.py` (two digits, lowercase slug). Do not reuse numbers that exist.
