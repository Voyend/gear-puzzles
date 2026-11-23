#!/usr/bin/env python3
"""gear_kit.py - build, check and solve levels of the gear puzzle game, offline (Python 3, standard library only; tested on 3.12).

WHAT IT IS
  * Builder   : Puzzle / Template / Gear classes that write the exact JSON the game loads (key names,
                enum names and colors copied from GearTemplate.to_dict and GearPuzzle.to_text).
  * Checker   : an offline model of the game for IDEAL (torque-free) puzzles: geometry, meshing, axles,
                speeds, objectives, rules (limits, layers, areas), start-not-won, solution-wins.
  * Solver    : searches for ways the player can place the stock gears (mesh positions at sampled angles,
                circle intersections, axle stacking) and reports solutions, decoys and spare stock.
  * report()  : runs all of it on a Puzzle and prints a PASS/FAIL verdict.

WHAT IT DOES NOT MODEL: torque, stalls, min_speed, one-way gears, slip gears, ring-gear clearance,
chain geometry. Levels that use them must be validated by loading them in the editor.

Geometry facts come from Gear2D: pitch radius = teeth * size / 2, tip (outer) radius = pitch + size,
two gears mesh at the sum of their pitch radii (same tooth size, same layer).

CLI:  python gear_kit.py check puzzle.json [solution.json]
      python gear_kit.py solve puzzle.json [--angle 30] [--write DIR]
      python gear_kit.py selftest
"""
import json
import math
import os
import re
import sys
import time
from itertools import combinations

__all__ = ["Puzzle", "Template", "Gear", "KitError", "mesh_pos", "pitch_radius", "outer_radius", "circle_intersections",
           "speed_node", "all_of", "any_of", "not_of", "hold_of", "report", "analyse", "solve", "selfcheck"]

# ----------------------------------------------------------------------------------------------
# Constants (limits copied from GearPuzzle / GearRules / GearTemplate / Gear2D)
# ----------------------------------------------------------------------------------------------
FORMAT = 1
MAX_TEMPLATES = 64
MAX_GEARS = 500
MIN_TOOTH_COUNT = 6
MAX_TOOTH_COUNT = 128
MAX_TOOTH_SIZE = 100
MAX_COORDINATE = 100000.0
MAX_LAYER = 64
MAX_AXLE_ID = 9999
MAX_TITLE = 80
MAX_DESCRIPTION = 1000
MAX_LIMIT = 500
MAX_LAYER_SPANS = 32
MAX_AREAS = 32
MIN_AREA_SIZE = 1.0
MIN_VIEW_SIZE = 16.0
MAX_VIEW_SIZE = 200000.0
KIT_MAX_OBJECTIVES = 8          # the game allows more; levels need 1-3
ADDENDUM = 1.0                  # tip radius above pitch radius, in tooth_size units (Gear2D)
DEDENDUM = 1.25                 # root radius below pitch radius (Gear2D)
INTERNAL_TOOTH_MARGIN = 6       # a ring gear needs this many more teeth than the gear inside (Gear2D)
EPSILON = 1e-4                  # GearRules.EPSILON

# The engine's mesh tolerance is not in the sources I had, so the kit is strict in both directions:
MESH_EXACT = 0.5                # px: this close to the mesh distance = meshed
MESH_NEAR = 3.0                 # px: between EXACT and NEAR = "almost meshed": refused, place it exactly
CLEARANCE = 1.0                 # px beyond the tip circles for gears that are NOT meshed
AXLE_SAME_POSITION = 0.01       # px: gears of one axle must stand on the same point

TYPE_NAMES = ["SPUR", "INTERNAL", "ONE_WAY", "SLIP"]       # GearTemplate.GearType order
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")      # conservative gear-name rule
PALETTE = {"gray": "8c94a1", "gold": "d2ac47", "blue": "5abcda", "red": "da5a5a"}   # editor GEAR_COLORS

TEMPLATE_DEFAULTS = {
    "type": "SPUR", "tooth_count": 16, "tooth_size": 10, "bore_ratio": 0.3, "hub_ratio": 0.7,
    "rim_ratio": 1.5, "lock_clockwise": True, "slip_torque": 50.0, "motor_free_speed": 0.0,
    "motor_stall_torque": 0.0, "resistance": 0.0, "min_speed": 0.0, "fill_color": "8c94a1ff",
    "hub_color": "6b7380ff", "outline_color": "1a1c21ff", "outline_width": 2.0, "antialiased": True,
    "id_prefix": "",
}


class KitError(Exception):
    """Raised by the builder when something cannot be a valid level."""


# ----------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------
def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _in(value, low, high):
    return _num(value) and low <= float(value) <= high


def _is_layer(value):
    return _in(value, -MAX_LAYER, MAX_LAYER) and float(value) == round(float(value))


def _r2(v):
    return round(float(v), 2)


def _darken_hex(color, amount):
    """Color.darkened(amount) of a 'rrggbb' string, as Godot rounds it."""
    out = ""
    for i in range(3):
        c = int(color[i * 2:i * 2 + 2], 16)
        out += "%02x" % min(255, max(0, int(c * (1.0 - amount) + 0.5)))
    return out


def merge_spans(spans):
    """Sorted spans with the ones that overlap or touch joined (GearRules.merge_spans)."""
    merged = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def read_span(raw):
    """A layer (8) or a pair ([0, 5]) as a span, None when it is neither."""
    if _is_layer(raw):
        return (int(raw), int(raw))
    if isinstance(raw, list) and len(raw) == 2 and _is_layer(raw[0]) and _is_layer(raw[1]):
        return (min(int(raw[0]), int(raw[1])), max(int(raw[0]), int(raw[1])))
    return None


def spans_to_data(spans):
    return [lo if lo == hi else [lo, hi] for lo, hi in spans]


def circle_intersections(c1, r1, c2, r2):
    """Points at distance r1 from c1 and r2 from c2 (0, 1 or 2 points)."""
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d < 1e-9 or d > r1 + r2 + 1e-6 or d < abs(r1 - r2) - 1e-6:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    mx, my = c1[0] + a * dx / d, c1[1] + a * dy / d
    if h < 1e-6:
        return [(mx, my)]
    return [(mx + h * dy / d, my - h * dx / d), (mx - h * dy / d, my + h * dx / d)]


# ----------------------------------------------------------------------------------------------
# Template geometry (mirrors Gear2D)
# ----------------------------------------------------------------------------------------------
class TI(object):
    """What the model needs to know about a template."""

    def __init__(self, d):
        self.type = str(d.get("type", "SPUR"))
        self.n = int(d.get("tooth_count", 16))
        self.s = int(d.get("tooth_size", 10))
        self.rim = float(d.get("rim_ratio", 1.5))
        self.free = float(d.get("motor_free_speed", 0.0))
        self.stall = float(d.get("motor_stall_torque", 0.0))
        self.internal = self.type == "INTERNAL"
        self.is_motor = self.stall > 0.0 and abs(self.free) > 1e-5     # Gear2D.is_motor()
        self.pitch = self.n * self.s * 0.5
        self.tip = self.pitch - ADDENDUM * self.s if self.internal else self.pitch + ADDENDUM * self.s
        self.root = self.pitch + DEDENDUM * self.s if self.internal else self.pitch - DEDENDUM * self.s
        self.outer = self.root + self.rim * self.s if self.internal else self.tip


def can_mesh(a, b):
    """Gear2D.can_mesh_with."""
    if a.s != b.s:
        return False
    if a.internal and b.internal:
        return False
    if a.internal:
        return a.n >= b.n + INTERNAL_TOOTH_MARGIN
    if b.internal:
        return b.n >= a.n + INTERNAL_TOOTH_MARGIN
    return True


def mesh_distance(a, b):
    """Gear2D.get_mesh_distance."""
    if a.internal != b.internal:
        return abs(a.pitch - b.pitch)
    return a.pitch + b.pitch


def mesh_pos(center, r_a, r_b, angle_deg):
    """Where the center of a gear of pitch radius r_b stands when it meshes with a gear of pitch radius r_a
    at [center]. 0 deg = +x (right), 90 deg = +y (DOWN, screen space)."""
    a = math.radians(angle_deg)
    return [_r2(center[0] + (r_a + r_b) * math.cos(a)), _r2(center[1] + (r_a + r_b) * math.sin(a))]


