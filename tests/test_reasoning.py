"""Reasoning must improve evidence and preserve speed, privacy and tool boundaries."""

from contextlib import contextmanager
from dataclasses import replace
from fractions import Fraction
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.brain.routing import requests_deep_reasoning
from jarvis.core.adaptive import compact_observations
from jarvis.core.agent import conversation_context
from jarvis.core.models import Message, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.tools.calculate import CalculateTool, evaluate
from tests.support import make_controller, temporary_project


class CalculatorTests(unittest.TestCase):
    def test_arithmetic_preserves_exact_decimal_and_large_integer_results(self):
        self.assertEqual(evaluate("0.1+0.2"), Fraction(3, 10))
        self.assertEqual(evaluate("987654321*123456789"), 121932631112635269)
        self.assertEqual(evaluate("240*(1-25/100)*(1+22/100)"), Fraction(1098, 5))
        self.assertEqual(evaluate("2**-3"), Fraction(1, 8))

    def test_calls_names_attributes_and_non_arithmetic_syntax_are_never_executed(self):
        for expression in ("__import__('os').getcwd()", "open('secret')", "True", "1<2", "[1,2]", "1 if 2 else 3", "(1).__class__"):
            with self.subTest(expression=expression), self.assertRaises(UserError):
                evaluate(expression)

    def test_resource_limits_and_invalid_operations_are_reported(self):
        for expression in ("2**1000000", "1/0", "0**-1", "9**(9**9)", "+"*30+"1", "1+"*300+"1"):
            with self.subTest(expression=expression), self.assertRaises(UserError):
                evaluate(expression)

    def test_repeating_decimal_is_not_presented_as_exact_decimal(self):
        tool=CalculateTool()
        context=TaskContext("math",threading.Event(),5)
        third=tool.execute(tool.validate({"expression":"1/3"}),context)
        self.assertEqual(third.evidence["result"],"1/3")
        self.assertFalse(third.evidence["decimal_is_exact"])
        finite=tool.execute(tool.validate({"expression":"0.1+0.2"}),context)
        self.assertEqual(finite.evidence["result"],"0.3")
        self.assertTrue(finite.evidence["decimal_is_exact"])


