"""Git-isolated synthetic smoke task; production JARVIS files never enter it."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from .permissions import ROOT, STATE, TOOLS, clean_environment

NORMALIZE = '''"""Intentionally defective development-system fixture, not JARVIS code."""

def normalize_percentage(value):
    if not isinstance(value, int):
        raise ValueError("integer required")
    return max(0, min(100, value))
'''
TEST = '''"""Trusted acceptance tests for the synthetic runner fixture."""
import unittest
from normalize import normalize_percentage

class WrappedInt(int):
    pass

class NormalizeTests(unittest.TestCase):
    def test_clamps_integer_range(self):
        for value, expected in [(-500,0),(0,0),(23,23),(100,100),(205,100),(WrappedInt(42),42)]:
            with self.subTest(value=value):
                self.assertEqual(normalize_percentage(value), expected)

    def test_rejects_booleans_and_non_integers(self):
        for value in [True,False,1.0,"12",None,[],object()]:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                normalize_percentage(value)

if __name__ == "__main__":
    unittest.main()
'''


def validate_relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Invalid task path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"..", ".git", ".codex", ".agents", ".env"} for part in path.parts):
        raise ValueError("Protected or escaping task path")
    return path


def git(*arguments, cwd):
    env = clean_environment()
    empty = TOOLS / "empty.gitconfig"
    empty.touch(exist_ok=True)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(empty), GIT_TERMINAL_PROMPT="0")
    result = subprocess.run([str(TOOLS / "git/cmd/git.exe"), *map(str, arguments)], cwd=cwd, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Local Git command failed: " + result.stderr[-1000:])
    return result.stdout.strip()


def prepare_fixture(task_id):
    if task_id != "DEV-SMOKE-001":
        raise ValueError("This first approved implementation only executes DEV-SMOKE-001")
    repository = STATE / "smoke-repository"
    workspace = STATE / "worktrees" / task_id
    if workspace.exists():
        raise RuntimeError("Smoke worktree already exists; preserve it for review, do not silently overwrite or repeat the cycle")
    repository.mkdir(parents=True, exist_ok=True)
    (repository / "fixture").mkdir(exist_ok=True)
    (repository / "fixture/normalize.py").write_text(NORMALIZE, encoding="utf-8")
    (repository / "fixture/test_normalize.py").write_text(TEST, encoding="utf-8")
    (repository / "fixture/README.md").write_text(
        "# Synthetic development-system fixture\n\nNormalize integer percentages to 0..100. "
        "Accept int subclasses; reject bool and non-integers with ValueError. "
        "The intentionally seeded bug is not a JARVIS defect.\n", encoding="utf-8")
    (repository / ".gitignore").write_text("__pycache__/\n*.pyc\n.tmp/\n", encoding="utf-8")
    (repository / "AGENTS.md").write_text(
        "# Isolated synthetic smoke task\nOnly fixture/normalize.py is editable by the implementation agent.\n"
        "Do not change tests, Git metadata, permissions, environment, installed programs or other project files.\n"
        "Use the assigned task only. No installs, network, credentials, apps, subagents or Git operations.\n"
        "Tests are executed independently by the runner.\n", encoding="utf-8")
    git("init", "--initial-branch=main", cwd=repository)
    git("config", "user.name", "JARVIS Development", cwd=repository)
    git("config", "user.email", "jarvis-dev@localhost", cwd=repository)
    git("config", "commit.gpgsign", "false", cwd=repository)
    git("add", "--", "fixture", ".gitignore", "AGENTS.md", cwd=repository)
    git("commit", "-m", "Synthetic smoke fixture with intentionally failing bool case", cwd=repository)
    base = git("rev-parse", "HEAD", cwd=repository)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    branch = "development/" + task_id
    git("worktree", "add", "-b", branch, workspace, "HEAD", cwd=repository)
    return {"repository": str(repository), "workspace": str(workspace), "branch": branch,
            "base_commit": base, "editable": ["fixture/normalize.py"],
            "readonly": ["fixture/test_normalize.py", "fixture/README.md", "AGENTS.md", ".gitignore"]}


def changed_paths(workspace):
    tracked = git("diff", "--name-only", "HEAD", cwd=workspace).splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard", cwd=workspace).splitlines()
    return sorted(set(tracked + untracked))


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