def pitch_radius(teeth, size=10):
    return teeth * size / 2.0


def outer_radius(teeth, size=10):
    return teeth * size / 2.0 + ADDENDUM * size


# ----------------------------------------------------------------------------------------------
# Rules (mirrors GearRules)
# ----------------------------------------------------------------------------------------------
class Rules(object):
    def __init__(self):
        self.move = True
        self.place = True
        self.chain = True
        self.chain_segment = 256.0
        self.chain_gears = 0
        self.layers = []        # inclusive spans, empty = every layer
        self.limits = {}        # template index -> most unfixed gears of it on the board
        self.areas = []         # (x, y, w, h, mode, spans), mode is "allow" or "block"
        self.hidden_rows = []

    @staticmethod
    def parse(raw, n_templates):
        """Reads the 'rules' value of a puzzle. Returns (Rules, errors)."""
        rules, errors = Rules(), []
        if raw is None:
            return rules, errors
        if not isinstance(raw, dict):
            return rules, ["rules must be an object"]
        for key in ("move", "place", "chain"):
            if not isinstance(raw.get(key, True), bool):
                errors.append("rules.%s must be true or false" % key)
        rules.move = raw.get("move", True) is True
        rules.place = raw.get("place", True) is True
        rules.chain = raw.get("chain", True) is True
        seg = raw.get("chain_segment", 256.0)
        if not _in(seg, 0.0, 10000.0):
            errors.append("rules.chain_segment must be 0..10000")
        else:
            rules.chain_segment = float(seg)
        cg = raw.get("chain_gears", 0)
        if not _in(cg, 0, MAX_LIMIT) or float(cg) != round(float(cg)) or int(cg) == 1:
            errors.append("rules.chain_gears must be 0 or a whole number from 2 to %d" % MAX_LIMIT)
        else:
            rules.chain_gears = int(cg)
        raw_layers = raw.get("layers", [])
        if not isinstance(raw_layers, list) or len(raw_layers) > MAX_LAYER_SPANS:
            errors.append("rules.layers must be a list of at most %d spans" % MAX_LAYER_SPANS)
        else:
            spans = [read_span(item) for item in raw_layers]
            if any(s is None for s in spans):
                errors.append("rules.layers: a layer is a whole number or a pair [first, last]")
            else:
                rules.layers = merge_spans(spans)
        raw_limits = raw.get("limits", [])
        if not isinstance(raw_limits, list) or len(raw_limits) > n_templates:
            errors.append("rules.limits must be a list with at most one entry per template")
        else:
            for item in raw_limits:
                if not isinstance(item, dict) or not _in(item.get("template"), 0, max(n_templates - 1, 0)) \
                        or not _in(item.get("count"), 0, MAX_LIMIT):
                    errors.append("rules.limits: each entry needs a template index and a count 0..%d" % MAX_LIMIT)
                    continue
                if int(item["template"]) in rules.limits:
                    errors.append("rules.limits: template %d has two limits" % int(item["template"]))
                rules.limits[int(item["template"])] = int(item["count"])
        raw_areas = raw.get("areas", [])
        if not isinstance(raw_areas, list) or len(raw_areas) > MAX_AREAS:
            errors.append("rules.areas must be a list of at most %d areas" % MAX_AREAS)
        else:
            for item in raw_areas:
                area = Rules._read_area(item)
                if area is None:
                    errors.append("rules.areas: an area needs rect [x, y, w, h] (w, h >= 1), mode allow|block, optional layers")
                else:
                    rules.areas.append(area)
        raw_rows = raw.get("hidden_rows", [])
        if not isinstance(raw_rows, list) or not all(isinstance(r, str) for r in raw_rows):
            errors.append("rules.hidden_rows must be a list of property ids")
        else:
            rules.hidden_rows = list(raw_rows)
        return rules, errors

    @staticmethod
    def _read_area(item):
        if not isinstance(item, dict):
            return None
        rect = item.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            return None
        if not (_in(rect[0], -MAX_COORDINATE, MAX_COORDINATE) and _in(rect[1], -MAX_COORDINATE, MAX_COORDINATE)):
            return None
        if not (_in(rect[2], MIN_AREA_SIZE, 2 * MAX_COORDINATE) and _in(rect[3], MIN_AREA_SIZE, 2 * MAX_COORDINATE)):
            return None
        if item.get("mode") not in ("allow", "block"):
            return None
        raw_layers = item.get("layers", [])
        if not isinstance(raw_layers, list) or len(raw_layers) > MAX_LAYER_SPANS:
            return None
        spans = [read_span(s) for s in raw_layers]
        if any(s is None for s in spans):
            return None
        return (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]), item["mode"], merge_spans(spans))

    def allows_layer(self, layer):
        if not self.layers:
            return True
        return any(lo <= layer <= hi for lo, hi in self.layers)

    def area_error(self, x, y, layer, radius):
        """Why a gear (center x, y, outer [radius]) cannot stand there, '' when it can (GearRules.get_gear_area_error)."""
        has_allow, fits = False, False
        for ax, ay, aw, ah, mode, spans in self.areas:
            if spans and not any(lo <= layer <= hi for lo, hi in spans):
                continue
            if mode == "block":
                nx, ny = min(max(x, ax), ax + aw), min(max(y, ay), ay + ah)
                if math.hypot(x - nx, y - ny) < radius - EPSILON:
                    return "gears cannot be placed in the blocked area [%g, %g, %g, %g]" % (ax, ay, aw, ah)
            else:
                has_allow = True
                if (x - radius >= ax - EPSILON and x + radius <= ax + aw + EPSILON
                        and y - radius >= ay - EPSILON and y + radius <= ay + ah + EPSILON):
                    fits = True
        if has_allow and not fits:
            return "gears must stay inside one allowed area"
        return ""


# ----------------------------------------------------------------------------------------------
# The model: links and speeds
# ----------------------------------------------------------------------------------------------
def norm_gear(g):
    x, y = g["position"]
    return {"template": int(g["template"]), "x": float(x), "y": float(y), "layer": int(g.get("layer", 0)),
            "axle": int(g.get("axle", -1)), "id": g.get("id", ""), "fixed": bool(g.get("fixed", False))}


class Sim(object):
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.speed = []         # deg/s per gear (positive = clockwise)
        self.comp = []          # machine id per gear
        self.mesh = set()       # (a, b) pairs that mesh, a < b
        self.edges = []         # (a, b, kind, sign, uses_teeth)


def _name(gears, i):
    return gears[i]["id"] or "#%d" % i


