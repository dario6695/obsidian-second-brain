# obsidian-second-brain

My personal configuration layer — hooks and Claude Code settings — built on top of the [obsidian-second-brain skill](https://github.com/eugeniughelbur/obsidian-second-brain) by [@eugeniughelbur](https://github.com/eugeniughelbur).

## How it works

The core skill lives at `~/.claude/skills/obsidian-second-brain/` and is installed via the upstream repo's [install instructions](https://github.com/eugeniughelbur/obsidian-second-brain#install). It provides 40+ slash commands (`/obsidian-save`, `/obsidian-daily`, `/obsidian-ingest`, etc.) that Claude Code can invoke to read and write an Obsidian vault.

This repo captures the **glue layer**: the Claude Code hooks and `settings.json` config that wire the skill into every session automatically, without needing to type a command. Here's the flow:

```
Every session start
  └── SessionStart hook → load_vault_context.py
        Reads _CLAUDE.md from the vault, injects it as context
        so Claude knows vault structure, folder map, and rules.

Every prompt
  └── UserPromptSubmit hook → obsidian-find-hook.py
        Embeds the prompt via ollama (nomic-embed-text),
        runs cosine similarity against ~/.claude/vault-index.db,
        injects the top 5 matching note snippets as context.
        Falls back to grep if the index doesn't exist.

Every vault write (Write/Edit tool)
  └── PostToolUse hook → validate-ai-first.sh
        Checks frontmatter, "For future Claude" preamble,
        required fields. Warns Claude to self-correct if missing.

After context compaction
  └── PostCompact hook → obsidian-bg-agent.sh
        Spawns a headless Claude agent that reads the compaction
        summary and propagates decisions/tasks/people to the vault.

End of session
  └── Stop hook (1) → headless claude -p "/obsidian-save"
        Auto-saves everything vault-worthy from the conversation.
  └── Stop hook (2) → update-vault-index.sh
        Incrementally re-indexes any vault notes changed this session.
```

## What's in here

### Hooks

| File | Trigger | What it does |
|---|---|---|
| `hooks/load_vault_context.py` | `SessionStart` | Reads `_CLAUDE.md` from the vault and injects it into every session as context. Requires `OBSIDIAN_VAULT_PATH` env var. |
| `hooks/obsidian-find-hook.py` | `UserPromptSubmit` | Embeds each prompt via ollama, runs cosine similarity against the vault index DB, injects top 5 matching note snippets as context. Falls back to grep if index is absent. |
| `hooks/build_vault_index.py` | (one-shot / Stop) | Builds or rebuilds `~/.claude/vault-index.db` — a SQLite DB of `nomic-embed-text` embeddings for all vault notes. Supports `--incremental` to skip unchanged files. |
| `hooks/update-vault-index.sh` | `Stop` | Thin wrapper that calls `build_vault_index.py --incremental` after each session, logging to `~/.claude/vault-index.log`. |
| `hooks/obsidian-bg-agent.sh` | `PostCompact` | After Claude compacts context, runs a headless agent that propagates the session summary to the vault. Opt-in: requires `OBSIDIAN_BG_AGENT_ENABLED=1`. |
| `hooks/validate-ai-first.sh` | `PostToolUse (Write\|Edit)` | Validates every vault write against the AI-first rule: frontmatter, `## For future Claude` preamble, no banned Unicode. Non-blocking — surfaces warnings back to Claude to self-correct. |

### Hook config

- `hooks/obsidian-bg-agent.hook.yaml` — platform-neutral spec for the PostCompact hook
- `hooks/postcompact.hook.example.json` — ready-to-paste JSON for `~/.claude/settings.json`
- `hooks/validate-ai-first.hook.yaml` — platform-neutral spec for the PostToolUse validator

## Setup

### 1. Install ollama + embedding model

Vector search requires [ollama](https://ollama.com) running locally with `nomic-embed-text`:

```bash
# install ollama (macOS)
brew install ollama
ollama serve &

# pull the embedding model (~274 MB)
ollama pull nomic-embed-text
```

### 2. Build the initial vault index

Copy `hooks/build_vault_index.py` to `~/.claude/` and run it once against your vault:

```bash
cp hooks/build_vault_index.py ~/.claude/
cp hooks/update-vault-index.sh ~/.claude/
OBSIDIAN_VAULT_PATH=/path/to/your/vault python3 ~/.claude/build_vault_index.py
```

This creates `~/.claude/vault-index.db`. The index is rebuilt incrementally after each session via the Stop hook.

### 3. Set env vars in `~/.claude/settings.json`

```json
{
  "env": {
    "OBSIDIAN_VAULT_PATH": "/path/to/your/vault",
    "OBSIDIAN_BG_AGENT_ENABLED": "1"
  }
}
```

### 4. Wire hooks in `~/.claude/settings.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/this/repo/hooks/load_vault_context.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/obsidian-find-hook.py",
            "timeout": 10
          }
        ]
      }
    ],
    "PostCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/this/repo/hooks/obsidian-bg-agent.sh",
            "timeout": 10,
            "async": true
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash /path/to/this/repo/hooks/validate-ai-first.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "OBSIDIAN_VAULT_PATH=/path/to/your/vault /opt/homebrew/bin/claude --dangerously-skip-permissions -p 'Read ~/.claude/skills/obsidian-second-brain/obsidian-second-brain.md and run /obsidian-save on this session.' 2>/dev/null || true",
            "timeout": 120,
            "async": true
          },
          {
            "type": "command",
            "command": "OBSIDIAN_VAULT_PATH=/path/to/your/vault bash ~/.claude/update-vault-index.sh",
            "timeout": 300,
            "async": true
          }
        ]
      }
    ]
  }
}
```

### 5. Make shell hooks executable

```bash
chmod +x hooks/obsidian-bg-agent.sh hooks/validate-ai-first.sh hooks/update-vault-index.sh
```

## Benchmark (2026-06-05, 155 files / 387 chunks)

### Latency

| Hook | Trigger | Avg latency |
|---|---|---|
| `SessionStart` (`load_vault_context.py`) | Once per session | ~67ms |
| `UserPromptSubmit` (`obsidian-find-hook.py`) | Every message | ~124ms |

Both well under the 10s timeout.

### Token footprint

| Hook | Output size | Approx tokens |
|---|---|---|
| SessionStart | 40,582 chars | ~10,145 tokens (once per session) |
| UserPromptSubmit (per message) | ~1,133 chars | ~283 tokens |

Estimated **5,000–15,000 tokens saved per session** vs manual `Read` calls.

### Accuracy: grep vs vector search (same 5 test prompts)

| Prompt | Grep (~60%) | Vector (~95%) |
|---|---|---|
| TLS cert webhook | ✅ hit 1 | ✅ hit 1+3+4+5 all relevant |
| migration push failure | ❌ wrong | ✅ hit 1+2+4 exact |
| slack irq DM support | ❌ wrong | ✅ hit 1+3 correct |
| copilot code review | ✅ hit 3 | ✅ hit 1+3 exact, moved to top |
| cancel queued runs | ✅ hit 1 | ✅ hit 1+3+4 all relevant |

**~60% → ~95% top-5 accuracy** after switching from keyword grep to vector search.

## Notes

- `obsidian-find-hook.py`, `build_vault_index.py`, and `update-vault-index.sh` live at `~/.claude/` locally — committed here for backup and portability.
- The vector index (`vault-index.db`) is rebuilt incrementally on every Stop event — only notes changed since the last run are re-embedded.
- If ollama is not running, `obsidian-find-hook.py` falls back to keyword grep automatically.
- The bg-agent (`obsidian-bg-agent.sh`) only activates when both `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_BG_AGENT_ENABLED=1` are set — safe to deploy without the second flag while testing.
