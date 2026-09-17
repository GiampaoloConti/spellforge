# A support caster: heals wounded allies nearby and keeps away from the fight.

HEAL = 3
HEAL_RANGE = 5


def act(ctx, me):
    shaman = ctx.entity(me)
    target = ctx.nearest_hostile(me, max_distance=8)
    if target is not None and shaman.pos.distance_to(target.pos) <= 2:
        options = [p for p in shaman.pos.neighbors() if ctx.is_walkable(p)]
        farther = [
            p for p in options if p.distance_to(target.pos) > shaman.pos.distance_to(target.pos)
        ]
        if farther:
            ctx.move(me, ctx.choice(farther))
            return
    wounded = [
        e
        for e in ctx.entities_in_radius(shaman.pos, HEAL_RANGE, faction=shaman.faction)
        if e.hp < e.max_hp
    ]
    if wounded:
        patient = min(wounded, key=lambda e: (e.hp / e.max_hp, e.id))
        if ctx.heal(patient.id, HEAL) > 0:
            who = "itself" if patient.id == me else f"the {patient.name}"
            ctx.log(f"The goblin shaman chants and heals {who}.")
            return
    if target is not None and shaman.pos.distance_to(target.pos) > 4:
        ctx.step_toward(me, target.pos)


define_monster(
    id="goblin_shaman",
    name="goblin shaman",
    description="Heals nearby monsters. Kill it first.",
    glyph="G",
    max_hp=6,
    attack=1,
    act=act,
    sprite="goblin_shaman",
)


# ---- art ----

define_sprite(
    id="goblin_shaman",
    palette={
        "G": "#3c7a2a",
        "P": "#8d56b3",
        "c": "#6fe8ff",
        "e": "#1c1426",
        "f": "#e04a4a",
        "g": "#5caa3c",
        "k": "#140d1c",
        "n": "#8b5a2b",
        "p": "#6b3a8a",
        "q": "#4a2663",
        "r": "#ffd43b",
        "w": "#e9e4d4",
    },
    rows=[
        ".....kkkkffcwwwk",
        "....kPppppfkewek",
        "...kPppppppkwwwc",
        "...kppppppqkknkk",
        "..kkpGGGGGqkknk.",
        ".kggkgrgrgkgGnk.",
        "..kkkgggggkkknk.",
        "....kgGGGgk.knk.",
        "...kPwwwwwqkknk.",
        "...kPpppppqkgnk.",
        "...kPpppppqkknk.",
        "..kPpppppppqknk.",
        "..kPpppppppqknk.",
        "..kPpppppppqknk.",
        "..kPpppppppqknk.",
        "...kqqqkqqqkknk.",
    ],
)