def simulate(T, gears, chains):
    """Links (mesh, axle, chain), checks the geometry and propagates the speeds from the motors."""
    S = Sim()
    n = len(gears)
    ti = [T[g["template"]] for g in gears]
    for a, b in combinations(range(n), 2):
        ga, gb = gears[a], gears[b]
        if ga["layer"] != gb["layer"]:
            continue
        A, B = ti[a], ti[b]
        d = math.hypot(ga["x"] - gb["x"], ga["y"] - gb["y"])
        if A.internal and B.internal:
            S.warnings.append("ring gears %s and %s share a layer: not checked" % (_name(gears, a), _name(gears, b)))
            continue
        ring = A.internal or B.internal
        want = mesh_distance(A, B)
        diff = abs(d - want)
        if can_mesh(A, B) and diff <= MESH_EXACT:
            S.edges.append((a, b, "mesh", 1 if ring else -1, True))
            S.mesh.add((a, b))
        elif can_mesh(A, B) and diff <= MESH_NEAR:
            S.errors.append("gears %s and %s are almost meshed (%.2f px off the mesh distance %.2f): place them exactly"
                            % (_name(gears, a), _name(gears, b), diff, want))
        elif ring:
            S.warnings.append("ring gear clearance between %s and %s is not checked" % (_name(gears, a), _name(gears, b)))
        elif d < A.outer + B.outer + CLEARANCE:
            S.errors.append("gears %s and %s overlap on layer %d: distance %.2f, they need %.2f to be apart%s"
                            % (_name(gears, a), _name(gears, b), ga["layer"], d, A.outer + B.outer + CLEARANCE,
                               " (different tooth sizes cannot mesh)" if A.s != B.s and abs(d - (A.pitch + B.pitch)) <= MESH_NEAR else ""))
    axles = {}
    for i, g in enumerate(gears):
        if g["axle"] >= 0:
            axles.setdefault(g["axle"], []).append(i)
    for axle, members in axles.items():
        if len(members) < 2:
            S.warnings.append("axle %d has a single gear" % axle)
        for a, b in combinations(members, 2):
            if math.hypot(gears[a]["x"] - gears[b]["x"], gears[a]["y"] - gears[b]["y"]) > AXLE_SAME_POSITION:
                S.errors.append("axle %d: gears %s and %s are not at the same position" % (axle, _name(gears, a), _name(gears, b)))
            if gears[a]["layer"] == gears[b]["layer"]:
                S.errors.append("axle %d: gears %s and %s are on the same layer" % (axle, _name(gears, a), _name(gears, b)))
            S.edges.append((a, b, "axle", 1, False))
    seen_in_chain = set()
    for ci, c in enumerate(chains):
        links = c.get("links", [])
        idx = [l.get("gear") for l in links]
        if len(links) < 2 or any(not isinstance(i, int) or not 0 <= i < n for i in idx):
            S.errors.append("chain %d needs at least 2 links with valid gear indices" % ci)
            continue
        if len(set(idx)) != len(idx) or seen_in_chain & set(idx):
            S.errors.append("chain %d: a gear is in two chains or twice in one" % ci)
            continue
        seen_in_chain |= set(idx)
        sides = [1 if l.get("side") == "inside" else -1 for l in links]
        if len({gears[i]["layer"] for i in idx}) > 1:
            S.errors.append("chain %d: gears on different layers" % ci)
        if len({ti[i].s for i in idx}) > 1:
            S.errors.append("chain %d: tooth sizes differ" % ci)
        if any(ti[i].internal for i in idx):
            S.errors.append("chain %d: ring gear in a chain" % ci)
        S.warnings.append("chain %d: belt geometry (wrap, blocking) is NOT checked here, load it in the editor" % ci)
        for k in range(len(idx)):
            S.edges.append((idx[k], idx[(k + 1) % len(idx)], "chain", sides[k] * sides[(k + 1) % len(idx)], True))
    adj = [[] for _ in range(n)]
    for a, b, kind, sign, teeth in S.edges:
        adj[a].append((b, sign, teeth))
        adj[b].append((a, sign, teeth))
    speed = [0.0] * n
    comp = [-1] * n
    for m in range(n):
        if not ti[m].is_motor or comp[m] >= 0:
            continue
        speed[m], comp[m] = ti[m].free, m
        stack = [m]
        while stack:
            a = stack.pop()
            for b, sign, teeth in adj[a]:
                v = speed[a] * sign * (float(ti[a].n) / float(ti[b].n) if teeth else 1.0)
                if comp[b] >= 0:
                    if abs(speed[b] - v) > 1e-6 * max(1.0, abs(v), abs(speed[b])):
                        S.errors.append("JAM: gear %s would turn at %.3f and %.3f deg/s (odd mesh loop or conflicting ratios)"
                                        % (_name(gears, b), speed[b], v))
                    continue
                speed[b], comp[b] = v, m
                if ti[b].is_motor:
                    if abs(v - ti[b].free) > 1e-6 * max(1.0, abs(v)):
                        S.errors.append("two motors in one machine disagree: %s is pushed to %.3f but is a motor of %.3f deg/s"
                                        % (_name(gears, b), v, ti[b].free))
                    else:
                        S.warnings.append("two motors drive one machine (%s): torque sharing is not simulated" % _name(gears, b))
                stack.append(b)
    for i in range(n):
        if comp[i] < 0:
            comp[i] = -1000 - i          # its own stationary machine
        if ti[i].type in ("ONE_WAY", "SLIP") and speed[i] != 0.0:
            S.warnings.append("%s gear %s: its locking/slipping is NOT simulated" % (ti[i].type, _name(gears, i)))
    S.speed, S.comp = speed, comp
    return S


# ----------------------------------------------------------------------------------------------
# Puzzle schema and objectives
# ----------------------------------------------------------------------------------------------
def check_schema(p):
    """Structural errors of a puzzle dict (what GearPuzzle.from_text would refuse, and a few kit limits)."""
    E = []
    if not isinstance(p, dict):
        return ["the puzzle must be a JSON object"]
    if p.get("format") != FORMAT:
        E.append("format must be %d" % FORMAT)
    if not isinstance(p.get("title", ""), str) or len(p.get("title", "")) > MAX_TITLE:
        E.append("title must be text of at most %d characters" % MAX_TITLE)
    if not isinstance(p.get("description", ""), str) or len(p.get("description", "")) > MAX_DESCRIPTION:
        E.append("description must be text of at most %d characters" % MAX_DESCRIPTION)
    templates = p.get("templates")
    if not isinstance(templates, list) or not 1 <= len(templates) <= MAX_TEMPLATES:
        return E + ["templates must be a list of 1..%d templates" % MAX_TEMPLATES]
    for i, t in enumerate(templates):
        if not isinstance(t, dict):
            E.append("template %d is not an object" % i)
            continue
        if t.get("type", "SPUR") not in TYPE_NAMES:
            E.append("template %d: type must be one of %s" % (i, TYPE_NAMES))
        if not _in(t.get("tooth_count", 16), MIN_TOOTH_COUNT, MAX_TOOTH_COUNT) or float(t.get("tooth_count", 16)) != round(float(t.get("tooth_count", 16))):
            E.append("template %d: tooth_count must be a whole number %d..%d" % (i, MIN_TOOTH_COUNT, MAX_TOOTH_COUNT))
        if not _in(t.get("tooth_size", 10), 1, MAX_TOOTH_SIZE) or float(t.get("tooth_size", 10)) != round(float(t.get("tooth_size", 10))):
            E.append("template %d: tooth_size must be a whole number 1..%d" % (i, MAX_TOOTH_SIZE))
        for key in ("motor_free_speed", "motor_stall_torque", "resistance", "min_speed", "rim_ratio"):
            if not _num(t.get(key, 0.0)):
                E.append("template %d: %s must be a number" % (i, key))
        for key in ("fill_color", "hub_color", "outline_color"):
            v = t.get(key, "000000ff")
            if not isinstance(v, str) or not re.match(r"^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$", v):
                E.append("template %d: %s must be a color like '5abcdaff'" % (i, key))
    gears = p.get("gears")
    if not isinstance(gears, list) or len(gears) > MAX_GEARS:
        return E + ["gears must be a list of at most %d gears" % MAX_GEARS]
    names = {}
    for i, g in enumerate(gears):
        if not isinstance(g, dict):
            E.append("gear %d is not an object" % i)
            continue
        if not _in(g.get("template"), 0, len(templates) - 1) or float(g.get("template")) != round(float(g.get("template"))):
            E.append("gear %d uses a template that does not exist" % i)
        pos = g.get("position")
        if not isinstance(pos, list) or len(pos) != 2 or not _in(pos[0], -MAX_COORDINATE, MAX_COORDINATE) or not _in(pos[1], -MAX_COORDINATE, MAX_COORDINATE):
            E.append("gear %d needs position [x, y] within +-%d" % (i, MAX_COORDINATE))
        if not _is_layer(g.get("layer", 0)):
            E.append("gear %d: layer must be a whole number -%d..%d" % (i, MAX_LAYER, MAX_LAYER))
        if not _in(g.get("axle", -1), -1, MAX_AXLE_ID) or float(g.get("axle", -1)) != round(float(g.get("axle", -1))):
            E.append("gear %d: axle must be -1 or 0..%d" % (i, MAX_AXLE_ID))
        if not _in(g.get("rotation", 0.0), -1000.0, 1000.0):
            E.append("gear %d: rotation out of range" % i)
        gid = g.get("id", "")
        if not isinstance(gid, str) or (gid and not NAME_RE.match(gid)):
            E.append("gear %d: name '%s' must match [A-Za-z][A-Za-z0-9_]{0,15}" % (i, gid))
        elif gid:
            if gid in names:
                E.append("gear name '%s' is used twice" % gid)
            names[gid] = i
    if E:
        return E
    chains = p.get("chains", [])
    if not isinstance(chains, list) or len(chains) > 64:
        E.append("chains must be a list of at most 64 chains")
    else:
        for ci, c in enumerate(chains):
            links = c.get("links") if isinstance(c, dict) else None
            if not isinstance(links, list) or len(links) < 2 or not all(isinstance(l, dict) and isinstance(l.get("gear"), int) and l.get("side") in ("inside", "outside") for l in links):
                E.append("chain %d needs links [{gear: index, side: inside|outside}, ...] (at least 2)" % ci)
    objs = p.get("objectives")
    if not isinstance(objs, list) or not 1 <= len(objs) <= KIT_MAX_OBJECTIVES:
        E.append("objectives must be a list of 1..%d objectives" % KIT_MAX_OBJECTIVES)
    else:
        for oi, o in enumerate(objs):
            if not isinstance(o, dict) or not isinstance(o.get("condition"), dict) or not isinstance(o.get("required", True), bool) or not isinstance(o.get("title", ""), str):
                E.append("objective %d needs a condition object, required true|false and a title text" % oi)
            else:
                E.extend("objective %d: %s" % (oi, m) for m in _check_node(o["condition"], names, 0))
        if not any(isinstance(o, dict) and o.get("required", True) for o in objs):
            E.append("at least one objective must be required")
    view = p.get("view")
    if view is not None:
        ok = isinstance(view, dict) and isinstance(view.get("position"), list) and len(view["position"]) == 2 \
            and all(_in(v, -MAX_COORDINATE, MAX_COORDINATE) for v in view["position"]) and _is_layer(view.get("layer", 0))
        sz = view.get("size") if isinstance(view, dict) else None
        ok = ok and sz is not None and isinstance(sz, list) and len(sz) == 2 and all(_in(v, MIN_VIEW_SIZE, MAX_VIEW_SIZE) for v in sz)
        if not ok:
            E.append("view needs position [x, y], size [w, h] (%g..%g) and a layer" % (MIN_VIEW_SIZE, MAX_VIEW_SIZE))
    _, rule_errors = Rules.parse(p.get("rules"), len(templates))
    E.extend(rule_errors)
    return E