class ReasoningProviderTests(unittest.TestCase):
    def provider(self):
        return OllamaProvider(OllamaSettings(enabled=True))

    def stream(self, provider, replies):
        bodies=[]
        iterator=iter(replies)
        @contextmanager
        def response(method,path,body,context):
            bodies.append(body)
            yield io.BytesIO(b"".join(json.dumps(row).encode()+b"\n" for row in next(iterator)))
        return response,bodies

    def test_deep_mode_filters_private_channels_and_emits_only_verified_final_content(self):
        provider=self.provider();provider.reasoning_mode=True
        response,bodies=self.stream(provider,[[{"message":{"thinking":"PRIVATE SENTINEL","content":""}},
            {"message":{"content":"<think>HIDDEN</think>Conclusione controllata."},"done":True,"done_reason":"stop"}]])
        chunks=[]
        with patch.object(provider,"_response",response):
            text,calls,usage=provider.chat([],[],TaskContext("deep",threading.Event(),60),chunks.append)
        self.assertTrue(bodies[0]["think"])
        self.assertEqual(text,"Conclusione controllata.")
        self.assertEqual(chunks,[text])
        self.assertNotIn("SENTINEL",str((chunks,usage)))
        self.assertNotIn("HIDDEN",str((chunks,usage)))
        self.assertTrue(usage["thinking_enabled_requested"])

    def test_exhausted_thinking_budget_retries_original_input_once_without_partial_calls(self):
        provider=self.provider();provider.reasoning_mode=True
        original=[{"role":"user","content":"Problema pubblico"}]
        response,bodies=self.stream(provider,[[{"message":{"thinking":"PRIVATE","content":"Non concluso",
            "tool_calls":[{"function":{"name":"calculate","arguments":{"expression":"1+1"}}}]},"done":True,"done_reason":"length"}],
            [{"message":{"content":"Risposta finale."},"done":True,"done_reason":"stop"}]])
        chunks=[]
        with patch.object(provider,"_response",response):
            text,calls,usage=provider.chat(original,[],TaskContext("bounded",threading.Event(),60),chunks.append)
        self.assertEqual([b["think"] for b in bodies],[True,False])
        self.assertEqual(bodies[1]["messages"],original)
        self.assertEqual(calls,[])
        self.assertEqual("".join(chunks),"Risposta finale.")
        self.assertTrue(usage["reasoning_fallback_used"])

    def test_only_one_deep_pass_and_no_deep_request_near_task_deadline(self):
        for remaining,used in ((10,False),(60,True)):
            provider=self.provider();provider.reasoning_mode=True;provider.reasoning_pass_used=used
            response,bodies=self.stream(provider,[[{"message":{"content":"Risposta"},"done":True}]])
            with patch.object(provider,"_response",response):
                provider.chat([],[],TaskContext("bounded",threading.Event(),remaining),lambda *_:None)
            self.assertFalse(bodies[0]["think"])

    def test_reasoning_route_is_distinct_from_quick_conversation(self):
        provider=self.provider()
        selection={"request_type":"reasoning","application":"","target":"","operations":[],"query":"","limit":20,"answer":""}
        with patch.object(provider,"_json",return_value={"message":{"content":json.dumps(selection)}}):
            calls=provider.select_initial_tools([{"role":"user","content":"Risolvi un problema logico"}],
                [{"name":"get_current_datetime","description":"Clock"}],TaskContext("route",threading.Event(),60))
        self.assertTrue(provider.reasoning_mode)
        self.assertFalse(provider.requires_execution)
        self.assertEqual(calls,[])

    def test_recovery_uses_supported_schema_and_rejects_non_read_tools(self):
        provider=self.provider()
        schemas=[{"name":"inspect_files","parameters":{"type":"object"}}, {"name":"send_whatsapp_message","parameters":{"type":"object"}}]
        invalid={"message":{"content":json.dumps({"tool":"send_whatsapp_message","arguments":{}})}}
        with patch.object(provider,"_json",return_value=invalid) as request,self.assertRaises(UserError):
            provider.recover_read([{"role":"user","content":"Leggi il file"}],schemas,ToolCall("inspect_files","{}"),TaskContext("recover",threading.Event(),5))
        format=request.call_args.args[2]["format"]
        self.assertNotIn("oneOf",format)
        self.assertEqual(format["properties"]["tool"]["enum"],["inspect_files"])

    def test_review_uses_only_public_problem_draft_and_bounded_observations(self):
        provider=self.provider()
        value={"message":{"content":json.dumps({"answer":"Conclusione corretta.","status":"revised"})}}
        with patch.object(provider,"_json",return_value=value) as request:
            answer,usage=provider.review_answer([{"role":"user","content":"Problema originale"},
                {"role":"tool","content":"Osservazione pubblica"}],"Bozza pubblica",TaskContext("review",threading.Event(),60))
        body=request.call_args.args[2]
        self.assertFalse(body["think"])
        self.assertNotIn("tools",body)
        self.assertIn("Problema originale",body["messages"][-1]["content"])
        self.assertEqual(answer,"Conclusione corretta.")
        self.assertEqual(usage["self_review_status"],"revised")


