# An area spell that uses a status effect: damages and freezes every nearby enemy of
# the caster. Frozen creatures skip their turns until the status expires.

RADIUS = 2
DAMAGE = 2
FREEZE_TURNS = 2


def on_cast(ctx, caster, target):
    me = ctx.entity(caster)
    hit = 0
    for other in ctx.entities_in_radius(me.pos, RADIUS):
        if other.faction == me.faction:
            continue
        ctx.damage(other.id, DAMAGE, source=caster)
        if ctx.apply_status(other.id, "frozen", FREEZE_TURNS, source=caster):
            hit += 1
    if hit == 0:
        ctx.log("Frost spreads across the floor, but nothing is caught in it.")


def on_frozen_apply(ctx, status):
    victim = ctx.entity(status.holder)
    ctx.log(f"The {victim.name} is frozen solid.")


define_status(
    id="frozen",
    name="Frozen",
    description="Encased in ice: cannot act.",
    prevents_action=True,
    on_apply=on_frozen_apply,
)

define_spell(
    id="frost_nova",
    name="Frost Nova",
    description="A blast of cold: 2 damage to nearby enemies, freezing them for 2 turns.",
    mana_cost=5,
    cooldown=4,
    target="self",
    on_cast=on_cast,
)
