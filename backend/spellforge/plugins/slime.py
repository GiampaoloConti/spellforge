# A slow blob that splits into two slimelings when it dies. It moves only every other
# turn. The split is a permanent status whose on_death hook spawns the slimelings.


def split(ctx, status):
    slime = ctx.entity(status.holder)
    if slime is None:
        return
    spawned = 0
    for pos in slime.pos.neighbors():
        if spawned == 2:
            break
        if ctx.is_walkable(pos) and ctx.spawn("slimeling", pos, slime.faction) is not None:
            spawned += 1
    if spawned:
        ctx.log("The slime splits in two!")


def chase(ctx, me, max_distance):
    body = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=max_distance)
    if target is None:
        return
    if body.pos.distance_to(target.pos) == 1:
        ctx.attack(me, target.id)
    else:
        ctx.step_toward(me, target.pos)


def act(ctx, me):
    if not ctx.has_status(me, "splitting"):
        ctx.apply_status(me, "splitting", None)
    if ctx.turn_number() % 2 == 0:
        chase(ctx, me, 6)


def act_small(ctx, me):
    chase(ctx, me, 6)


define_status(
    id="splitting",
    name="Splitting",
    description="Splits into two slimelings when killed.",
    on_death=split,
)

define_monster(
    id="slime",
    name="slime",
    description="Slow and tough. Splits in two when it dies.",
    glyph="S",
    max_hp=10,
    attack=2,
    act=act,
    sprite="slime",
)

define_monster(
    id="slimeling",
    name="slimeling",
    description="A small piece of a slime.",
    glyph="s",
    max_hp=3,
    attack=1,
    act=act_small,
    sprite="slimeling",
)


# ---- art ----

define_sprite(
    id="slime",
    palette={
        "G": "#2f8a4a",
        "L": "#a8f0a0",
        "e": "#10261a",
        "g": "#4cc46a",
        "k": "#10261a",
        "w": "#ffffff",
    },
    rows=[
        "................",
        "................",
        "................",
        ".....kkkkkk.....",
        "....kggggggk....",
        "...kgLLgggggk...",
        "..kgLggggggggk..",
        ".kggLgggggggGgk.",
        ".kggggggggggggk.",
        "kgggggwgggwggGgk",
        ".kggggegggegggk.",
        ".kggggggggggggk.",
        "..kggggGGGgggkk.",
        ".kGGGGGGGGGGGGGk",
        "..kGGGGGGGGGGGk.",
        "..kgkkkkkkkkkk..",
    ],
)

define_sprite(
    id="slimeling",
    palette={
        "G": "#2f8a4a",
        "L": "#a8f0a0",
        "e": "#10261a",
        "g": "#4cc46a",
        "k": "#10261a",
    },
    rows=[
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
        ".......kk.......",
        ".....kkggkk.....",
        "....kgLLgggk....",
        "...kggggggggk...",
        "...kgggeggegk...",
        "...kggggggggk...",
        "....kggggggk....",
        "....kGGGGGGGk...",
        ".....kkkkkkk....",
    ],
)
