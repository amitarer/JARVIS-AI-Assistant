"""Isolated fixtures, entirely inside the project directory."""

import json
import tempfile
from pathlib import Path

from jarvis.core.controller import Controller
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.history import ClearHistoryTool, ResetPreferencesTool
from jarvis.tools.open_application import OpenApplicationTool
from jarvis.tools.registry import ToolRegistry

PROJECT = Path(__file__).resolve().parents[1]


def temporary_project():
    base = PROJECT / "data/test-runs"
    base.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=base)


def populate(root: Path) -> None:
    (root / "config").mkdir()
    (root / "config/defaults.json").write_text(json.dumps({"log_level": "INFO", "reduced_motion": False,
        "task_timeout_seconds": 5, "approval_timeout_seconds": 2}), encoding="utf-8")
    (root / "config/applications.json").write_text(json.dumps({"blocco_note": {
        "label": "Blocco note", "executable": "C:\\Windows\\System32\\notepad.exe"}}), encoding="utf-8")


def make_controller(root: Path) -> Controller:
    populate(root)
    settings = load_settings(root)
    database = Database(root / "data/test.sqlite3")
    database.initialize()
    repository = Repository(database)
    registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
    registry.register(OpenApplicationTool(settings.applications))
    registry.register(ClearHistoryTool(repository))
    registry.register(ResetPreferencesTool(repository))
    return Controller(settings, repository, registry)