def _check_node(node, names, depth):
    if depth > 8:
        return ["condition is nested too deep"]
    op = node.get("op")
    if op in ("all", "any"):
        kids = node.get("children")
        if not isinstance(kids, list) or not 1 <= len(kids) <= 8 or not all(isinstance(k, dict) for k in kids):
            return ["'%s' needs 1..8 children" % op]
        return [m for k in kids for m in _check_node(k, names, depth + 1)]
    if op in ("not", "hold"):
        kids = node.get("children")
        if not isinstance(kids, list) or len(kids) != 1 or not isinstance(kids[0], dict):
            return ["'%s' needs exactly one child" % op]
        if op == "hold" and not _in(node.get("seconds"), 0.0, 60.0):
            return ["'hold' needs seconds 0..60"]
        return _check_node(kids[0], names, depth + 1)
    if op == "compare":
        if node.get("property") != "speed" or node.get("cmp") != "approx":
            return ["the kit only supports compare with property 'speed' and cmp 'approx'"]
        if node.get("gear") not in names:
            return ["refers to gear '%s', which is not a named gear of the puzzle" % node.get("gear")]
        if not _num(node.get("value")):
            return ["compare needs a numeric value"]
        if "tolerance" in node:
            return ["'tolerance' is outside what the kit supports (the default is 1%% of the value, at least 0.5 deg/s)"]
        return []
    return ["unsupported condition '%s' (the kit supports compare, all, any, not, hold)" % op]


def eval_objectives(objs, sim, gears):
    """One bool per objective (hold counts as its child: the check is for the settled state)."""
    ids = {g["id"]: i for i, g in enumerate(gears) if g["id"]}

    def ev(node):
        op = node["op"]
        if op == "all":
            return all(ev(k) for k in node["children"])
        if op == "any":
            return any(ev(k) for k in node["children"])
        if op == "not":
            return not ev(node["children"][0])
        if op == "hold":
            return ev(node["children"][0])
        v = sim.speed[ids[node["gear"]]]
        tol = max(0.5, 0.01 * abs(float(node["value"])))
        return abs(v - float(node["value"])) <= tol

    return [bool(ev(o["condition"])) for o in objs]


def is_won(objs, results):
    required = [r for o, r in zip(objs, results) if o.get("required", True)]
    return bool(required) and all(required)


class Analysis(object):
    def __init__(self):
        self.errors, self.warnings = [], []
        self.speeds, self.results, self.won = {}, [], False
        self.remaining, self.sim, self.gears, self.T, self.rules = {}, None, [], [], None


def analyse(p):
    """Everything the offline model can say about one puzzle dict."""
    A = Analysis()
    A.errors = check_schema(p)
    if A.errors:
        return A
    A.T = [TI(t) for t in p["templates"]]
    A.gears = [norm_gear(g) for g in p["gears"]]
    A.rules, _ = Rules.parse(p.get("rules"), len(A.T))
    sim = simulate(A.T, A.gears, p.get("chains", []))
    A.sim = sim
    A.errors += sim.errors
    A.warnings += sim.warnings
    A.speeds = {g["id"]: sim.speed[i] for i, g in enumerate(A.gears) if g["id"]}
    A.results = eval_objectives(p["objectives"], sim, A.gears)
    A.won = is_won(p["objectives"], A.results)
    unfixed = {}
    for g in A.gears:
        if not g["fixed"]:
            unfixed[g["template"]] = unfixed.get(g["template"], 0) + 1
    A.remaining = {t: c - unfixed.get(t, 0) for t, c in A.rules.limits.items()}
    return A


def check_solution(puz, sol):
    """Errors in how [sol] was made from [puz]: only legal gears added, within the limits, layers and areas."""
    E = []
    if sol.get("templates") != puz.get("templates"):
        E.append("the solution changed the templates")
    if sol.get("rules") != puz.get("rules"):
        E.append("the solution changed the rules")
    if sol.get("objectives") != puz.get("objectives"):
        E.append("the solution changed the objectives")
    pg, sg = puz["gears"], sol["gears"]
    if len(sg) <= len(pg):
        return E + ["the solution adds no gears"]
    added_axles = {g.get("axle", -1) for g in sg[len(pg):] if g.get("axle", -1) >= 0}
    for i, (a, b) in enumerate(zip(pg, sg)):
        a2, b2 = dict(a), dict(b)
        for k in ("rotation",):
            a2.pop(k, None)
            b2.pop(k, None)
        if a2.get("axle", -1) == -1 and b2.get("axle", -1) in added_axles:
            b2["axle"] = -1          # a new gear keyed onto an existing gear's axle: the editor allows that
        if a2 != b2:
            E.append("gear %d of the puzzle was changed in the solution" % i)
    if E:
        return E
    T = [TI(t) for t in puz["templates"]]
    rules, _ = Rules.parse(puz.get("rules"), len(T))
    lim, used = rules.limits, {}
    for g in sg:
        if not g.get("fixed", False):
            used[g["template"]] = used.get(g["template"], 0) + 1
    for t, c in used.items():
        if t in lim and c > lim[t]:
            E.append("template %d: %d unfixed gears but the limit is %d" % (t, c, lim[t]))
    for g in sg[len(pg):]:
        ng = norm_gear(g)
        if g.get("fixed", False):
            E.append("an added gear must not be fixed")
        if g.get("id"):
            E.append("added gears get automatic names: remove 'id'")
        if not rules.place:
            E.append("rules forbid placing gears but the solution adds one")
        if not rules.allows_layer(ng["layer"]):
            E.append("an added gear is on layer %d, which the rules lock" % ng["layer"])
        msg = rules.area_error(ng["x"], ng["y"], ng["layer"], T[ng["template"]].outer)
        if msg:
            E.append("an added gear: " + msg)
    if len(sol.get("chains", [])) > len(puz.get("chains", [])) and not rules.chain:
        E.append("rules forbid chains but the solution adds one")
    return E


