"""LEVEL 01 - Against the grain  (archetype: idlers / parity)

Design card:
  Teaches:            every gear in a row turns the opposite way of its neighbour, so idlers decide the direction.
  Numbers:            the motor turns +30 deg/s (clockwise); the target must turn -30 (counter-clockwise).
  Intended solution:  two 16-tooth idlers in a straight row between the motor and the target.
  Why the stock is tight: the gap is exactly two idler diameters (2 x 160 px); a bent row is shorter and cannot reach.
  Decoy:              none, this is a tutorial.
"""
try:
    from gear_kit import *
except ImportError:
    pass


def build():
    p = Puzzle("Against the grain", "The motor turns clockwise. Make the target turn the other way, at the same speed. Drag gears from the palette to bridge the gap.")
    motor_t = p.template(16, motor_speed=30, color="blue")
    gear_t = p.template(16)
    motor = p.gear(motor_t, (0, 0), id="Motor")
    p.gear(gear_t, (480, 0), id="Target")
    p.limit(motor_t, 0)
    p.limit(gear_t, 2)
    p.set_rules(chain=False)    # the kit does not model chains
    p.goal_speed("Target", -30, "Turn against the motor")
    first = mesh_pos(motor.pos, motor_t.pitch, gear_t.pitch, 0)
    second = mesh_pos(first, gear_t.pitch, gear_t.pitch, 0)
    p.player_gear(gear_t, first)
    p.player_gear(gear_t, second)
    p.fit_view()
    return p
