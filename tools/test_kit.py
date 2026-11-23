#!/usr/bin/env python3
"""Self-tests of gear_kit.py. Run: python tools/test_kit.py   (exit code 0 = all passed)"""
import copy
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gear_kit as K

FAILED = []


def check(label, condition, detail=""):
    if not condition:
        FAILED.append(label)
    print("%s  %s%s" % ("ok  " if condition else "FAIL", label, ("   " + str(detail)) if (detail and not condition) else ""))


def parity_level():
    p = K.Puzzle("Parity", "Make the target turn against the motor.")
    p.set_rules(chain=False)
    m = p.template(12, motor_speed=30, color="blue")
    g = p.template(16)
    motor = p.gear(m, (0, 0), id="Motor")
    r_m, r_g = m.pitch, g.pitch
    x = r_m + 2 * r_g + 2 * r_g + r_g          # two 16t idlers between the motor and a 16t target
    p.gear(g, (x, 0), id="Target")
    p.limit(m, 0)
    p.limit(g, 2)
    p.goal_speed("Target", -30 * 12 / 16.0, "Against the motor")
    p.fit_view()
    a = K.mesh_pos(motor.pos, r_m, r_g, 0)
    b = K.mesh_pos(a, r_g, r_g, 0)
    p.player_gear(g, a)
    p.player_gear(g, b)
    return p


def test_geometry():
    check("pitch radius is teeth * size / 2", K.pitch_radius(16, 10) == 80.0)
    check("outer radius is the tip circle", K.outer_radius(16, 10) == 90.0)
    pos = K.mesh_pos((0, 0), 60.0, 80.0, 90)
    check("mesh_pos stands at the sum of the pitch radii, y is down", pos == [0.0, 140.0], pos)
    pts = K.circle_intersections((0, 0), 5, (6, 0), 5)
    check("two circles meet in two points", len(pts) == 2 and all(abs(math.hypot(x, y) - 5) < 1e-9 for x, y in pts))
    check("tangent circles meet in one point", len(K.circle_intersections((0, 0), 5, (10, 0), 5)) == 1)
    check("far circles do not meet", K.circle_intersections((0, 0), 1, (10, 0), 1) == [])
    T = [K.TI({"tooth_count": 16, "tooth_size": 10, "type": "INTERNAL", "rim_ratio": 1.5}), K.TI({"tooth_count": 6, "tooth_size": 10})]
    check("a ring gear needs 6 more teeth than the gear inside it", K.can_mesh(T[0], T[1]) and not K.can_mesh(T[0], K.TI({"tooth_count": 11})))
    check("ring and gear mesh at the difference of the radii", K.mesh_distance(T[0], T[1]) == 50.0)
    check("a motor needs torque and a speed", not K.TI({"motor_free_speed": 30.0}).is_motor and K.TI({"motor_free_speed": 30.0, "motor_stall_torque": 1.0}).is_motor)


def test_builder_and_user_puzzle():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "examples", "puzzle_4.json")
    if not os.path.exists(path):
        path = os.path.join(here, "puzzle_4.json")
    theirs = json.load(open(path))
    p = K.Puzzle("puzzle_4")
    t16, tm, t32 = p.template(16), p.template(12, motor_speed=30, color="blue"), p.template(32)
    p.gear(t16, (160, 32), layer=1, id="Target")
    p.gear(tm, (-220, 32), layer=0, id="Motor")
    p.limit(t16, 1)
    p.limit(tm, 0)
    p.limit(t32, 1)
    p.goal_speed("Target", 45)
    mine = p.to_dict()
    for g in theirs["gears"]:
        g["rotation"] = 0.0
    theirs.pop("view", None)
    check("the builder writes the game's own export, key for key", mine == theirs)
    p.set_rules(chain=False)
    a = K.analyse(json.load(open(path)))
    check("the game's own puzzle has no errors and is not won", not a.errors and not a.won, a.errors)
    s1 = p.player_gear(t16, K.mesh_pos((-220, 32), 60, 80, 0), layer=0, axle=0)
    p.player_gear(t32, s1.pos, layer=1, axle=0)
    res = K.report(p, quiet=True)
    check("report passes the real compound-gear level", res["ok"], res["text"])
    check("and finds its decoy of 11.25 deg/s", "11.25" in res["text"], res["text"])
    sol = p.solution_dict()
    b = K.analyse(sol)
    check("compound gears give 30 * 12/16 * 32/16 = 45", abs(b.speeds["Target"] - 45.0) < 1e-9 and b.won)


