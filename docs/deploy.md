# Deploying Spellforge for friends (Hugging Face Spaces)

The game runs as one Docker container: the Python server plus the built frontend. GitHub
Actions tests every push to `main` and, when tests pass, pushes the code to a Hugging Face
Space, which builds the container and serves it at a public URL.

Your Anthropic key never enters the repository: it is a **secret on the Space**, visible only
to the running container.

## What protects your credit

| Guard | Setting | Default in the image |
|---|---|---|
| Invite code: nobody can play (or spend) without it | `SPELLFORGE_ACCESS_CODE` | none: **set it** |
| Daily budget across all players, in USD (UTC days) | `SPELLFORGE_DAILY_BUDGET_USD` | 5 |
| Concurrent players | `SPELLFORGE_MAX_SESSIONS` | 20 |
| One shard per spell; at most 6 forged spells and 3 Dungeon Master monsters per run | in code | |

The daily budget is kept in memory, so a restarted Space starts the day at zero. Set a
**spend limit in the Anthropic console** as the hard backstop (step 1).

Generated plugins run in separate worker processes. Besides the AST validator and the
restricted namespace, on Linux the workers cannot create processes, write files, or grow past
512 MB, and the server process is non-dumpable, so a worker cannot read the API key from
`/proc`. (Docker's default seccomp profile blocks the extra network namespace, so on
Hugging Face the network restriction is the validator's: plugin code cannot import anything.)

## One-time setup

### 1. Anthropic: a dedicated key with a limit

1. In the [Anthropic console](https://console.anthropic.com/), create a new API key just for
   this deployment (named e.g. `spellforge-space`), so you can revoke it on its own.
2. Under *Limits*, set a monthly spend limit you are comfortable with.

### 2. Hugging Face: the Space

1. Create an account at [huggingface.co](https://huggingface.co/join).
2. Create a Space: **New → Space**. Name it (e.g. `spellforge`), choose **Docker** as the SDK
   and the **Blank** template, the free *CPU basic* hardware, and **Public** visibility. The
   invite code protects the game; a public Space just means the page loads.
3. In the Space's **Settings → Variables and secrets**, add:
   - secret `ANTHROPIC_API_KEY`: the key from step 1;
   - secret `SPELLFORGE_ACCESS_CODE`: a long random code, for example the output of
     `python -c "import secrets; print(secrets.token_urlsafe(12))"`;
   - optionally, variable `SPELLFORGE_DAILY_BUDGET_USD` (default 5).
4. Create a token for GitHub to push with: **Settings → Access Tokens → Create new token**,
   type **Write** (or fine-grained with write access to this Space only). Copy it.

### 3. GitHub: connect the repository

In the GitHub repository, **Settings → Secrets and variables → Actions**:

- **Secrets** tab: add `HF_TOKEN` with the token from step 2.4.
- **Variables** tab: add `HF_SPACE` with `your-hf-username/spellforge`.

### 4. Deploy

Push to `main` (or run the *CI* workflow by hand from the **Actions** tab). When the `deploy`
job is green, the Space starts building; the first build takes a few minutes. The game is then
at `https://your-hf-username-spellforge.hf.space` (also linked from the Space page).

Send friends that URL and the invite code. The browser remembers a working code.

### 5. Keep the leaderboard across restarts

A Space's disk is wiped whenever it restarts or redeploys, so the leaderboard needs
somewhere lasting to live: a Hugging Face Storage Bucket mounted into the Space. The file is a
few kilobytes, well within the free storage allowance.

1. Create a bucket at [huggingface.co/new-bucket](https://huggingface.co/new-bucket): name
   it e.g. `spellforge-data`, **private**.
2. In the Space's **Settings**, attach the bucket as a volume mounted at `/data`,
   **read-write**.
3. In **Settings → Variables and secrets**, add the variable `SPELLFORGE_DATA_DIR` = `/data`.

The Space restarts. After the first death, `leaderboard.json` appears in the bucket. Without
these steps the leaderboard still works but starts empty after each restart; if the folder
cannot be written, the Space's *Logs* say so.

Players are recognised by a random id their browser keeps, not by IP address (housemates share
an IP, phones change theirs). Playing in another browser or a private window counts as a new
player. Runs are recorded by the server when the player dies, so scores can't be faked from the
browser.

## Day to day

- **Change the invite code**: edit the secret on the Space; it restarts with the new code and
  everyone is asked again.
- **Stop everything now**: pause the Space (*Settings → Pause*), or revoke the Anthropic key.
- **Logs**: the Space's *Logs* tab shows the server output, including each agent call.
- Free Spaces sleep after about 48 hours without visitors and wake on the next visit.

## Run the same container locally

```bash
docker build -t spellforge .
docker run -p 7860:7860 -e ANTHROPIC_API_KEY=sk-ant-... -e SPELLFORGE_ACCESS_CODE=test spellforge
# http://localhost:7860
```
