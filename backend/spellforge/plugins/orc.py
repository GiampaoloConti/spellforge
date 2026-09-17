# A slow-witted brute with a big axe: lots of health, heavy hits.


def act(ctx, me):
    orc = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=6)
    if target is None:
        return
    if orc.pos.distance_to(target.pos) == 1:
        ctx.attack(me, target.id)
    else:
        ctx.step_toward(me, target.pos)


define_monster(
    id="orc",
    name="orc brute",
    description="Tough and hits hard. Don't let it corner you.",
    glyph="O",
    max_hp=16,
    attack=4,
    act=act,
    sprite="orc",
)


# ---- art ----

define_sprite(
    id="orc",
    palette={
        "H": "#7a5234",
        "M": "#5f6470",
        "O": "#4d6326",
        "h": "#5a3a24",
        "i": "#d6dde4",
        "k": "#140d1c",
        "m": "#8a8f99",
        "n": "#8b5a2b",
        "o": "#6f8a3a",
        "r": "#ffb13e",
        "t": "#f4efe0",
    },
    rows=[
        "...kmmmimmmk....",
        "..kmmmmmmmmmk...",
        "...kMMMMMMMk.kkk",
        "...kOOOOOOOkkiim",
        "...korooorOkkiii",
        "...kotoootOkkiii",
        "...kotOOOtokkmii",
        "..kkoooooookkknk",
        ".kmmHHHHHHHmmknk",
        ".kmmhhhhhhhmmknk",
        "kohhhhhhhhhhhonk",
        "kohhkkkrkkkhhOnk",
        ".khhhhhhhhhhhknk",
        "..kkOOOkOOOkk.k.",
        "...kOOOkOOOk....",
        "..khhhhkhhhhk...",
    ],
)