# ----------------------------------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------------------------------
class Template(object):
    """A gear type. Make it with Puzzle.template()."""

    def __init__(self, index, props):
        self.index = index
        self.props = props
        self.info = TI(props)

    @property
    def teeth(self):
        return self.info.n

    @property
    def size(self):
        return self.info.s

    @property
    def pitch(self):
        return self.info.pitch

    @property
    def outer(self):
        return self.info.outer

    @property
    def is_motor(self):
        return self.info.is_motor


class Gear(object):
    """A gear of the puzzle (Puzzle.gear) or of its intended solution (Puzzle.player_gear)."""

    def __init__(self, template, pos, layer, axle, gid, fixed):
        self.template, self.layer, self.axle, self.id, self.fixed = template, layer, axle, gid, fixed
        self.x, self.y = _r2(pos[0]), _r2(pos[1])

    @property
    def pos(self):
        return [self.x, self.y]

    def to_dict(self):
        d = {"template": self.template.index, "position": [self.x, self.y], "rotation": 0.0,
             "layer": self.layer, "axle": self.axle}
        if self.id:
            d["id"] = self.id
        if self.fixed:
            d["fixed"] = True
        return d


def speed_node(gear, value):
    """The gear turns at [value] deg/s (positive = clockwise), within 1% (at least 0.5)."""
    return {"op": "compare", "gear": gear.id if isinstance(gear, Gear) else gear, "property": "speed",
            "cmp": "approx", "value": float(value)}


def all_of(*nodes):
    return {"op": "all", "children": list(nodes)}


def any_of(*nodes):
    return {"op": "any", "children": list(nodes)}


def not_of(node):
    return {"op": "not", "children": [node]}


def hold_of(seconds, node):
    return {"op": "hold", "seconds": float(seconds), "children": [node]}


class Puzzle(object):
    """One level: the puzzle the player gets plus the gears of its intended solution."""

    def __init__(self, title, description=""):
        self.title, self.description = title, description
        self.templates, self.gears, self.stock = [], [], []
        self.objectives, self.areas, self.view = [], [], None
        self.limits, self.layer_spans = {}, []
        self.allow_move = self.allow_place = self.allow_chain = True

    # -- templates and gears
    def template(self, teeth, size=10, motor_speed=0.0, motor_torque=None, color="gray"):
        """A spur gear type. [motor_speed] != 0 makes it a motor (deg/s, positive = clockwise), torque defaults to 1."""
        if not isinstance(teeth, int) or isinstance(teeth, bool) or not MIN_TOOTH_COUNT <= teeth <= MAX_TOOTH_COUNT:
            raise KitError("teeth must be a whole number %d..%d, got %r" % (MIN_TOOTH_COUNT, MAX_TOOTH_COUNT, teeth))
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_TOOTH_SIZE:
            raise KitError("size must be a whole number 1..%d, got %r" % (MAX_TOOTH_SIZE, size))
        if not _num(motor_speed):
            raise KitError("motor_speed must be a number")
        if len(self.templates) >= MAX_TEMPLATES:
            raise KitError("too many templates")
        base = PALETTE.get(color, color)
        if not re.match(r"^[0-9a-fA-F]{6}$", base):
            raise KitError("color must be one of %s or 'rrggbb'" % sorted(PALETTE))
        base = base.lower()
        props = dict(TEMPLATE_DEFAULTS)
        props.update({"tooth_count": teeth, "tooth_size": size, "fill_color": base + "ff",
                      "hub_color": "6b7380ff" if base == PALETTE["gray"] else _darken_hex(base, 0.3) + "ff"})
        if motor_speed != 0:
            props["motor_free_speed"] = float(motor_speed)
            props["motor_stall_torque"] = 1.0 if motor_torque is None else float(motor_torque)
        t = Template(len(self.templates), props)
        self.templates.append(t)
        return t

    def _check_gear(self, template, pos, layer, axle, gid):
        if not isinstance(template, Template) or template not in self.templates:
            raise KitError("the gear needs a template made by this puzzle")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2 and all(_in(v, -MAX_COORDINATE, MAX_COORDINATE) for v in pos)):
            raise KitError("position must be (x, y) within +-%d" % MAX_COORDINATE)
        if not isinstance(layer, int) or isinstance(layer, bool) or not -MAX_LAYER <= layer <= MAX_LAYER:
            raise KitError("layer must be a whole number -%d..%d" % (MAX_LAYER, MAX_LAYER))
        if not isinstance(axle, int) or isinstance(axle, bool) or not -1 <= axle <= MAX_AXLE_ID:
            raise KitError("axle must be -1 or 0..%d" % MAX_AXLE_ID)
        if gid and not NAME_RE.match(gid):
            raise KitError("gear name %r must match [A-Za-z][A-Za-z0-9_]{0,15}" % gid)
        if gid and any(g.id == gid for g in self.gears):
            raise KitError("gear name %r is already used" % gid)

    def gear(self, template, pos, layer=0, id="", fixed=True, axle=-1):
        """A gear the player finds on the board. Fixed by default (the player cannot move or delete it)."""
        self._check_gear(template, pos, layer, axle, id)
        g = Gear(template, pos, layer, axle, id, fixed)
        self.gears.append(g)
        return g

    def player_gear(self, template, pos, layer=0, axle=-1):
        """A gear of the intended solution: what the player places. Never fixed, never named."""
        self._check_gear(template, pos, layer, axle, "")
        g = Gear(template, pos, layer, axle, "", False)
        self.stock.append(g)
        return g

    def new_axle(self):
        """A free axle id (not used by any gear of the puzzle or of the solution)."""
        used = [g.axle for g in self.gears + self.stock]
        return max(used + [-1]) + 1

    # -- rules
    def limit(self, template, count):
        """The most unfixed gears of [template] the player can have at once. 0 hides the template from the player."""
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= MAX_LIMIT:
            raise KitError("a limit is a whole number 0..%d" % MAX_LIMIT)
        self.limits[template.index] = count

    def lock_layers(self, *spans):
        """The player can only work on these layers: ints or (first, last) pairs. Nothing given = every layer."""
        parsed = [read_span(list(s) if isinstance(s, tuple) else s) for s in spans]
        if any(s is None for s in parsed):
            raise KitError("lock_layers takes whole numbers or (first, last) pairs")
        self.layer_spans = merge_spans(parsed)

    def set_rules(self, move=None, place=None, chain=None):
        """What the player may do: move gears, place/delete gears, build chains. None leaves a rule as it is.
        Kit levels must call set_rules(chain=False): the kit does not model chains."""
        if move is not None:
            self.allow_move = bool(move)
        if place is not None:
            self.allow_place = bool(place)
        if chain is not None:
            self.allow_chain = bool(chain)

    def _area(self, mode, x, y, w, h, layers):
        spans = merge_spans([read_span(list(s) if isinstance(s, tuple) else s) for s in (layers or [])])
        if len(self.areas) >= MAX_AREAS or w < MIN_AREA_SIZE or h < MIN_AREA_SIZE:
            raise KitError("an area needs w, h >= %g and there can be at most %d" % (MIN_AREA_SIZE, MAX_AREAS))
        self.areas.append((_r2(x), _r2(y), _r2(w), _r2(h), mode, spans))

    def allow_area(self, x, y, w, h, layers=None):
        """Gears of [layers] (all when None) must stand entirely inside ONE allow area, when one applies to them."""
        self._area("allow", x, y, w, h, layers)

    def block_area(self, x, y, w, h, layers=None):
        """Gears of [layers] (all when None) must not overlap this rectangle. Block beats allow."""
        self._area("block", x, y, w, h, layers)

    # -- objectives
    def objective(self, node, title="", required=True):
        self.objectives.append({"condition": node, "required": bool(required), "title": title})

    def goal_speed(self, gear, value, title="", required=True, hold=1.0):
        """Objective: [gear] turns at [value] deg/s, kept for [hold] seconds (0 = no hold)."""
        node = speed_node(gear, value)
        self.objective(hold_of(hold, node) if hold and hold > 0 else node, title, required)

    # -- output
    def _rules_dict(self):
        r = {}
        if not self.allow_move:
            r["move"] = False
        if not self.allow_place:
            r["place"] = False
        if not self.allow_chain:
            r["chain"] = False
        if self.layer_spans:
            r["layers"] = spans_to_data(self.layer_spans)
        if self.limits:
            r["limits"] = [{"template": i, "count": self.limits[i]} for i in sorted(self.limits)]
        if self.areas:
            r["areas"] = [dict([("rect", [x, y, w, h]), ("mode", mode)] + ([("layers", spans_to_data(spans))] if spans else []))
                          for x, y, w, h, mode, spans in self.areas]
        return r

    def to_dict(self, with_solution=False):
        gears = [g.to_dict() for g in self.gears] + ([g.to_dict() for g in self.stock] if with_solution else [])
        d = {"format": FORMAT, "title": self.title, "templates": [dict(t.props) for t in self.templates],
             "gears": gears, "chains": [], "objectives": json.loads(json.dumps(self.objectives))}
        rules = self._rules_dict()
        if rules:
            d["rules"] = rules
        if self.description:
            d["description"] = self.description
        if self.view:
            d["view"] = json.loads(json.dumps(self.view))
        return d

    def solution_dict(self):
        return self.to_dict(with_solution=True)

    def fit_view(self, margin=160.0, aspect=16.0 / 9.0, layer=None, include_solution=True):
        """Frames every gear (the solution's too) plus [margin] px, widened to [aspect]. The start view promises
        the player this region is visible, so leave room for the panels that cover the board."""
        items = self.gears + (self.stock if include_solution else [])
        if not items:
            raise KitError("nothing to frame")
        lo_x = min(g.x - g.template.outer for g in items)
        hi_x = max(g.x + g.template.outer for g in items)
        lo_y = min(g.y - g.template.outer for g in items)
        hi_y = max(g.y + g.template.outer for g in items)
        for x, y, w, h, mode, spans in self.areas:
            lo_x, hi_x, lo_y, hi_y = min(lo_x, x), max(hi_x, x + w), min(lo_y, y), max(hi_y, y + h)
        w, h = hi_x - lo_x + 2 * margin, hi_y - lo_y + 2 * margin
        if w / h < aspect:
            w = h * aspect
        else:
            h = w / aspect
        if layer is None:
            named = {g.id: g for g in self.gears if g.id}
            goal = None
            for o in self.objectives:
                stack = [o["condition"]]
                while stack and goal is None:
                    node = stack.pop()
                    if node.get("op") == "compare":
                        goal = named.get(node["gear"])
                    stack.extend(node.get("children", []))
            layer = goal.layer if goal else 0
        self.view = {"position": [_r2((lo_x + hi_x) / 2.0), _r2((lo_y + hi_y) / 2.0)],
                     "size": [round(w, 1), round(h, 1)], "layer": int(layer)}
        return self.view

    def write(self, folder, name):
        """Writes <name>.json and <name>.solution.json (the file that already contains the intended solution)."""
        os.makedirs(folder, exist_ok=True)
        paths = []
        for suffix, data in ((".json", self.to_dict()), (".solution.json", self.solution_dict())):
            path = os.path.join(folder, name + suffix)
            with open(path, "w") as f:
                f.write(dump(data))
            paths.append(path)
        return paths


