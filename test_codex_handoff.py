import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import codex_handoff as bridge
import codex_review_worker as worker
from update_storage import write_json
from update_progress import activity_caption, update_detail_text


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, LOCALAPPDATA=self.temp.name)
        env.start()
        self.addCleanup(env.stop)
        self.owner = "00000000-0000-4000-8000-000000000001"
        write_json(bridge.folder()/"codex_handoff_settings.json", {
            "enabled": True, "dispatch_mode": "codex_queue", "target_thread_id": self.owner})
        self.source = "Country — Finland"
        self.url = "https://www.finlex.fi/fi/lainsaadanto/1978/38"
        write_json(bridge.folder()/"knowledge_coverage_latest.json", {"changed": [self.source],
            "pending_source_fingerprints": {self.source: {self.url: "a"*64}}})
        self.failure = {"state": "retry_pending", "source_errors": {self.source: {
            "reason": "新旧官方正文不可用 secret-token-not-to-export"}}}

    def test_tickets_are_deduplicated_and_allowlisted(self):
        bridge.submit(self.failure)
        bridge.submit(self.failure)
        queue = bridge.read("codex_repair_requests.json")
        self.assertEqual(len(queue["requests"]), 1)
        self.assertNotIn("secret-token", json.dumps(queue))
        self.assertEqual(bridge.summary()["state"], "queued")

    def test_event_dispatch_is_once_not_recurring(self):
        bridge.submit(self.failure)
        with patch.object(worker, "locate_codex", return_value=Path("synthetic-codex.exe")), patch("subprocess.run", return_value=Mock(returncode=0)) as call:
            self.assertEqual(bridge.dispatch()["state"], "awaiting_chat")
            bridge.dispatch()
        call.assert_called_once()
        args = call.call_args.args[0]
        self.assertEqual(args[1:4], ["queue", "--thread", self.owner])
        self.assertNotIn("dangerously", " ".join(args))

    def test_send_failure_is_not_claimed_delivered(self):
        bridge.submit(self.failure)
        with patch.object(worker, "locate_codex", return_value=Path("synthetic-codex.exe")), patch("subprocess.run", side_effect=subprocess.TimeoutExpired("queue",45)):
            result = bridge.dispatch()
        self.assertEqual(result["state"], "queued")
        self.assertTrue(result["delivery_failed"])

    def test_claim_is_distinct_from_delivery_and_resolution(self):
        bridge.submit(self.failure)
        ids = list(bridge.read("codex_repair_requests.json")["requests"])
        with self.assertRaises(ValueError):
            bridge.claim(ids, "another-chat")
        bridge.claim(ids, self.owner)
        self.assertEqual(bridge.summary()["state"], "processing")
        self.assertTrue(bridge.defer_source(self.source))
        self.assertEqual(bridge.read("codex_repair_requests.json")["requests"][ids[0]]["state"], "processing")

    def test_ticket_does_not_close_when_report_or_approval_missing(self):
        bridge.submit(self.failure)
        pack = {"rulepack_version": "fixture", "reviewed_source_fingerprints": {}}
        with patch("rulepack_manager.load_rulepack", return_value=pack):
            bridge.reconcile()
        self.assertEqual(bridge.summary()["pending"], 1)
        write_json(bridge.folder()/"knowledge_coverage_latest.json", {"changed": [], "unreachable": [],
            "rulepack_version": "fixture", "observed_source_fingerprints": {self.source: {self.url:"a"*64}}})
        with patch("rulepack_manager.load_rulepack", return_value=pack):
            bridge.reconcile()
        self.assertEqual(bridge.summary()["pending"], 1)
        pack["reviewed_source_fingerprints"] = {self.source:{self.url:"a"*64}}
        with patch("rulepack_manager.load_rulepack", return_value=pack):
            bridge.reconcile()
        self.assertEqual(bridge.summary()["pending"], 0)

    def test_local_prior_snapshot_recovered_without_cloud(self):
        body = "Applicable consumer law official body. "*80
        digest = hashlib.sha256(body.encode()).hexdigest()
        doc = {"url": self.url, "normalized_text": body}
        write_json(worker.folder()/"codex_review/evidence"/(digest+".json"), doc)
        with patch.object(worker, "_http_json") as remote:
            self.assertEqual(worker.prior_document(digest,self.url), doc)
        remote.assert_not_called()

    def test_mismatched_prior_snapshot_is_not_used(self):
        digest = "a"*64
        write_json(worker.folder()/"codex_review/evidence"/(digest+".json"), {"url":self.url,"normalized_text":"untrusted body"*100})
        with patch.object(worker, "_http_json", side_effect=worker.ReviewError("no official history")):
            with self.assertRaises(worker.ReviewError):
                worker.prior_document(digest,self.url)


