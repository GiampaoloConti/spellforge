# Forge speed: which model and effort level? (2026-09-17)

Playtesting showed forging took too long (about 27 s with Claude Opus 5 at effort `high`).
Before swapping models, I measured. Every run is the full pipeline (writer, sandbox
verification, one retry allowed), so "success" means the spell reached the player's
spellbook.

Ideas used:

1. "turn enemies into rocks for a few turns": a status plus a sprite
2. "chain lightning that jumps between up to 3 enemies, weaker with each jump": targeting logic
3. "summon a spirit wolf that fights beside me for 5 turns": a monster with AI and a sprite

Script: `python -m spellforge.agents.bench_forge` (raw results in the JSON files next to this
note, including every generated plugin).

## Run 1: five configurations, one run per idea

| Model | Effort | Success | Avg attempts | Avg time | Avg cost | Sprite drawn when needed |
|---|---|---|---|---|---|---|
| claude-opus-5 | high | 3/3 | 1.0 | 27.0s | $0.108 | 2/2 |
| claude-opus-5 | low | 3/3 | 1.0 | 16.8s | $0.072 | 2/2 |
| claude-sonnet-5 | medium | 3/3 | 1.0 | 16.3s | $0.031 | 2/2 |
| claude-sonnet-5 | low | 3/3 | 1.3 | 15.8s | $0.040 | 2/2 |
| claude-haiku-4-5 | n/a | 2/3 | 1.7 | 21.5s | $0.013 | 1/1 |

Findings:

- **Time is almost all generation.** Sandbox verification took under 1 s per attempt.
- **Every failure or retry was a sprite formatting slip.** Rows were 15 or 17 characters
  wide, or `"."` was listed in the palette. LLMs are bad at counting characters, and each
  slip cost a full extra attempt (10-25 s). Haiku 4.5 is the fastest per call (7 s) but
  retried the most and failed the summon, so it was *slower* on average.

**Fix:** `define_sprite` now forgives small slips. It pads short rows, trims transparent
overflow, adds missing rows at the top and ignores a `"."` palette entry. It still rejects
art that would lose visible pixels.

![Sprites from run 1](forge-models-sprites-run1.png)

*Left to right: rock and wolf from Opus high, Opus low, Sonnet medium, Sonnet low, Haiku.*

## Run 2: the two fastest candidates, with lenient sprites, two runs per idea

| Model | Effort | Success | Avg attempts | Avg time | Avg cost | Sprite drawn when needed |
|---|---|---|---|---|---|---|
| claude-opus-5 | low | 6/6 | 1.0 | 16.8s | $0.038 | 4/4 |
| claude-sonnet-5 | low | 6/6 | 1.0 | 12.0s | $0.013 | 4/4 |

![Sprites from run 2](forge-models-sprites-run2.png)

*Left: 2 rocks and 2 wolves from Opus low. Right: the same from Sonnet low.*

## Decision

**Default: Claude Opus 5 at effort `low`** (`SPELLFORGE_MODEL`, `SPELLFORGE_EFFORT` override it).

- It is about 40% faster than the old default, with the same success rate and a third of the cost.
- Sonnet 5 at `low` is another ~5 s faster and 3x cheaper, and its code was just as
  reliable here. Its sprites are clearly weaker, though: the rocks look like grey robots and
  the wolves like blobs. In a game where the art shows every time you cast the spell, that
  is worth 5 s. Set `SPELLFORGE_MODEL=claude-sonnet-5` if you prefer speed.

Caveat: small sample (3 ideas, up to 2 runs each). The M5 eval suite will repeat this with
more ideas and an automatic judge for balance and faithfulness to the idea.
