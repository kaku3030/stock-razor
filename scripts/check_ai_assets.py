#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
COPILOT = ROOT / ".github" / "copilot-instructions.md"
INSTRUCTIONS_DIR = ROOT / ".github" / "instructions"
CLAUDE_SKILLS_DIR = ROOT / ".claude" / "skills"
CANONICAL_REPOSITORY = "kaku3030/stock-razor"
FORBIDDEN_REPOSITORY_REFERENCES = (
    "ZhuLinsen/daily_stock_analysis",
)

REQUIRED_INSTRUCTION_FILES = {
    "backend.instructions.md",
    "client.instructions.md",
    "governance.instructions.md",
}

REQUIRED_SKILL_FILES = {
    "README.md",
    "analyze-issue/SKILL.md",
    "analyze-pr/SKILL.md",
    "fix-issue/SKILL.md",
    "stock-razor-self-improvement/SKILL.md",
}

REQUIRED_GITIGNORE_SNIPPETS = (
    ".claude/*",
    "!.claude/skills/",
    "!.claude/skills/**",
)


def fail(message: str) -> None:
    print(f"[ai-assets] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def ensure_file_exists(path: Path, description: str) -> None:
    if not path.exists():
        fail(f"{description} is missing: {path.relative_to(ROOT)}")


def ensure_symlink() -> None:
    ensure_file_exists(AGENTS, "canonical AGENTS.md")
    if not CLAUDE.exists():
        fail("CLAUDE.md is missing")
    if not CLAUDE.is_symlink():
        fail("CLAUDE.md must be a symlink to AGENTS.md")

    target = Path(CLAUDE.readlink())
    if target != Path("AGENTS.md"):
        fail(f"CLAUDE.md must point to AGENTS.md, found: {target}")


def ensure_copilot_entry() -> None:
    ensure_file_exists(COPILOT, "repository Copilot instructions")
    content = COPILOT.read_text(encoding="utf-8")
    required_fragments = (
        "Canonical source:",
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/skills/",
    )
    for fragment in required_fragments:
        if fragment not in content:
            fail(f".github/copilot-instructions.md is missing required text: {fragment!r}")


def ensure_instruction_files() -> None:
    ensure_file_exists(INSTRUCTIONS_DIR, "instructions directory")
    actual = {path.name for path in INSTRUCTIONS_DIR.glob("*.instructions.md")}
    missing = REQUIRED_INSTRUCTION_FILES - actual
    if missing:
        fail(f"missing instruction files: {', '.join(sorted(missing))}")


def ensure_skill_files() -> None:
    ensure_file_exists(CLAUDE_SKILLS_DIR, "Claude skills directory")
    for relative_path in REQUIRED_SKILL_FILES:
        path = CLAUDE_SKILLS_DIR / relative_path
        if not path.exists():
            fail(f"missing repository skill asset: {path.relative_to(ROOT)}")
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if relative_path != "README.md" and "AGENTS.md" not in content:
                fail(f"{path.relative_to(ROOT)} must reference AGENTS.md as the rule source")


def ensure_shared_failure_registry() -> None:
    """Every PR must pass the same cross-window anti-repeat registry contract."""
    registry = CLAUDE_SKILLS_DIR / "stock-razor-self-improvement" / "failure-registry.json"
    ensure_file_exists(registry, "canonical cross-window failure registry")
    agents = AGENTS.read_text(encoding="utf-8")
    if "stock-razor-self-improvement/SKILL.md" not in agents:
        fail("AGENTS.md missing mandatory shared self-improvement bootstrap")
    script = ROOT / "scripts" / "self_improvement_gate.py"
    ensure_file_exists(script, "self-improvement fail-closed gate")
    proc = subprocess.run(
        [sys.executable, str(script), "--check-registry"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if proc.returncode != 0:
        fail("shared self-improvement registry validation failed: " + proc.stderr[:250])


def ensure_gitignore_rules() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for snippet in REQUIRED_GITIGNORE_SNIPPETS:
        if snippet not in gitignore:
            fail(f".gitignore is missing required AI asset rule: {snippet}")


def ensure_no_tracked_claude_artifacts() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", ".claude"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    allowed_prefixes = (".claude/skills/",)
    for path in tracked:
        if path.startswith(allowed_prefixes):
            continue
        fail(f"tracked .claude artifact outside skills/: {path}")


def ensure_skill_repository_references() -> None:
    for path in CLAUDE_SKILLS_DIR.rglob("*.md"):
        content = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_REPOSITORY_REFERENCES:
            if forbidden in content:
                fail(
                    f"{path.relative_to(ROOT)} contains stale repository reference: "
                    f"{forbidden}; use {CANONICAL_REPOSITORY}"
                )


def main() -> None:
    ensure_symlink()
    ensure_copilot_entry()
    ensure_instruction_files()
    ensure_skill_files()
    ensure_shared_failure_registry()
    ensure_gitignore_rules()
    ensure_no_tracked_claude_artifacts()
    ensure_skill_repository_references()
    print("[ai-assets] OK")


if __name__ == "__main__":
    main()