def dump(data):
    """JSON text the way the game writes it (tabs, sorted keys)."""
    return json.dumps(data, indent="\t", sort_keys=True) + "\n"


def kit_errors(p):
    """Extra rules for levels made with this kit (the game itself is more permissive)."""
    E = []
    T = p.get("templates", [])
    rules, _ = Rules.parse(p.get("rules"), len(T))
    used_fixed = {g["template"] for g in p.get("gears", []) if g.get("fixed")}
    for i, t in enumerate(T):
        info = TI(t)
        if info.type != "SPUR":
            E.append("template %d: only SPUR gears are supported by the kit levels (ring, one-way and slip are not modelled)" % i)
        if i not in rules.limits:
            E.append("template %d has no limit, so it is offered without limit: call p.limit(t, n) (0 hides it from the player)" % i)
        if info.is_motor and rules.limits.get(i, 0) != 0:
            E.append("template %d is a motor: it must be hidden with p.limit(t, 0)" % i)
    if rules.chain:
        E.append("the player can build chains, which the kit does not model (a chain could bridge any gap): call p.set_rules(chain=False)")
    if not any(TI(t).is_motor and i in used_fixed for i, t in enumerate(T)):
        E.append("the puzzle needs a fixed gear that uses a motor template")
    named = {g.get("id"): g for g in p.get("gears", []) if g.get("id")}
    for o in p.get("objectives", []):
        stack = [o.get("condition", {})]
        while stack:
            node = stack.pop()
            if node.get("op") == "compare" and node.get("gear") in named and not named[node["gear"]].get("fixed"):
                E.append("objective gear '%s' must be fixed (the player could delete it)" % node["gear"])
            stack.extend(node.get("children", []))
    return E


# ----------------------------------------------------------------------------------------------
# Solver: how can the player place the stock gears?
# ----------------------------------------------------------------------------------------------
class SolveResult(object):
    def __init__(self):
        self.solutions = []     # dicts: depth, placed, keyed, family
        self.families = {}      # family signature -> first solution
        self.min_depth = None
        self.decoys = {}        # rounded speed of the goal gear -> [count, example state]
        self.states = 0
        self.complete = True    # False when the state or time budget ended the search
        self.redundant = 0      # winning states that only add a gear that does nothing (not counted as solutions)
        self.notes = []
        self.stock = {}
        self.base = []
        self.error = ""


def _gears_of(base, keyed, placed):
    gears = []
    for i, g in enumerate(base):
        h = dict(g)
        if i in keyed:
            h["axle"] = keyed[i]
        gears.append(h)
    for t, x, y, layer, axle in placed:
        gears.append({"template": t, "x": x, "y": y, "layer": layer, "axle": axle, "id": "", "fixed": False})
    return gears


def _goal_ids(objs):
    """Gear names that required objectives ask to MOVE (speed target other than 0), in order."""
    out = []
    for o in objs:
        if not o.get("required", True):
            continue
        stack = [o["condition"]]
        while stack:
            node = stack.pop(0)
            if node.get("op") == "compare" and abs(float(node["value"])) > 1e-9 and node["gear"] not in out:
                out.append(node["gear"])
            stack.extend(node.get("children", []))
    return out


def _quick_ok(T, gears, x, y, layer, ti):
    """False when a new gear at (x, y) would overlap a gear of its layer (meshing ones are fine)."""
    for g in gears:
        if g["layer"] != layer:
            continue
        o = T[g["template"]]
        d = math.hypot(x - g["x"], y - g["y"])
        if o.internal:
            continue
        if can_mesh(o, ti) and abs(d - mesh_distance(o, ti)) <= MESH_NEAR:
            continue
        if d < o.outer + ti.outer + CLEARANCE:
            return False
    return True


def _candidates(T, gears, ti, layer, angles):
    """Where a gear of [ti] could go on [layer]: meshing a gear at sampled angles, meshing two gears at once,
    or stacked on the axle of a gear of another layer. Returns (x, y, stack_index or -1) tuples."""
    out = {}

    def add(x, y, stack=-1):
        out[(round(x, 2), round(y, 2), stack)] = None

    partners = [i for i, g in enumerate(gears) if g["layer"] == layer and not T[g["template"]].internal
                and can_mesh(T[g["template"]], ti)]
    centers = {(g["x"], g["y"]) for g in gears}
    for i in partners:
        g = gears[i]
        r = T[g["template"]].pitch + ti.pitch
        for ang in angles:
            add(g["x"] + r * math.cos(ang), g["y"] + r * math.sin(ang))
        for ox, oy in centers:
            if (ox, oy) != (g["x"], g["y"]):
                ang = math.atan2(oy - g["y"], ox - g["x"])
                add(g["x"] + r * math.cos(ang), g["y"] + r * math.sin(ang))
    for i, j in combinations(partners, 2):
        gi, gj = gears[i], gears[j]
        for pt in circle_intersections((gi["x"], gi["y"]), T[gi["template"]].pitch + ti.pitch,
                                       (gj["x"], gj["y"]), T[gj["template"]].pitch + ti.pitch):
            add(pt[0], pt[1])
    for e, g in enumerate(gears):
        if g["layer"] != layer:
            add(g["x"], g["y"], e)
    return list(out)


