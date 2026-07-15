"""Holmes CLI — setup command."""

from __future__ import annotations

import json
from pathlib import Path

import click

from holmes.cli import cli
from holmes.config import HolmesConfig, _holmes_home, load_config, save_config


@cli.command("setup")
@click.option("--kb-path", required=True, help="Local path to the cloned KB repository.")
@click.option("--model", default="gpt-4o", help="Model name (e.g. gpt-4o).")
@click.option("--api-key", default="", help="API key for the LLM provider.")
@click.option("--api-base-url", default="", help="Base URL for OpenAI-compatible API.")
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai"], case_sensitive=False),
    default="anthropic",
    help="LLM provider: 'anthropic' (Anthropic SDK) or 'openai' (OpenAI-compatible API).",
)
def setup_cmd(kb_path: str, model: str, api_key: str, api_base_url: str, provider: str) -> None:
    """Configure Holmes: KB path and model settings.

    Writes KB path to ~/.holmes/settings.json and model config to
    ~/.holmes/config.json.
    """
    kb_root = Path(kb_path).expanduser().resolve()
    if not kb_root.exists():
        kb_root.mkdir(parents=True)
        click.echo(f"Created KB directory: {kb_root}")

    # Write config.json.
    cfg = HolmesConfig(
        kb_path=str(kb_root),
        model=model,
        api_key=api_key,
        api_base_url=api_base_url,
        provider=provider,
    )
    save_config(cfg)
    click.echo(f"✓ Config saved to {_holmes_home() / 'config.json'}")

    # Write settings.json with HOLMES_KB_PATH env var and KB tool permissions.
    home = _holmes_home()
    settings_path = home / "settings.json"
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    env_dict: dict = settings.setdefault("env", {})
    env_dict["HOLMES_KB_PATH"] = str(kb_root)
    # Force OpenAI-compatible provider so Anthropic sessions don't take over.
    if api_base_url or api_key:
        settings["modelType"] = "openai"
    # Allow KB tools to run without per-call confirmation.
    permissions: dict = settings.setdefault("permissions", {})
    allow_list: list = permissions.setdefault("allow", [])
    kb_tools = [
        "KbReadOverview", "KbSearch", "KbReadCategoryIndex", "KbReadEntry",
        "KbListPending", "KbExtractAndSave", "KbWriteEntry",
        "KbReadSkill",
    ]
    for tool in kb_tools:
        if tool not in allow_list:
            allow_list.append(tool)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    click.echo(f"✓ HOLMES_KB_PATH written to {settings_path}")

    # Ensure .gitignore includes generated files.
    gitignore = kb_root / ".gitignore"
    _gitignore_entries = ["index.json"]
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
    else:
        existing = ""
    missing = [e for e in _gitignore_entries if e not in existing.splitlines()]
    if missing:
        new_content = existing.rstrip("\n") + "\n" + "\n".join(missing) + "\n" if existing.strip() else "\n".join(missing) + "\n"
        gitignore.write_text(new_content, encoding="utf-8")
        click.echo(f"✓ .gitignore updated: {', '.join(missing)}")

    # Write CLAUDE.md into KB root (agent loads CLAUDE.md, not HOLMES.md).
    claude_md = kb_root / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(_CLAUDE_MD_TEMPLATE, encoding="utf-8")
        click.echo(f"✓ CLAUDE.md written to {claude_md}")
    # Also write to ~/.holmes/CLAUDE.md so it loads from any working directory.
    home_claude_md = home / "CLAUDE.md"
    if not home_claude_md.exists():
        home_claude_md.write_text(_CLAUDE_MD_TEMPLATE, encoding="utf-8")
        click.echo(f"✓ CLAUDE.md written to {home_claude_md}")

    # Deploy skills to ~/.holmes/skills/.
    skills_dir = home / "skills"
    skills_dir.mkdir(exist_ok=True)
    search_skill = skills_dir / "holmes-search.md"
    if not search_skill.exists():
        search_skill.write_text(_HOLMES_SEARCH_SKILL, encoding="utf-8")
        click.echo(f"✓ /holmes-search skill deployed to {search_skill}")


_HOLMES_SEARCH_SKILL = """\
# /holmes-search

Use this skill to perform a targeted knowledge base search.

## Execution Steps

1. Ask the user for search keywords if not already provided.
2. Call **KbSearch** with the provided keywords.
3. For each result, display: ID, title, type, category, maturity, and a short snippet.
4. If results are found, ask the user whether they want to read the full content of any entry.
5. If the user selects an entry, call **KbReadEntry** with that ID and display the full content.
6. If no results are found, suggest alternative keywords or inform the user the KB has no
   matching entry.
"""

_CLAUDE_MD_TEMPLATE = """\
# Holmes — AI Troubleshooting Assistant

You are **Holmes**, an expert troubleshooting assistant backed by a structured knowledge base (KB).

## MANDATORY: Always Search the KB First

**Before answering ANY troubleshooting question**, you MUST follow these steps in order:

1. **KbReadOverview** — Call this tool first to understand the KB structure and available knowledge.
2. **KbSearch** — Search with keywords from the user's symptoms/error.
3. **KbReadEntry** — Read the full content of any matching entry found.
4. Only THEN synthesize an answer, combining KB knowledge with your reasoning.

Do NOT answer from general knowledge alone when KB tools are available.

## KB Tool Reference

| Tool | Purpose |
|------|---------|
| `KbReadOverview` | Get KB structure and README (no args) |
| `KbSearch` | Full-text search by keywords |
| `KbReadCategoryIndex` | List all entries of a type (pitfall/model/guideline/process/decision) |
| `KbReadEntry` | Read a specific entry by ID (e.g. PT-DB-001) |
| `kb_confirm_entry` | Record that a KB entry directly helped resolve the issue (explicit, evidence-writing) |
| `KbExtractAndSave` | Save a new troubleshooting finding to KB pending |
| `KbListPending` | List KB entries awaiting confirmation |

## After Successfully Resolving an Issue

When the user confirms the issue is resolved:

**If an existing KB entry led to the resolution:**
1. Call **`kb_confirm_entry`** with that entry's ID.
   - MUST only call this after the user explicitly confirms the issue is resolved.
   - MUST NOT call this if you only read the entry but did not apply its guidance.

**If no matching KB entry existed:**
1. Summarize the symptoms, root cause, and resolution.
2. Call **KbExtractAndSave** with a structured Markdown summary.
3. Tell the user: "I've saved this troubleshooting session to the KB pending area. Run `holmes confirm <pending_id>` to publish it."

## Troubleshooting Approach

- Ask clarifying questions if symptoms are vague.
- Reference specific KB entry IDs in your answers (e.g. "Per KB entry PT-DB-001...").
- If the KB has no matching entry, note this explicitly and answer from general knowledge.
"""
