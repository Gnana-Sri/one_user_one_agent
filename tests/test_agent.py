import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from src.agent import OneViewerAgent, parse_ts, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data_pack" / "one_user_one_agent_pack"

class AgentTests(unittest.TestCase):
    def test_timestamp_parser(self):
        self.assertEqual(parse_ts("2026-10-01T00:00:00Z").tzinfo, timezone.utc)

    def test_profile_conflict_resolves_to_event_app_dialect(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        trigger = {"user_id": "U-00443", "app_dialect": "d5", "received_at": "2026-09-30T12:00:00Z",
                   "properties": {"deeplink": "ott://c/cmp/d2/title/T1"}}
        facts = agent.resolve(trigger)
        self.assertEqual(facts["dialect"], "d5")
        self.assertTrue(facts["dialect_conflicts"])

    def test_unmeasurable_goal_is_never_selected(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        facts = {"profile": {}, "events": [], "signup_at": now, "subscription_status": "unknown"}
        goal = agent.choose_goal(facts, now)
        self.assertNotEqual(goal["goal_id"] if goal else None, "G10")

    def test_holdout_is_never_actioned(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        uid = next(u for u, arm in agent.arms.items() if arm == "holdout")
        trigger = {"event_id": "test-event", "user_id": uid, "event": "app_open",
                   "received_at": "2026-10-01T12:00:00Z", "deliver_at": "2026-10-01T12:00:00Z",
                   "occurred_at": "2026-10-01T12:00:00Z", "app_dialect": "d1", "properties": {}}
        facts = agent.resolve(trigger)
        decision, action = agent.verify_and_act(trigger, facts, {"goal_id":"G02"}, parse_ts(trigger["deliver_at"]), "D-TEST")
        self.assertIsNone(action)
        self.assertIn("holdout", decision["no_action_reason"])

    def test_timeout_fault_fails_closed(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        agent_uid = next(u for u, arm in agent.arms.items() if arm == "agent")
        trigger = {"event_id": "5edb5b00-0773-4063-8da8-40929553233c", "user_id": agent_uid, "event": "app_open",
                   "received_at": "2026-10-01T12:00:00Z", "deliver_at": "2026-10-01T12:00:00Z",
                   "occurred_at": "2026-10-01T12:00:00Z", "app_dialect": "d1", "properties": {}}
        facts = agent.resolve(trigger)
        decision, action = agent.verify_and_act(trigger, facts, {"goal_id":"G02"}, parse_ts(trigger["deliver_at"]), "D-FAULT")
        self.assertIsNone(action)
        self.assertTrue(decision["fallback_used"])
        self.assertIn("timeout", decision["no_action_reason"])

    def test_corrected_g03_rule_changes_success_signal(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        now = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        facts = {"profile": {}, "events": [{"event":"play_started", "received_at": (now-timedelta(hours=2)).isoformat(), "properties": {}}, {"event":"episode_completed", "received_at": (now-timedelta(hours=1)).isoformat(), "properties": {}}],
                 "signup_at": now-timedelta(hours=12), "subscription_status": "unknown"}
        goal = agent.choose_goal(facts, now)
        self.assertIsNotNone(goal)
        self.assertEqual(goal["goal_id"], "G03")
        self.assertEqual(goal["success_event"], "play_started")
        self.assertIn("corrected", goal["rule_version"])

    def test_dependency_outage_fails_closed(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        agent_uid = next(u for u, arm in agent.arms.items() if arm == "agent")
        trigger = {"event_id": "dependency-test", "user_id": agent_uid, "event": "app_open",
                   "received_at": "2026-10-01T13:12:00Z", "deliver_at": "2026-10-01T13:12:00Z",
                   "occurred_at": "2026-10-01T13:12:00Z", "app_dialect": "d1", "properties": {}}
        facts = agent.resolve(trigger)
        decision, action = agent.verify_and_act(trigger, facts, {"goal_id":"G02"}, parse_ts(trigger["deliver_at"]), "D-OUTAGE")
        self.assertIsNone(action)
        self.assertTrue(decision["fallback_used"])
        self.assertIn("user_data_store_degraded", decision["no_action_reason"])

    def test_duplicate_event_ids_deduplicate_history(self):
        agent = OneViewerAgent(PACK, ROOT / "sample_run")
        uid = next(iter(agent.history))
        rows = [e for e in agent.history[uid] if e.get("event_id")]
        ids = [e["event_id"] for e in rows]
        self.assertEqual(len(ids), len(set(ids)))

if __name__ == "__main__":
    unittest.main()
