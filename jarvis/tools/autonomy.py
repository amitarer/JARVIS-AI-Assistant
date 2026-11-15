"""One concrete session approval, followed by narrowly scoped browser operations."""

import json

from jarvis.core.models import Risk, ToolCall, ToolResult, UserError
from jarvis.security.sessions import SessionPermission


class StartAutonomousChatTool:
    name = "start_autonomous_chat"
    risk = Risk.MEDIUM
    description = ("Avvia una conversazione autonoma con ChatGPT nel browser dedicato, fino a STOP. "
                   "Per richieste come 'inizia a chattare con ChatGPT'. objective definisce l'argomento; "
                   "se non specificato usa conversazione generale in italiano. Una conferma iniziale autorizza gli invii della sessione.")
    parameters = {"type": "object", "properties": {"objective": {"type": "string", "minLength": 1, "maxLength": 1000}},
                  "required": ["objective"], "additionalProperties": False}

    def validate(self, arguments):
        if (set(arguments) != {"objective"} or not isinstance(arguments["objective"], str)
                or not 1 <= len(arguments["objective"].strip()) <= 1000 or "\x00" in arguments["objective"]):
            raise UserError("Specifica un obiettivo di conversazione, massimo 1000 caratteri.")
        return {"objective": arguments["objective"].strip()}

    def describe(self, arguments):
        return ("Autorizza JARVIS a scrivere, inviare e leggere messaggi SOLO nella conversazione ChatGPT del profilo dedicato, "
                "continuando fino a STOP. Obiettivo: " + arguments["objective"] +
                ". Nessun accesso a file personali, credenziali, altre chat o altri siti. Login e CAPTCHA restano manuali.")

    def execute(self, arguments, context):
        context.checkpoint()
        context.session_permission = SessionPermission(context.task_id, context.cancellation)
        context.autonomy_objective = arguments["objective"]
        return ToolResult("Sessione autonoma ChatGPT autorizzata fino a STOP.",
                          {"session_granted": True, "objective": arguments["objective"], "scope": "chatgpt_conversation"})


class BrowserChatTool:
    def __init__(self, browser, operation):
        allowed = {"open", "observe", "send", "reply"}
        if operation not in allowed:
            raise ValueError("Operazione browser non registrata.")
        self.browser, self.operation = browser, operation
        self.name = "browser_chat_" + operation
        self.risk = Risk.MEDIUM if operation == "send" else Risk.LOW
        self.description = "Operazione strutturata della conversazione ChatGPT autorizzata: " + operation
        properties = {"text": {"type": "string", "maxLength": 1800}} if operation == "send" else (
            {"assistant_count": {"type": "integer", "minimum": 0}} if operation == "reply" else {})
        self.parameters = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def validate(self, arguments):
        if set(arguments) != set(self.parameters["properties"]):
            raise UserError("Parametri browser non validi.")
        if self.operation == "send" and (not isinstance(arguments["text"], str)
                or not 1 <= len(arguments["text"].strip()) <= 1800 or "\x00" in arguments["text"]):
            raise UserError("Messaggio browser non valido.")
        if self.operation == "reply" and (type(arguments["assistant_count"]) is not int or arguments["assistant_count"] < 0):
            raise UserError("Contatore della conversazione non valido.")
        return dict(arguments)

    def describe(self, arguments):
        return "Operazione sulla conversazione ChatGPT dedicata: " + self.operation

    def execute(self, arguments, context):
        context.checkpoint()
        grant = context.session_permission
        if not isinstance(grant, SessionPermission) or not grant.allows(context, ToolCall(self.name, json.dumps(arguments))):
            raise UserError("Operazione browser riservata a una sessione autonoma autorizzata.")
        if self.operation == "open":
            data = self.browser.open_chat(context)
        elif self.operation == "observe":
            data = self.browser.observe(context)
        elif self.operation == "send":
            data = self.browser.send(arguments["text"], context)
            data = {**data, "message_text": arguments["text"]}
        else:
            data = self.browser.wait_reply(arguments["assistant_count"], context)
        return ToolResult(json.dumps(data, ensure_ascii=False), data, observation=self.operation in {"observe", "reply"})