class TransparentProgressTests(unittest.TestCase):
    def test_elapsed_and_liveness_do_not_invent_progress(self):
        now = datetime(2026,10,12,tzinfo=timezone.utc)
        update = {"state":"reviewing","heartbeat_at":now.isoformat(),
                  "last_event_at":(now-timedelta(minutes=3)).isoformat(),
                  "operation_started_at":(now-timedelta(minutes=3)).isoformat(),"model_running":True}
        text = activity_caption({"update_status":update},now)
        self.assertIn("3分00秒",text)
        self.assertIn("等待输出",text)
        update["heartbeat_at"] = (now-timedelta(seconds=60)).isoformat()
        self.assertIn("可能已卡住",activity_caption({"update_status":update},now))

    def test_detail_explains_stage_not_country_completion(self):
        text = update_detail_text({"update_status":{"state":"reviewing","stage":"verifying","progress_percent":55,
            "operation":"独立复核结论","model_round":2,"source_index":3,"source_total":7}})
        self.assertIn("步骤 4/8",text)
        self.assertIn("3/7",text)
        self.assertIn("不是全部国家完成率",text)
        self.assertIn("2/2",text)

    def test_accepted_queue_is_not_shown_as_repaired(self):
        text = activity_caption({"update_status":{"state":"retry_pending","handoff":{"state":"awaiting_chat"}}})
        self.assertIn("等待接手",text)
        self.assertIn("尚未完成修复",text)


class ReviewActivityTests(unittest.TestCase):
    def test_model_wait_records_activity_without_resending_prompt(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,LOCALAPPDATA=directory,OPENAI_API_KEY="never-export-this"):
            process = Mock(pid=123456,returncode=0)
            process.poll.return_value = None
            calls = [0]
            def communicate(**kwargs):
                calls[0] += 1
                if calls[0] == 1:
                    raise subprocess.TimeoutExpired("synthetic",5,output=b'{"type":"turn.started"}\n')
                write_json(worker.folder()/"codex_review/model_workspace/proposal_result.json", {"fixture":True})
                return ('{"item":{"type":"agent_message"}}\n','')
            process.communicate.side_effect = communicate
            auth = subprocess.CompletedProcess([],0,"Logged in using ChatGPT","")
            with patch.object(worker,"locate_codex",return_value=Path("synthetic-codex.exe")), \
                 patch("subprocess.run",return_value=auth), patch("subprocess.Popen",return_value=process) as start:
                result = worker.codex_json("public legal fixture",{},"proposal")
            self.assertEqual(result,{"fixture":True})
            self.assertEqual(process.communicate.call_args_list[0].kwargs["input"],"public legal fixture")
            self.assertIsNone(process.communicate.call_args_list[1].kwargs["input"])
            self.assertNotIn("OPENAI_API_KEY",start.call_args.kwargs["env"])
            status = json.loads((worker.folder()/"codex_review_status.json").read_text(encoding="utf-8"))
            self.assertFalse(status["model_running"])
            self.assertIn("last_model_output_at",status)

    def test_model_deadline_kills_only_its_own_process(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,LOCALAPPDATA=directory):
            process = Mock(pid=123456,returncode=0)
            process.poll.return_value = None
            process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic",5),('','')]
            auth = subprocess.CompletedProcess([],0,"Logged in using ChatGPT","")
            with patch.object(worker,"locate_codex",return_value=Path("synthetic-codex.exe")), \
                 patch("subprocess.run",return_value=auth), patch("subprocess.Popen",return_value=process), \
                 patch.object(worker.time,"monotonic",side_effect=[0,901]):
                with self.assertRaises(worker.ReviewError):
                    worker.codex_json("public legal fixture",{},"proposal")
            process.kill.assert_called_once()

    def test_runtime_signal_does_not_reset_last_effective_event(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,LOCALAPPDATA=directory):
            first = worker.record("reviewing",operation="审查")
            worker.touch_runtime(model_running=True)
            current = json.loads((worker.folder()/"codex_review_status.json").read_text(encoding="utf-8"))
        self.assertEqual(first["last_event_at"],current["last_event_at"])
        self.assertTrue(current["model_running"])


if __name__ == "__main__":
    unittest.main()