def _family(T, gears, sim, n_base):
    """A rough signature of HOW a solution connects things (not where exactly the gears stand)."""
    def label(i):
        return gears[i]["id"] or "%dt@L%d" % (T[gears[i]["template"]].n, gears[i]["layer"])
    placed = sorted(label(i) for i in range(n_base, len(gears)))
    edges = sorted((min(label(a), label(b)), max(label(a), label(b)), kind) for a, b, kind, s, t in sim.edges
                   if a >= n_base or b >= n_base)
    return (tuple(placed), tuple(edges))


def solve(p, angle_step=30.0, max_states=400000, time_limit=10.0, extra_layers=(), unlimited_stock=2):
    """Searches the ways to place the stock gears. Any solution it finds is valid in the offline model; not
    finding one proves nothing (positions are sampled at [angle_step] degrees plus exact two-gear fits)."""
    R = SolveResult()
    A = analyse(p)
    if A.errors:
        R.error = "the puzzle has errors, fix them first"
        return R
    T, base, rules, objs = A.T, A.gears, A.rules, p["objectives"]
    chains = p.get("chains", [])
    start = time.time()
    unfixed = {}
    for g in base:
        if not g["fixed"]:
            unfixed[g["template"]] = unfixed.get(g["template"], 0) + 1
    for i, t in enumerate(T):
        if t.type != "SPUR":
            R.notes.append("template %d (%s) is not searched" % (i, t.type))
            continue
        lim = rules.limits.get(i)
        left = unlimited_stock if lim is None else lim - unfixed.get(i, 0)
        if lim is None:
            R.notes.append("template %d has no limit: the search assumes %d of it" % (i, unlimited_stock))
        if not rules.place:
            left = 0
        if left > 0:
            R.stock[i] = left
    total = sum(R.stock.values())
    R.base = base
    layers = sorted({g["layer"] for g in base} | set(extra_layers))
    layers = [l for l in range(layers[0], layers[-1] + 1) if rules.allows_layer(l)] if layers else [0]
    angles = [math.radians(a * angle_step) for a in range(int(round(360.0 / angle_step)))]
    goals = _goal_ids(objs)
    ids = {g["id"]: i for i, g in enumerate(base) if g["id"]}
    goal_idx = [ids[g] for g in goals if g in ids]
    visited = set()
    frontier = [((), {})]
    seen_families = set()
    for depth in range(1, total + 1):
        nxt = []
        for placed, keyed in frontier:
            gears = _gears_of(base, keyed, placed)
            used = {}
            for t, x, y, l, a in placed:
                used[t] = used.get(t, 0) + 1
            for t_idx, count in R.stock.items():
                if used.get(t_idx, 0) >= count:
                    continue
                ti = T[t_idx]
                for layer in layers:
                    for x, y, stack in _candidates(T, gears, ti, layer, angles):
                        if time.time() - start > time_limit or R.states >= max_states:
                            R.complete = False
                            return _finish(R, p)
                        if abs(x) > MAX_COORDINATE or abs(y) > MAX_COORDINATE or rules.area_error(x, y, layer, ti.outer):
                            continue
                        if not _quick_ok(T, gears, x, y, layer, ti):
                            continue
                        axle, new_keyed, new_placed = -1, keyed, placed
                        if stack >= 0:
                            e = gears[stack]
                            if e["axle"] >= 0:
                                if any(g["axle"] == e["axle"] and g["layer"] == layer for g in gears):
                                    continue
                                axle = e["axle"]
                            else:
                                axle = max([g["axle"] for g in gears] + [-1]) + 1
                                if stack < len(base):
                                    new_keyed = dict(keyed)
                                    new_keyed[stack] = axle
                                else:
                                    k = stack - len(base)
                                    t0, x0, y0, l0, a0 = placed[k]
                                    new_placed = placed[:k] + ((t0, x0, y0, l0, axle),) + placed[k + 1:]
                        new_placed = new_placed + ((t_idx, x, y, layer, axle),)
                        key = (frozenset((t, round(px, 1), round(py, 1), l, a >= 0) for t, px, py, l, a in new_placed),
                               frozenset(new_keyed))
                        if key in visited:
                            continue
                        visited.add(key)
                        R.states += 1
                        g2 = _gears_of(base, new_keyed, new_placed)
                        sim = simulate(T, g2, chains)
                        if sim.errors:
                            continue
                        new_i = len(g2) - 1
                        if not any(new_i in (a, b) for a, b, k_, s_, t_ in sim.edges):
                            continue
                        results = eval_objectives(objs, sim, g2)
                        if is_won(objs, results):
                            if _has_winning_subset(T, base, new_keyed, new_placed, objs, chains):
                                R.redundant += 1
                                continue
                            fam = _family(T, g2, sim, len(base))
                            sol = {"depth": depth, "placed": new_placed, "keyed": new_keyed, "family": fam}
                            R.solutions.append(sol)
                            R.families.setdefault(fam, sol)
                            if R.min_depth is None:
                                R.min_depth = depth
                            continue
                        if goal_idx and all(abs(sim.speed[gi]) > 1e-9 for gi in goal_idx):
                            rec = R.decoys.setdefault(tuple(round(sim.speed[gi], 3) for gi in goal_idx), [0, (new_placed, new_keyed)])
                            rec[0] += 1
                        if depth < total and not _hopeless(T, g2, sim, goal_idx, R.stock, new_placed):
                            nxt.append((new_placed, new_keyed))
        frontier = nxt
        if not frontier:
            break
    return _finish(R, p)


def _has_winning_subset(T, base, keyed, placed, objs, chains):
    """True when taking one placed gear away still wins (so that gear is only along for the ride)."""
    for k in range(len(placed)):
        gears = _gears_of(base, keyed, placed[:k] + placed[k + 1:])
        sim = simulate(T, gears, chains)
        if not sim.errors and is_won(objs, eval_objectives(objs, sim, gears)):
            return True
    return False


def _hopeless(T, gears, sim, goal_idx, stock, placed):
    """True when the remaining stock cannot bridge the gap between a goal gear and every motor (each gear spans
    at most its own diameter)."""
    motor_comps = {sim.comp[i] for i, g in enumerate(gears) if T[g["template"]].is_motor}
    if not motor_comps or not goal_idx:
        return False
    used = {}
    for t, x, y, l, a in placed:
        used[t] = used.get(t, 0) + 1
    reach = sum(max(c - used.get(t, 0), 0) * 2.0 * T[t].outer for t, c in stock.items())
    for gi in goal_idx:
        if sim.comp[gi] in motor_comps:
            continue
        gap = INF
        for a, ga in enumerate(gears):
            if sim.comp[a] != sim.comp[gi]:
                continue
            for b, gb in enumerate(gears):
                if sim.comp[b] in motor_comps:
                    gap = min(gap, math.hypot(ga["x"] - gb["x"], ga["y"] - gb["y"]) - T[ga["template"]].outer - T[gb["template"]].outer)
        if gap > reach + 1.0:
            return True
    return False


INF = float("inf")


def _finish(R, p):
    return R


def solution_dict_of(p, base_gears, state):
    """The puzzle [p] (dict) with the gears of a solver state added, as a solution file."""
    sol = json.loads(json.dumps(p))
    placed, keyed = state
    for i, axle in keyed.items():
        sol["gears"][i]["axle"] = axle
    for t, x, y, layer, axle in placed:
        sol["gears"].append({"template": t, "position": [_r2(x), _r2(y)], "rotation": 0.0, "layer": layer, "axle": axle})
    return sol


def describe_state(T, state, base):
    placed, keyed = state
    parts = []
    for t, x, y, layer, axle in placed:
        parts.append("%dt on layer %d at (%g, %g)%s" % (T[t].n, layer, _r2(x), _r2(y), " axle %d" % axle if axle >= 0 else ""))
    for i, axle in keyed.items():
        parts.append("(keys %s onto axle %d)" % (base[i]["id"] or "#%d" % i, axle))
    return "; ".join(parts)


