"""Construct local services. Importing this module performs no IO."""

from pathlib import Path

from jarvis.core.controller import Controller
from jarvis.infrastructure.logging_setup import configure_logging
from jarvis.infrastructure.settings import Settings, load_settings
from jarvis.infrastructure.system_information import SystemInformation
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.history import ClearHistoryTool, ResetPreferencesTool
from jarvis.tools.open_application import OpenApplicationTool
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.read_operations import ReadOperationsTool
from jarvis.tools.applications import ApplicationCatalog, ListApplicationsTool
from jarvis.tools.pc import InspectFilesTool, OpenResourceTool
from jarvis.tools.desktop import DesktopSession, InspectDesktopTool, DesktopActionTool
from jarvis.tools.system_information import OPERATIONS, SystemInformationTool
from jarvis.tools.websites import WebsiteCatalog
from jarvis.browser.controller import BrowserController
from jarvis.tools.autonomy import StartAutonomousChatTool, BrowserChatTool
from jarvis.research.service import ResearchServices
from jarvis.tools.research import RunResearchTool, ResearchOperationTool
from jarvis.tools.web_reading import WebReadingTool
from jarvis.tools.whatsapp import WhatsAppMessageTool, WhatsAppContactTool, ConnectWhatsAppTool
from jarvis.browser.whatsapp import WhatsAppBrowser


def build_controller(root: Path) -> Controller:
    settings = load_settings(root)
    ensure_local_data(settings)
    configure_logging(settings.data_dir / "logs", settings.log_level)
    database = Database(settings.data_dir / "jarvis.sqlite3")
    database.initialize()
    repository = Repository(database)
    return Controller(settings, repository, build_tool_registry(settings, repository))


def build_tool_registry(settings: Settings, repository: Repository) -> ToolRegistry:
    registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
    system_information = SystemInformation()
    for operation in OPERATIONS:
        registry.register(SystemInformationTool(system_information, operation))
    catalog = ApplicationCatalog(settings.root)
    registry.register(OpenApplicationTool(settings.applications, catalog))
    whatsapp = WhatsAppBrowser(settings.root)
    registry.register(WhatsAppMessageTool(whatsapp))
    registry.register(WhatsAppMessageTool(whatsapp, send=True))
    registry.register(WhatsAppContactTool(repository))
    registry.register(ConnectWhatsAppTool(whatsapp))
    registry.register(ListApplicationsTool(catalog))
    registry.register(OpenResourceTool(WebsiteCatalog(settings.root)))
    registry.register(StartAutonomousChatTool())
    registry.register(RunResearchTool())
    research = ResearchServices(settings.root)
    for operation in ("search", "fetch"):
        registry.register(WebReadingTool(research, operation))
    for operation in ("search","fetch","pdf","chatgpt","google_docs"):
        registry.register(ResearchOperationTool(research,operation))
    browser = BrowserController(settings.root)
    for operation in ("open", "observe", "send", "reply"):
        registry.register(BrowserChatTool(browser, operation))
    registry.register(InspectFilesTool())
    desktop_session = DesktopSession()
    registry.register(InspectDesktopTool(desktop_session))
    registry.register(DesktopActionTool(desktop_session))
    registry.register(ClearHistoryTool(repository))
    registry.register(ResetPreferencesTool(repository))
    registry.register(ReadOperationsTool(repository))
    return registry


def ensure_local_data(settings: Settings) -> None:
    """Prevent an existing redirected data directory from escaping the project."""
    root = settings.root.resolve()
    for relative in ("data", "data/logs", "data/jarvis.lock", "data/jarvis.sqlite3", "data/jarvis.sqlite3-wal",
                     "data/jarvis.sqlite3-shm", "data/logs/operations.jsonl",
                     "data/logs/operations.jsonl.1", "data/logs/operations.jsonl.2", "data/logs/operations.jsonl.3"):
        target = root / relative
        if target.is_symlink() or target.is_junction() or not target.resolve().is_relative_to(root):
            raise ValueError("Il percorso dati deve rimanere nella cartella JARVIS, senza collegamenti.")
    settings.data_dir.mkdir(exist_ok=True)
