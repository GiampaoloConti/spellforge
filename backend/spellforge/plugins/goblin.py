# A basic melee monster. Chases the nearest visible hostile and attacks when adjacent;
# otherwise it wanders.


def act(ctx, me):
    goblin = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=8)
    if target is None:
        if ctx.chance(0.5):
            options = [pos for pos in goblin.pos.neighbors() if ctx.is_walkable(pos)]
            if options:
                ctx.move(me, ctx.choice(options))
        return
    if goblin.pos.distance_to(target.pos) == 1:
        ctx.attack(me, target.id)
    else:
        ctx.step_toward(me, target.pos)


define_monster(
    id="goblin",
    name="goblin",
    description="A small, vicious creature that rushes anything it sees.",
    glyph="g",
    max_hp=6,
    attack=2,
    act=act,
    sprite="goblin",
)


# ---- art ----

define_sprite(
    id="goblin",
    palette={
        "G": "#3c7a2a",
        "H": "#a06638",
        "I": "#ffffff",
        "L": "#94d65c",
        "g": "#5caa3c",
        "h": "#7a4a2a",
        "i": "#c9d4de",
        "k": "#140d1c",
        "n": "#8b5a2b",
        "r": "#ff4b3e",
        "t": "#f4efe0",
    },
    rows=[
        "................",
        "................",
        ".k...kkkkkk...k.",
        "kLk.kLLLLLGk.kgk",
        "kgkkLggggggGkkgk",
        ".kggLGGGGGGGGGk.",
        "..kkgkrggrkGkkIk",
        "...kgggggggGkkik",
        "...kggtkktgGkkik",
        "...kkgggggGkkkik",
        "..kgHhhhhhhhgkik",
        "..kgHhhhhhhhGnnk",
        "...kkkkkkkkkkkk.",
        "...kHhhhhhhhk...",
        "....kGGkkGGk....",
        "....kkk..kkk....",
    ],
)
