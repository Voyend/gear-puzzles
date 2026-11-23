"""LEVEL 02 - Compound gears  (archetype: axle across layers)

Design card:
  Teaches:            two gears on one axle turn together, so a small gear driving a big one multiplies the speed.
  Numbers:            motor 12 teeth at +30 deg/s -> 16t at -22.5 -> (same axle) 32t at -22.5 -> target 16t at +45.
  Intended solution:  a 16-tooth gear on layer 0 meshing the motor, and a 32-tooth gear on layer 1 on the same axle,
                      meshing the target (which stands on layer 1).
  Why the stock is tight: one gear of each size; the target is out of reach of any single gear.
  Decoy:              the same two gears with the 32-tooth on layer 0 and the 16-tooth on layer 1 also bridge the gap,
                      but give the target only 11.25 deg/s. Fitting is not enough: the player must reason about ratios.
"""
try:
    from gear_kit import *
except ImportError:
    pass


def build():
    p = Puzzle("Compound gears", "The target is on another layer. Two gears on one axle can carry the motion over, and speed it up.")
    small_t = p.template(16)
    motor_t = p.template(12, motor_speed=30, color="blue")
    big_t = p.template(32)
    p.gear(small_t, (160, 32), layer=1, id="Target")
    motor = p.gear(motor_t, (-220, 32), layer=0, id="Motor")
    p.limit(small_t, 1)
    p.limit(motor_t, 0)
    p.limit(big_t, 1)
    p.set_rules(chain=False)    # the kit does not model chains
    p.goal_speed("Target", 45, "Faster")
    axle = p.new_axle()
    low = p.player_gear(small_t, mesh_pos(motor.pos, motor_t.pitch, small_t.pitch, 0), layer=0, axle=axle)
    p.player_gear(big_t, low.pos, layer=1, axle=axle)
    p.fit_view()
    return p
