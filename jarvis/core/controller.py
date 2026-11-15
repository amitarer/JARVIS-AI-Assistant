"""Core orchestration. All calls, including demo commands, use real tools."""

import logging
import json
import threading
from collections.abc import Callable
from uuid import uuid4

from jarvis.core.commands import HELP, parse_command
from jarvis.core.models import ApprovalRequest, Cancelled, Event, TaskTimeout, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import Settings
from jarvis.memory.repository import Repository
from jarvis.tools.registry import ToolRegistry

logger = logging.getLogger("jarvis.core")


class Controller:
    def __init__(self, settings: Settings, repository: Repository, tools: ToolRegistry):
        self.settings = settings
        self.repository = repository
        self.tools = tools

    def run(self, payload: dict, cancellation: threading.Event, emit: Callable[[Event], None],
            approve: Callable[[ApprovalRequest, TaskContext], str | None], before_tool=None) -> None:
        task_id = uuid4().hex
        kind = payload.get("kind", "chat")
        timeout = self.settings.ollama.timeout_seconds if kind in {"chat", "voice", "provider_check"} and self.settings.ollama.enabled else self.settings.task_timeout_seconds
        context = TaskContext(task_id, cancellation, timeout, origin=kind)
        created = False
        effect_message: str | None = None
        try:
            context.checkpoint()
            if kind == "refresh":
                emit(Event("snapshot", self.repository.snapshot()))
                return
            if kind == "provider_check":
                from jarvis.brain.ollama import OllamaProvider
                result = OllamaProvider(self.settings.ollama).check(context)
                emit(Event("provider", {"available": True, **result}))
                return
            if kind == "voice" and not self.settings.ollama.enabled:
                raise UserError("Provider AI non configurato: nessuna risposta vocale simulata.")
            self.repository.create_task(task_id, kind, payload.get("text", ""))
            created = True
            emit(Event("snapshot", self.repository.snapshot()))
            emit(Event("state", "executing"))
            logger.info("task_started", extra={"task_id": task_id, "status": "running"})
            if kind == "preferences":
                context.checkpoint()
                self.repository.save_preferences(payload["reduced_motion"], payload["log_level"], payload.get("voice"))
                text = "Preferenze salvate."
            else:
                call: ToolCall | None = None
                if kind in {"chat", "voice"}:
                    text_in = payload["text"].strip()
                    if not text_in or len(text_in) > 8000:
                        raise UserError("Inserisci un messaggio da 1 a 8000 caratteri.")
                    self.repository.add_message("user", text_in)
                    call = parse_command(text_in)
                    if call is None:
                        if self.settings.ollama.enabled:
                            from jarvis.core.agent import run_agent
                            text = run_agent(self, context, emit, approve, before_tool)
                        else:
                            text = "Messaggio salvato localmente. Nessun modello AI è collegato. Usa /aiuto per le operazioni disponibili."
                    elif call.name == "aiuto":
                        text = HELP.replace("Modalità demo: nessun provider AI è collegato.", "Provider: Qwen 3.5 9B tramite Ollama locale.").replace(
                            "la comprensione del linguaggio naturale arriverà nella versione 0.2.",
                            "le richieste naturali vengono inviate al modello locale, con gli strumenti autorizzati.") if self.settings.ollama.enabled else HELP
                        call = None
                    elif call.name == "app":
                        if "list_applications" in self.tools:
                            call = ToolCall("list_applications", '{"query":""}')
                        else:
                            text = "Applicazioni autorizzate:\n" + "\n".join(
                                f"• {identifier}: {app.label}" for identifier, app in self.settings.applications.items()
                            )
                            call = None
                elif kind in {"clear_history", "reset_preferences"}:
                    call = ToolCall(kind, "{}")
                else:
                    raise UserError("Operazione non disponibile.")
                if call is not None:
                    result = self.execute_tool(call, context, emit, approve, before_tool)
                    text = result.message
                    effect_message = result.message
                    logger.info("tool_completed", extra={"task_id": task_id, "tool": call.name, "status": "succeeded"})
                    if cancellation.is_set():
                        text += "\nSTOP ricevuto: l'effetto già completato non è stato annullato."
                else:
                    context.checkpoint()
                self.repository.add_message("assistant", text)
            self.repository.set_task_status(task_id, "succeeded")
            self.repository.finish_task(task_id, result=text)
            emit(Event("notice", text))
            if kind in {"chat", "voice"}:
                emit(Event("response", text))
            logger.info("task_finished", extra={"task_id": task_id, "status": "succeeded"})
        except (Cancelled, TaskTimeout, UserError) as exc:
            status = "cancelled" if isinstance(exc, Cancelled) else "timed_out" if isinstance(exc, TaskTimeout) else "failed"
            if created:
                try:
                    self.repository.set_task_status(task_id, status)
                    self.repository.finish_task(task_id, result=getattr(context, "partial_result", ""), error=str(exc))
                    self.repository.add_message("system", str(exc))
                except Exception as storage_error:
                    logger.error("failure_record_write_failed", extra={"task_id": task_id,
                                 "error_type": type(storage_error).__name__})
            emit(Event("notice", str(exc)))
            if kind == "provider_check":
                emit(Event("provider", {"available": False, "message": str(exc)}))
            emit(Event("state", "error" if status != "cancelled" else "idle"))
            logger.warning("task_stopped", extra={"task_id": task_id, "status": status, "error_type": type(exc).__name__})
        except Exception as exc:
            # Never log raw exception messages, which can contain sensitive input.
            logger.error("task_failed", extra={"task_id": task_id, "error_type": type(exc).__name__})
            if created:
                try:
                    self.repository.set_task_status(task_id, "failed")
                except Exception:
                    logger.error("task_status_write_failed", extra={"task_id": task_id})
            notice = "Errore interno. Consulta data/logs/operations.jsonl per il tipo di errore."
            if effect_message is not None:
                notice = effect_message + "\nL'operazione è avvenuta, ma la registrazione locale non è riuscita."
            emit(Event("notice", notice))
            emit(Event("state", "error"))
        finally:
            self.tools.policy.approvals.revoke_all()
            if kind != "refresh":
                try:
                    emit(Event("snapshot", self.repository.snapshot()))
                except Exception:
                    emit(Event("notice", "Impossibile leggere la memoria locale. Verifica accesso e spazio su disco."))

    def execute_tool(self, call, context, emit, approve, before_tool=None):
        operation_id = self.repository.begin_operation(context.task_id, call.name, json.loads(call.arguments_json))
        emit(Event("action", {"tool": call.name, "task_id": context.task_id}))
        logger.info("tool_started", extra={"task_id": context.task_id, "tool": call.name})

        def prepare():
            emit(Event("state", "executing"))
            if before_tool:
                before_tool(call.name, context)
            self.repository.operation_status(operation_id, "executing")

        try:
            result = self.tools.execute(call, context, approve, before_execute=prepare)
        except Exception as exc:
            safe_error = str(exc) if isinstance(exc, (UserError, Cancelled, TaskTimeout)) else type(exc).__name__
            self.repository.operation_status(operation_id, "failed", error=safe_error)
            raise
        self.repository.operation_status(operation_id, "succeeded", result.message, result.evidence)
        emit(Event("tool_result", result))
        return result
