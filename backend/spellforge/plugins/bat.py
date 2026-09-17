# A fragile, erratic flyer: half the time it flutters about at random, otherwise it dives
# at the nearest hostile it can see.


def flutter(ctx, me, pos):
    options = [p for p in pos.neighbors() if ctx.is_walkable(p)]
    if options:
        ctx.move(me, ctx.choice(options))


def act(ctx, me):
    bat = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=7)
    if target is None or ctx.chance(0.5):
        flutter(ctx, me, bat.pos)
        return
    if bat.pos.distance_to(target.pos) == 1:
        ctx.attack(me, target.id)
    else:
        ctx.step_toward(me, target.pos)


define_monster(
    id="bat",
    name="bat",
    description="A cave bat. Weak, but hard to pin down.",
    glyph="b",
    max_hp=3,
    attack=1,
    act=act,
    sprite="bat",
)


# ---- art ----

define_sprite(
    id="bat",
    palette={
        "B": "#6b4f8a",
        "b": "#4a3560",
        "d": "#2e2040",
        "k": "#140d1c",
        "r": "#ff4b3e",
        "w": "#f4efe0",
    },
    rows=[
        "................",
        "................",
        "................",
        "................",
        "..kk..k..k...kk.",
        ".kBbkkbkkbk.kbBk",
        "kbbbbkbbbbkkbbbb",
        "kbbbbbbBbbkbbbbb",
        "kbbbbbbrbrkbbbbb",
        "kddbdbbbbbkbdbdd",
        ".kkkkdbwbwkdkkkk",
        "..kdkkkkkk.kkdk.",
        "...k.........k..",
        "................",
        "................",
        "................",
    ],
)