def test_parity_and_report():
    p = parity_level()
    res = K.report(p, quiet=True)
    check("a parity level passes", res["ok"], res["text"])
    A = K.analyse(p.to_dict())
    B = K.analyse(p.solution_dict())
    check("two idlers flip the sense once back", abs(B.speeds["Target"] + 22.5) < 1e-9 and not A.won)
    R = K.solve(p.to_dict())
    check("the solver finds exactly the idler row", R.min_depth == 2 and len(R.families) >= 1, R.solutions[:1])


def test_failures_are_caught():
    p = parity_level()
    d = p.solution_dict()
    d["gears"][-1]["position"][0] += 1.2
    a = K.analyse(d)
    check("a gear 1.2 px off the mesh distance is refused as almost meshed", any("almost meshed" in e for e in a.errors), a.errors)
    d = p.solution_dict()
    d["gears"][-1]["position"][0] = d["gears"][-2]["position"][0] + 100
    d["gears"][-1]["position"][1] = 0
    a = K.analyse(d)
    check("overlapping gears are refused", any("overlap" in e for e in a.errors), a.errors)
    d = p.solution_dict()
    d["gears"].append({"template": 1, "position": [d["gears"][-1]["position"][0] / 2, 140.0], "rotation": 0.0, "layer": 0, "axle": -1})
    t = K.TI(d["templates"][1])
    d["gears"][-1]["position"] = [(d["gears"][-3]["position"][0] + d["gears"][-2]["position"][0]) / 2, math.sqrt(160.0 ** 2 - 80.0 ** 2)]
    a = K.analyse(d)
    check("a gear meshing two meshed neighbours (odd loop) is a JAM", any("JAM" in e for e in a.errors), a.errors)
    d = parity_level().to_dict()
    d["gears"][0]["axle"] = 3
    d["gears"].append(dict(d["gears"][0], position=[5.0, 0.0], id="X", fixed=True, layer=1, axle=3))
    a = K.analyse(d)
    check("gears of one axle must share a position", any("same position" in e for e in a.errors), a.errors)
    p2 = parity_level()
    p2.limits.pop(1)
    check("a template without a limit is a kit error", any("no limit" in e for e in K.kit_errors(p2.to_dict())))
    p3 = parity_level()
    p3.limit(p3.templates[0], 1)
    check("a motor the player could place is a kit error", any("motor" in e for e in K.kit_errors(p3.to_dict())))
    p4 = parity_level()
    p4.objectives[0]["condition"]["children"][0]["gear"] = "Nope"
    check("an objective on a missing gear is an error", any("not a named gear" in e for e in K.analyse(p4.to_dict()).errors))
    p5 = parity_level()
    p5.goal_speed("Target", -22.5, "extra")
    p5.objectives = p5.objectives[:1]
    p5.objectives[0]["condition"]["children"][0]["value"] = 0.0
    check("an objective already true at the start is caught by the report", not K.report(p5, quiet=True)["ok"])
    p6 = parity_level()
    p6.stock.pop()
    check("a solution that does not win is caught", not K.report(p6, quiet=True)["ok"])
    p8 = parity_level()
    p8.set_rules(chain=True)
    check("a level where the player may chain is a kit error", any("chain" in e for e in K.kit_errors(p8.to_dict())))
    p8.set_rules(chain=False)
    p8.set_rules(place=True)
    check("set_rules leaves the rules it is not given alone", p8.allow_chain is False)
    p7 = parity_level()
    p7.limit(p7.templates[1], 1)
    check("a solution over the limit is caught", any("limit" in e for e in K.check_solution(p7.to_dict(), p7.solution_dict())))
    for bad, why in ((lambda: K.Puzzle("t").template(5), "teeth below 6"), (lambda: K.Puzzle("t").template(16, size=0), "size 0"),
                     (lambda: K.Puzzle("t").template(16, color="pink"), "unknown color")):
        try:
            bad()
            check("the builder refuses " + why, False)
        except K.KitError:
            check("the builder refuses " + why, True)