class ContextAndRoutingTests(unittest.TestCase):
    def test_inconsistent_draft_never_reaches_ui_before_review(self):
        with temporary_project() as folder:
            c=make_controller(Path(folder));c.settings=replace(c.settings,ollama=OllamaSettings(enabled=True))
            c.tools=build_tool_registry(c.settings,c.repository);events=[]
            with patch.object(OllamaProvider,"check",return_value={}), \
                    patch.object(OllamaProvider,"chat",return_value=("BOZZA CONTRADDITTORIA",[],{})), \
                    patch.object(OllamaProvider,"review_answer",return_value=("Conclusione controllata.",{"stage":"answer_review"})):
                c.run({"kind":"chat","text":"Risolvi questo problema logico"},threading.Event(),events.append,lambda *_:None)
            self.assertNotIn("BOZZA CONTRADDITTORIA",str(events))
            self.assertEqual(c.repository.messages()[-1].content,"Conclusione controllata.")
            self.assertTrue(any(e.kind=="reasoning_mode" and e.data.get("stage")=="review" for e in events))

    def test_calendar_validator_rejects_wrong_duration_and_duplicate_worker_assignments(self):
        from scripts.verify_reasoning import valid_schedule
        self.assertTrue(valid_schedule("A: L1, 0-6; B: L1, 6-10; C: L2, 0-5; D: L1, 10-13"))
        self.assertTrue(valid_schedule("A (0-6) su L1; B (6-10) e C (0-5) su L2; D (10-13) su L1"))
        self.assertFalse(valid_schedule("A (0-6) su L1; B (6-10) e C (0-6) su L2; D (10-13) su L1"))
        self.assertFalse(valid_schedule("A: L1, 0-6; B: L1, 6-10; C: L2, 0-6; D: L1, 10-13"))
        self.assertFalse(valid_schedule("A: L1, 0-6; B: L1, 6-10; C: L1, 0-5; D: L1, 10-13"))
    def test_explicit_analytical_fast_path_never_intercepts_a_message_or_pending_reply(self):
        self.assertTrue(requests_deep_reasoning("Trova il colpevole con questi vincoli"))
        self.assertFalse(requests_deep_reasoning("Scrivi a Paolo: trova il colpevole"))
        self.assertFalse(requests_deep_reasoning("Trova il colpevole", "Scrivi a mio padre"))
        self.assertFalse(requests_deep_reasoning("Ciao"))

    def test_explicit_logic_skips_the_small_routing_generation(self):
        provider=OllamaProvider(OllamaSettings(enabled=True))
        with patch.object(provider,"_json") as inference:
            provider.select_initial_tools([{"role":"user","content":"Risolvi un problema logico con vincoli"}],[],TaskContext("route",threading.Event(),60))
        inference.assert_not_called()
        self.assertTrue(provider.reasoning_mode)

    def test_truncated_router_is_repaired_without_reusing_or_executing_partial_output(self):
        provider=OllamaProvider(OllamaSettings(enabled=True))
        replies=[{"done_reason":"length","message":{"content":"{incompleto"}},
                 {"message":{"content":'{"kind":"task"}'}}]
        with patch.object(provider,"_json",side_effect=replies) as inference:
            calls=provider.select_initial_tools([{"role":"user","content":"Apri un programma e controlla il risultato"}],
                [{"name":"get_current_datetime","description":"Clock"}],TaskContext("route",threading.Event(),60))
        self.assertEqual(calls,[])
        self.assertTrue(provider.requires_execution)
        self.assertEqual(inference.call_count,2)
        self.assertNotIn("incompleto",str(inference.call_args))

    def test_long_current_request_keeps_both_the_initial_constraint_and_final_goal(self):
        request="NON INVIARE MESSAGGI. "+"dato "*1450+" FINE RICHIESTA"
        messages=conversation_context([Message("assistant","old "*2000,""),Message("user",request,"")])
        self.assertEqual(messages[-1]["content"],request)
        self.assertLessEqual(sum(len(m["content"]) for m in messages),11000)

    def test_compaction_keeps_tail_facts_and_bounds_many_tool_observations(self):
        messages=[{"role":"tool","content":"inizio "+"x"*4000+" IMPORTANTE ALLA FINE"} for _ in range(50)]
        compact=compact_observations(messages)
        first=json.loads(compact[-4]["content"])
        self.assertTrue(first["truncated"])
        self.assertIn("IMPORTANTE ALLA FINE",first["tail"])
        self.assertLess(sum(len(m["content"]) for m in compact),30000)
        self.assertTrue(messages[0]["content"].endswith("IMPORTANTE ALLA FINE"))

    def test_direct_calculation_finishes_with_exact_tool_result_without_second_inference(self):
        with temporary_project() as folder:
            c=make_controller(Path(folder));c.settings=replace(c.settings,ollama=OllamaSettings(enabled=True))
            c.tools=build_tool_registry(c.settings,c.repository)
            selection={"request_type":"calculation","application":"","target":"0.1+0.2","operations":[],"query":"","limit":20,"answer":""}
            events=[]
            with patch.object(OllamaProvider,"check",return_value={}),patch.object(OllamaProvider,"_json",return_value={"message":{"content":json.dumps(selection)}}) as infer,patch.object(OllamaProvider,"chat") as deep:
                c.run({"kind":"chat","text":"Quanto fa 0.1+0.2?"},threading.Event(),events.append,lambda *_:None)
            self.assertEqual(infer.call_count,1)
            deep.assert_not_called()
            self.assertEqual(c.repository.tasks()[0]["status"],"succeeded")
            self.assertIn("= 0.3",c.repository.tasks()[0]["result_text"])
            self.assertEqual(c.repository.operations()[0]["tool"],"calculate")
