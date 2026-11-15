"""Task-bound WhatsApp tools, exact drafts and explicit sending approval."""

import json

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.tools.applications import normalized


class WhatsAppMessageTool:
    risk = Risk.MEDIUM

    def __init__(self, service, send=False):
        self.service, self.send_message = service, send
        self.risk = Risk.MEDIUM if send else Risk.LOW
        self.name = "send_whatsapp_message" if send else "prepare_whatsapp_message"
        self.description = ("Invia SOLO la bozza verificata in questo incarico: destinatario e testo esatti, conferma obbligatoria. Non ritentare un invio incerto."
                            if send else "Apri WhatsApp, cerca il contatto con nome esatto e prepara una bozza verificata SENZA inviare. Chiedi il testo se manca; non inventare destinatari.")
        self.parameters = {"type": "object", "properties": {
            "recipient": {"type": "string", "minLength": 1, "maxLength": 100},
            "text": {"type": "string", "minLength": 1, "maxLength": 400}},
            "required": ["recipient", "text"], "additionalProperties": False}

    def validate(self, arguments):
        if set(arguments) != {"recipient", "text"} or any(not isinstance(arguments[k], str)
                or not 1 <= len(arguments[k].strip()) <= limit or any(ord(c) < 32 for c in arguments[k])
                for k, limit in (("recipient", 100), ("text", 400))):
            raise UserError("Servono nome esatto del contatto e testo su una riga (massimo 400 caratteri).")
        if normalized(arguments["recipient"]) in {"miopadre", "miamadre", "miofratello", "miasorella", "mogenitore"}:
            raise UserError("Non conosco il nome WhatsApp di questa persona. Consulta whatsapp_contact o chiedi il nome esatto.")
        return {key: value.strip() for key, value in arguments.items()}

    def describe(self, arguments):
        return (("INVIA" if self.send_message else "Prepara senza inviare") +
                f" su WhatsApp a {arguments['recipient']}: «{arguments['text']}».")

    def execute(self, arguments, context):
        if self.send_message:
            context.whatsapp_draft = None
            return self.service.send(arguments["recipient"], arguments["text"], context)
        context.whatsapp_draft = None
        result = self.service.prepare(arguments["recipient"], arguments["text"], context)
        if result.evidence.get("draft_verified") is True:
            context.whatsapp_draft = dict(arguments)
        return result


class ConnectWhatsAppTool:
    name = "connect_whatsapp"
    risk = Risk.LOW
    description = "Apri WhatsApp Web nel profilo JARVIS per collegare il telefono con QR, senza leggere chat o inviare messaggi. Il collegamento e' manuale una sola volta."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, service):
        self.service = service

    def validate(self, arguments):
        if arguments:
            raise UserError("Il collegamento WhatsApp non accetta parametri.")
        return {}

    def describe(self, arguments):
        return "Apri il collegamento WhatsApp dedicato a JARVIS. Nessun messaggio viene inviato."

    def execute(self, arguments, context):
        return self.service.connect(context)


class WhatsAppContactTool:
    name = "whatsapp_contact"
    risk = Risk.LOW
    description = "Consulta un alias WhatsApp gia' memorizzato (lookup) o ricorda il nome esatto dichiarato dall'utente (remember). Non indovinare legami familiari."
    parameters = {"type": "object", "properties": {"action": {"type": "string", "enum": ["lookup", "remember"]},
                  "alias": {"type": "string", "minLength": 1, "maxLength": 100},
                  "name": {"type": "string", "maxLength": 100}}, "required": ["action", "alias"], "additionalProperties": False}

    def __init__(self, repository):
        self.repository = repository

    def validate(self, arguments):
        if (set(arguments) - {"action", "alias", "name"} or arguments.get("action") not in {"lookup", "remember"}
                or any(not isinstance(arguments.get(k, ""), str) or len(arguments.get(k, "")) > 100
                       or any(ord(c) < 32 for c in arguments.get(k, "")) for k in ("alias", "name"))
                or not arguments.get("alias", "").strip()
                or (arguments["action"] == "remember" and not arguments.get("name", "").strip())):
            raise UserError("Indica alias e, per ricordarlo, il nome esatto del contatto.")
        return {"action": arguments["action"], "alias": normalized(arguments["alias"]), "name": arguments.get("name", "").strip()}

    def risk_for(self, arguments):
        return Risk.MEDIUM if arguments["action"] == "remember" else Risk.LOW

    def describe(self, arguments):
        return f"Contatto WhatsApp: {arguments['alias']} → {arguments['name']} ({arguments['action']})."

    def execute(self, arguments, context):
        context.checkpoint()
        contacts = self.repository.preferences().get("whatsapp_contacts", {})
        if arguments["action"] == "remember":
            contacts[arguments["alias"]] = arguments["name"]
            self.repository.set_preference("whatsapp_contacts", contacts)
        return ToolResult(json.dumps({"alias": arguments["alias"], "name": contacts.get(arguments["alias"]),
                          "known": arguments["alias"] in contacts}, ensure_ascii=False), observation=True)