def test_rules_areas_layers():
    p = parity_level()
    p.allow_area(-100, -200, 2000, 400)
    check("idlers inside an allow area are fine", K.report(p, quiet=True)["ok"])
    p = parity_level()
    p.block_area(100, -50, 100, 100)
    res = K.report(p, quiet=True)
    check("a block area across the only route makes the intended solution fail", not res["ok"] and any("blocked" in e for e in res["errors"]), res["text"])
    p = parity_level()
    p.lock_layers(1)
    res = K.report(p, quiet=True)
    check("locking the layer the solution uses fails", not res["ok"] and any("lock" in e for e in res["errors"]), res["text"])
    p = parity_level()
    p.set_rules(place=False)
    res = K.report(p, quiet=True)
    check("forbidding placement fails a level that needs it", not res["ok"], res["text"])
    r, errs = K.Rules.parse({"areas": [{"rect": [0, 0, 10, 10], "mode": "allow", "layers": [[5, 2], 3]}]}, 1)
    check("area layers are turned round and merged", not errs and r.areas[0][5] == [(2, 5)], errs)
    r, errs = K.Rules.parse({"areas": [{"rect": [0, 0, 0, 10], "mode": "allow"}]}, 1)
    check("an area without a width is refused", bool(errs))
    r, errs = K.Rules.parse({"chain_gears": 1}, 1)
    check("one gear per chain is refused", bool(errs))
    r = K.Rules()
    r.areas = [(0, 0, 100, 100, "allow", []), (100, 0, 100, 100, "allow", [])]
    check("a gear across two allow areas fits in neither", r.area_error(100, 50, 0, 20) != "" and r.area_error(50, 50, 0, 20) == "")
    r.areas = [(0, 0, 100, 100, "block", [])]
    check("touching a block area from outside is fine", r.area_error(-20, 50, 0, 20) == "" and r.area_error(-19, 50, 0, 20) != "")


def test_solver_negative_and_budget():
    p = K.Puzzle("Far", "Too far.")
    p.set_rules(chain=False)
    m = p.template(12, motor_speed=30, color="blue")
    g = p.template(16)
    p.gear(m, (0, 0), id="Motor")
    p.gear(g, (3000, 0), id="Target")
    p.limit(m, 0)
    p.limit(g, 2)
    p.goal_speed("Target", -30)
    R = K.solve(p.to_dict())
    check("a gap the stock cannot bridge has no solution and the search says it finished", not R.solutions and R.complete, (R.states, R.complete))
    p = K.Puzzle("Big", "Four gears with a bend.")
    p.set_rules(chain=False)
    m = p.template(12, motor_speed=30, color="blue")
    g = p.template(16)
    h = p.template(24)
    motor = p.gear(m, (0, 0), id="Motor")
    first = K.mesh_pos(motor.pos, m.pitch, g.pitch, 0)
    second = K.mesh_pos(first, g.pitch, g.pitch, 60)
    third = K.mesh_pos(second, g.pitch, h.pitch, 0)
    fourth = K.mesh_pos(third, h.pitch, g.pitch, -60)
    p.gear(g, K.mesh_pos(fourth, g.pitch, g.pitch, 0), id="Target")
    p.limit(m, 0)
    p.limit(g, 3)
    p.limit(h, 1)
    for pos, tpl in ((first, g), (second, g), (third, h), (fourth, g)):
        p.player_gear(tpl, pos)
    p.goal_speed("Target", 1.0)
    speed = K.analyse(p.solution_dict()).speeds["Target"]
    p.objectives = []
    p.goal_speed("Target", speed, "go")
    p.fit_view()
    t0 = time.time()
    res = K.report(p, quiet=True)
    check("a four-gear bent level passes the report inside the budget", res["ok"] and time.time() - t0 < 12.0, (time.time() - t0, res["text"]))
    R = K.solve(p.to_dict())
    check("the search finishes and finds the bent solution at 30 degrees", R.complete and R.min_depth == 4, (R.states, R.complete))

def test_build_files():
    p = parity_level()
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_test_out")
    paths = p.write(folder, "parity")
    ok = all(os.path.exists(x) for x in paths)
    d = json.load(open(paths[0]))
    s = json.load(open(paths[1]))
    check("write() makes the puzzle and its solution", ok and len(s["gears"]) == len(d["gears"]) + 2)
    check("the file is the game's text format: tabs and sorted keys", open(paths[0]).read().startswith('{\n\t"chains"'))
    for x in paths:
        os.remove(x)
    os.rmdir(folder)


def main():
    for fn in (test_geometry, test_builder_and_user_puzzle, test_parity_and_report, test_failures_are_caught,
               test_rules_areas_layers, test_solver_negative_and_budget, test_build_files):
        print("--", fn.__name__)
        fn()
    print("\n%d failed" % len(FAILED) if FAILED else "\nall passed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
