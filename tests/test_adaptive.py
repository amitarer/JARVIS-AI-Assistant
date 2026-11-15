"""Recovery changes plans from evidence, without replaying uncertain side effects."""

from dataclasses import replace
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch,Mock

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.adaptive import compact_observations
from jarvis.core.models import ToolCall,ToolResult,UserError
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.tools.pc import InspectFilesTool
from jarvis.tools.desktop import InspectDesktopTool,DesktopActionTool
from tests.support import make_controller,temporary_project


class AdaptiveAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=temporary_project()
        self.controller=make_controller(Path(self.temp.name))
        self.controller.settings=replace(self.controller.settings,ollama=OllamaSettings(enabled=True,max_tool_rounds=8))
        self.controller.tools.register(InspectFilesTool())
        self.events=[]

    def tearDown(self):
        self.temp.cleanup()

    def run_task(self,turns):
        iterator=iter(turns)
        def chat(*args):
            turn=next(iterator)
            return turn(*args) if callable(turn) else turn
        with patch.object(OllamaProvider,"check",return_value={"model":"test"}), \
                patch.object(OllamaProvider,"recover_read",side_effect=UserError("Nessuna lettura alternativa proposta")), \
                patch.object(OllamaProvider,"chat",side_effect=chat):
            self.controller.run({"kind":"chat","text":"Leggi il file richiesto; cerca nella cartella se necessario."},threading.Event(),self.events.append,
                lambda request,ctx:self.controller.tools.policy.approvals.issue(request))

    def test_failed_read_replans_with_error_and_then_finishes(self):
        tool=self.controller.tools._tools["inspect_files"]
        call=ToolCall("inspect_files",json.dumps({"action":"read_text","path":str(Path(self.temp.name)/"appunti.txt")}))
        list_call=ToolCall("inspect_files",json.dumps({"action":"list","path":self.temp.name}))
        seen=[]
        def recovered(messages,schemas,ctx,on_chunk):
            seen.extend(messages)
            return "",[list_call],{}
        with patch.object(tool,"execute",side_effect=[UserError("File spostato: rileggi la cartella"),ToolResult('Elenco letto',{"read_only":True},observation=True),
                                                    ToolResult("Contenuto letto",{"read_only":True},observation=True)]):
            self.run_task([("",[call],{}),recovered,("",[call],{}),("Ecco il contenuto del file.",[],{})])
        self.assertTrue(any(m["role"]=="tool" and "File spostato" in m["content"] for m in seen))
        self.assertEqual(self.controller.repository.tasks()[0]["status"],"succeeded")
        self.assertEqual(len(self.controller.repository.operations()),3)

    def test_uncertain_write_is_never_retried(self):
        tool=self.controller.tools._tools["open_application"]
        with patch.object(tool,"execute",side_effect=UserError("Esito incerto")) as action:
            self.run_task([("",[ToolCall("open_application",'{"application_id":"blocco_note"}')],{})])
        self.assertEqual(action.call_count,1)
        self.assertEqual(self.controller.repository.tasks()[0]["status"],"failed")

    def test_failed_observation_discards_dependent_actions_in_same_batch(self):
        path=str(Path(self.temp.name)/"missing.txt")
        calls=[ToolCall("inspect_files",json.dumps({"action":"read_text","path":path})),
               ToolCall("open_application",'{"application_id":"blocco_note"}')]
        with patch.object(self.controller.tools._tools["open_application"],"execute") as action:
            self.run_task([("",calls,{}),("Non ho il contenuto richiesto.",[],{})])
        action.assert_not_called()
        self.assertEqual(self.controller.repository.tasks()[0]["status"],"failed")

    def test_three_identical_observations_stop_without_spinning(self):
        call=ToolCall("inspect_files",json.dumps({"action":"list","path":self.temp.name}))
        with patch.object(self.controller.tools._tools["inspect_files"],"execute",return_value=ToolResult("Identico",{},observation=True)) as read:
            self.run_task([("",[call],{})]*5)
        self.assertEqual(read.call_count,3)
        self.assertEqual(self.controller.repository.tasks()[0]["status"],"failed")

    def test_desktop_input_is_followed_by_fresh_observation(self):
        self.controller.tools.register(InspectDesktopTool())
        self.controller.tools.register(DesktopActionTool())
        action=self.controller.tools._tools["desktop_action"]
        inspect=self.controller.tools._tools["inspect_desktop"]
        order=[]
        def acted(args,ctx):
            order.append("input");return ToolResult("Input consegnato",{"input_delivered":True,"effect_verified":False})
        def observed(args,ctx):
            order.append("observe");return ToolResult("Stato nuovo",{"read_only":True},observation=True)
        with patch.object(action,"execute",side_effect=acted),patch.object(inspect,"execute",side_effect=observed):
            self.run_task([("",[ToolCall("desktop_action",'{"action":"focus","window_id":123}')],{}),("Fatto",[],{})])
        self.assertEqual(order,["input","observe"])
        self.assertEqual(next(e.data for e in self.events if e.kind=="response"),"Input consegnato")

    def test_compaction_preserves_latest_evidence_and_original_messages(self):
        messages=[{"role":"system","content":"Istruzioni"},{"role":"user","content":"Richiesta"}]
        self.assertEqual(compact_observations(messages),messages)
        messages.extend({"role":"tool","tool_name":"inspect_files","content":"x"*5000+str(n)} for n in range(4))
        compact=compact_observations(messages)
        self.assertTrue(json.loads(compact[2]["content"])["truncated"])
        self.assertEqual(compact[-1],messages[-1])
        self.assertEqual(len(messages[2]["content"]),5001)
