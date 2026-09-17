# A projectile spell: flies along a line toward the target tile and hits the first
# creature in its path.

DAMAGE = 5


def on_cast(ctx, caster, target):
    origin = ctx.entity(caster).pos
    for pos in ctx.line(origin, target):
        if ctx.is_wall(pos):
            ctx.log("The firebolt splashes against the wall.")
            return
        victim = ctx.entity_at(pos)
        if victim is not None:
            ctx.damage(victim.id, DAMAGE, source=caster)
            return
    ctx.log("The firebolt hits nothing.")


define_spell(
    id="firebolt",
    name="Firebolt",
    description="Hurl a bolt of fire that deals 5 damage to the first creature in its path.",
    mana_cost=3,
    target="tile",
    range=7,
    on_cast=on_cast,
)
