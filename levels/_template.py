"""LEVEL NN - Title  (archetype: ...)

Design card (fill in BEFORE writing code):
  Teaches:            the one new idea
  Numbers:            motor speed, target speed and why they are what they are
  Intended solution:  which gears go where
  Why the stock is tight: why fewer or other gears cannot win
  Decoy:              a wrong but plausible arrangement and the speed it gives
"""
try:
    from gear_kit import *      # when tools/build.py runs this file
except ImportError:
    pass                        # in a pasted code cell the kit is already defined above


def build():
    p = Puzzle("Title (max 80 characters)", "What the player must achieve, without giving the solution away.")

    # 1) Templates: teeth, and motor_speed for the motor. All gears that must mesh share the same size (10).
    motor_t = p.template(16, motor_speed=30, color="blue")
    gear_t = p.template(16)

    # 2) What the player finds on the board: fixed gears, with names for every gear an objective mentions.
    motor = p.gear(motor_t, (0, 0), id="Motor")
    target = p.gear(gear_t, (480, 0), id="Target")

    # 3) What the player may place. Every template needs a limit; 0 hides it (motors are always 0).
    p.limit(motor_t, 0)
    p.limit(gear_t, 2)
    p.set_rules(chain=False)    # the kit does not model chains

    # 4) What the player has to achieve (deg/s, positive = clockwise).
    p.goal_speed("Target", -30, "Turn against the motor")

    # 5) The intended solution. Compute positions with mesh_pos(), never by hand.
    first = mesh_pos(motor.pos, motor_t.pitch, gear_t.pitch, 0)
    second = mesh_pos(first, gear_t.pitch, gear_t.pitch, 0)
    p.player_gear(gear_t, first)
    p.player_gear(gear_t, second)

    # 6) Frame the level so everything is visible.
    p.fit_view()
    return p