# ----------------------------------------------------------------------------------------------
# Report: everything in one call
# ----------------------------------------------------------------------------------------------
def report(p, solve_seconds=8.0, angle_step=30.0, quiet=False, write_dir=None, name=None):
    """Checks a Puzzle (builder object), runs the solver and prints a verdict. Returns a dict with ok, errors,
    warnings and notes. Call it with write_dir and name to also write the two JSON files when it passes."""
    out = []

    def say(line=""):
        out.append(line)

    puz = p.to_dict()
    sol = p.solution_dict() if p.stock else None
    errors, warnings, notes = [], [], []
    say("=== %s ===" % (p.title or "untitled"))
    if p.view is None:
        warnings.append("no start view: call p.fit_view() (the player's camera is otherwise at the origin)")
    if not p.description:
        warnings.append("no description: the intro text the player reads when the level opens")
    A = analyse(puz)
    errors += A.errors
    warnings += A.warnings
    if not A.errors:
        errors += kit_errors(puz)
        say("stock the player has (template: teeth -> left): " + ", ".join(
            "%d: %dt -> %d" % (t, A.T[t].n, c) for t, c in sorted(A.remaining.items())))
        say("start state: speeds %s, objectives %s -> %s" % (
            {k: round(v, 3) for k, v in A.speeds.items()}, A.results, "WON (error)" if A.won else "not won (good)"))
        if A.won:
            errors.append("the puzzle is already won at the start")
    if sol is None:
        errors.append("no intended solution: add the player's gears with p.player_gear(...)")
    elif not A.errors:
        B = analyse(sol)
        errors += B.errors
        warnings += [w for w in B.warnings if w not in warnings]
        errors += check_solution(puz, sol)
        say("intended solution: speeds %s, objectives %s -> %s" % (
            {k: round(v, 3) for k, v in B.speeds.items()}, B.results, "WON" if B.won else "NOT won"))
        if not B.errors and not B.won:
            errors.append("the intended solution does not win")
    if not A.errors:
        extra = sorted({g.layer for g in p.stock})
        R = solve(puz, angle_step=angle_step, time_limit=solve_seconds, extra_layers=extra)
        if not R.complete:
            coarse = solve(puz, angle_step=60.0, time_limit=3.0, extra_layers=extra)
            if (coarse.solutions or coarse.complete) and not R.solutions:
                R = coarse
                notes.append("the %g-degree search ran out of budget; the 60-degree pass was used instead" % angle_step)
        say("search: %d states%s" % (R.states, "" if R.complete else " (stopped by the budget: partial)"))
        total = sum(R.stock.values())
        if R.solutions:
            fams = list(R.families.values())
            say("search found %d solution(s) in %d family(ies); fewest gears: %d of %d in stock" % (
                len(R.solutions), len(fams), R.min_depth, total))
            for f in sorted(fams, key=lambda s: s["depth"])[:4]:
                say("  - %d gear(s): %s" % (f["depth"], describe_state(A.T, (f["placed"], f["keyed"]), R.base)))
            if R.min_depth < total:
                warnings.append("spare stock: a solution exists with %d of the %d gears the player has" % (R.min_depth, total))
            if len(fams) > 1:
                notes.append("%d different ways to win: make sure each is intended (or tighten stock, areas or layers)" % len(fams))
            if any(f["keyed"] for f in fams):
                notes.append("a found solution keys a new gear onto the axle of a FIXED gear: the editor allows it, but check it is intended")
        else:
            say("search found no solution%s" % ("" if R.complete else " before the budget ended"))
            if sol is not None and not errors:
                notes.append("the search did not rediscover the intended solution (positions are sampled): fine if it validated above")
        if R.decoys:
            say("decoys (wrong arrangements that still move the goal gear%s): " % ("s" if len(next(iter(R.decoys))) > 1 else "") + ", ".join(
                "%s deg/s x%d" % (" / ".join("%g" % x for x in v), c[0]) for v, c in sorted(R.decoys.items())[:6]))
        else:
            notes.append("no decoy found: the level may be a plain fitting puzzle with no ratio reasoning")
        for n in R.notes:
            notes.append(n)
    ok = not errors
    for title, items in (("ERRORS", errors), ("WARNINGS", warnings), ("NOTES", notes)):
        if items:
            say("%s:" % title)
            for item in items:
                say("  - " + item)
    say("RESULT: %s" % ("PASS" if ok else "FAIL"))
    if ok and write_dir:
        for path in p.write(write_dir, name or re.sub(r"\W+", "_", p.title.lower()) or "level"):
            say("wrote " + path)
    if not quiet:
        print("\n".join(out))
    return {"ok": ok, "errors": errors, "warnings": warnings, "notes": notes, "text": "\n".join(out)}


def selfcheck():
    """A one-second integrity check. Run it right after pasting the kit into a code cell: it prints KIT OK, or fails
    when the paste was damaged (a missing line, a changed number)."""
    p = Puzzle("selfcheck", "Compound gear.")
    t16 = p.template(16)
    tm = p.template(12, motor_speed=30, color="blue")
    t32 = p.template(32)
    p.gear(t16, (160, 32), layer=1, id="Target")
    p.gear(tm, (-220, 32), id="Motor")
    p.limit(t16, 1)
    p.limit(tm, 0)
    p.limit(t32, 1)
    p.goal_speed("Target", 45)
    p.set_rules(chain=False)
    low = p.player_gear(t16, mesh_pos((-220, 32), 60.0, 80.0, 0), axle=0)
    p.player_gear(t32, low.pos, layer=1, axle=0)
    p.fit_view()
    res = report(p, quiet=True)
    assert res["ok"], res["text"]
    assert "11.25" in res["text"] and "1 family" in res["text"], res["text"]
    assert p.to_dict()["templates"][1]["hub_color"] == "3f8499ff"
    assert dump(p.to_dict()).startswith('{\n\t"chains": [],\n\t"description"')
    print("KIT OK")


# ----------------------------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------------------------
def _load(path):
    with open(path) as f:
        return json.load(f)


def main(argv):
    if len(argv) >= 3 and argv[1] == "check":
        puz = _load(argv[2])
        A = analyse(puz)
        print("errors:", A.errors or "none")
        print("warnings:", A.warnings or "none")
        print("speeds:", {k: round(v, 3) for k, v in A.speeds.items()}, "objectives:", A.results, "won:", A.won)
        bad = bool(A.errors) or A.won
        if len(argv) >= 4:
            sol = _load(argv[3])
            B = analyse(sol)
            errs = B.errors + check_solution(puz, sol)
            print("solution errors:", errs or "none")
            print("solution speeds:", {k: round(v, 3) for k, v in B.speeds.items()}, "won:", B.won)
            bad = bad or bool(errs) or not B.won
        print("RESULT:", "FAIL" if bad else "PASS")
        return 1 if bad else 0
    if len(argv) >= 3 and argv[1] == "solve":
        puz = _load(argv[2])
        angle = float(argv[argv.index("--angle") + 1]) if "--angle" in argv else 30.0
        R = solve(puz, angle_step=angle)
        A = analyse(puz)
        print("error:", R.error) if R.error else None
        print("states %d, complete %s, solutions %d, families %d, fewest gears %s" % (
            R.states, R.complete, len(R.solutions), len(R.families), R.min_depth))
        for f in R.families.values():
            print(" -", describe_state(A.T, (f["placed"], f["keyed"]), R.base))
        print("decoys:", {" / ".join("%g" % x for x in v): c[0] for v, c in sorted(R.decoys.items())})
        if "--write" in argv:
            folder = argv[argv.index("--write") + 1]
            os.makedirs(folder, exist_ok=True)
            for i, f in enumerate(R.families.values()):
                path = os.path.join(folder, "found_%d.json" % (i + 1))
                with open(path, "w") as fh:
                    fh.write(dump(solution_dict_of(puz, R.base, (f["placed"], f["keyed"]))))
                print("wrote", path)
        return 0
    if len(argv) >= 2 and argv[1] == "selftest":
        selfcheck()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
