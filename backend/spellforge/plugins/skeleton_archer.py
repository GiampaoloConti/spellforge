# A ranged attacker: shoots arrows from a distance and backs away from anyone who gets
# close.

ARROW_DAMAGE = 2
SHOOT_RANGE = 6


def back_away(ctx, me, pos, threat):
    options = [p for p in pos.neighbors() if ctx.is_walkable(p)]
    farther = [p for p in options if p.distance_to(threat) > pos.distance_to(threat)]
    if farther:
        ctx.move(me, ctx.choice(farther))
        return True
    return False


def act(ctx, me):
    archer = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=9)
    if target is None:
        return
    distance = archer.pos.distance_to(target.pos)
    if distance == 1:
        if not back_away(ctx, me, archer.pos, target.pos):
            ctx.attack(me, target.id)
    elif distance <= SHOOT_RANGE:
        victim = "you" if target.is_player else f"the {target.name}"
        ctx.log(f"The skeleton archer looses an arrow at {victim}.")
        ctx.damage(target.id, ARROW_DAMAGE, source=me)
    else:
        ctx.step_toward(me, target.pos)


define_monster(
    id="skeleton_archer",
    name="skeleton archer",
    description="Keeps its distance and peppers you with arrows.",
    glyph="s",
    max_hp=5,
    attack=1,
    act=act,
    sprite="skeleton_archer",
)


# ---- art ----

define_sprite(
    id="skeleton_archer",
    palette={
        "W": "#b3ab96",
        "e": "#1c1426",
        "i": "#c9d4de",
        "k": "#140d1c",
        "n": "#8b5a2b",
        "r": "#7a2a2a",
        "s": "#d8d0bb",
        "w": "#e9e4d4",
    },
    rows=[
        ".....kkkkkk.....",
        "....kwwwwwrk....",
        "...krwwwwWkk....",
        "...krweweWknk...",
        "....kwwewwksnk..",
        "....kWWWWWksnk..",
        ".....kwewkksknk.",
        ".....kkwkkksknkk",
        "....kWwWwnnnnnni",
        "....kwkwkkksknkk",
        "....kWWWWWksnk..",
        ".....kkwkkksnk..",
        ".....kWWWkknk...",
        ".....kwkwk.k....",
        ".....kwkwk......",
        "....kWWkWWk.....",
    ],
)
