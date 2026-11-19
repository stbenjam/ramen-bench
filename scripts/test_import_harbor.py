"""ATIF-to-site conversion for Harbor runs."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_harbor
from import_harbor import INSTRUCTION, register, transcript_events, usage, user_text
from list_prices import list_cost


class TranscriptEventsTest(unittest.TestCase):
    def test_keeps_public_activity_and_drops_private_content(self):
        steps = [
            {"source": "system", "message": "You are an agent."},
            {
                "source": "user",
                "message": "<environment_context>cwd</environment_context>",
            },
            {"source": "user", "message": INSTRUCTION},
            {
                "source": "agent",
                "timestamp": "2026-11-17T18:39:28.263Z",
                "message": "Drawing the bowl.",
                "reasoning_content": "hidden",
                "tool_calls": [
                    {
                        "tool_call_id": "a",
                        "function_name": "exec",
                        "arguments": {"cmd": "ls"},
                    },
                    {
                        "tool_call_id": "b",
                        "function_name": "agent_mail",
                        "arguments": {},
                    },
                ],
                "observation": {
                    "results": [
                        {"source_call_id": "a", "content": "index.html"},
                        {"source_call_id": "b", "content": "private"},
                    ]
                },
            },
        ]
        events, omitted = transcript_events(steps)
        self.assertEqual(
            [
                (e["type"], e.get("role") or e.get("tool") or e.get("callId"))
                for e in events
            ],
            [
                ("message", "user"),
                ("message", "assistant"),
                ("tool_call", "exec"),
                ("tool_result", "a"),
            ],
        )
        self.assertEqual(omitted, 1)
        self.assertNotIn("hidden", json.dumps(events))


class UserTextTest(unittest.TestCase):
    def test_unwraps_antigravity_user_request(self):
        message = f"<USER_REQUEST>\n{INSTRUCTION}\n\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nlocal time\n</ADDITIONAL_METADATA>"
        self.assertEqual(user_text(message), INSTRUCTION)
        self.assertEqual(user_text(INSTRUCTION), INSTRUCTION)


class UsageTest(unittest.TestCase):
    def test_maps_atif_final_metrics(self):
        trajectory = {
            "final_metrics": {
                "total_prompt_tokens": 100,
                "total_completion_tokens": 20,
                "total_cached_tokens": 60,
                "total_cost_usd": 1.5,
                "extra": {
                    "total_cache_creation_input_tokens": 10,
                    "reasoning_output_tokens": 5,
                },
            }
        }
        result = usage(trajectory, "unpriced", 3)[0]
        self.assertEqual(
            result["tokens"],
            {
                "input": 100,
                "cachedInput": 60,
                "cacheCreationInput": 10,
                "reasoning": 5,
                "output": 20,
                "total": 120,
            },
        )
        self.assertEqual(
            result["cost"], {"currency": "USD", "total": 1.5, "estimated": True}
        )
        self.assertEqual(result["toolCalls"], 3)

    def test_unrecorded_cost_stays_unknown(self):
        trajectory = {
            "final_metrics": {"total_prompt_tokens": 1, "total_completion_tokens": 1}
        }
        self.assertIsNone(usage(trajectory, "unpriced", 0)[0]["cost"])


class ListPriceTest(unittest.TestCase):
    def step(self, prompt, cached, completion, writes=0):
        extra = {"cache_write_input_tokens": writes}
        return {
            "metrics": {
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "completion_tokens": completion,
                "extra": extra,
            }
        }

    def trajectory(self, *steps):
        return {"steps": list(steps)}

    def test_prices_each_request_at_its_context_tier(self):
        steps = self.trajectory(self.step(100_000, 0, 0), self.step(300_000, 0, 0))
        cost, evidence = list_cost("openai/gpt-6.2-sol", steps)
        # 100K short-context at $2/M plus 300K long-context at $4/M.
        self.assertAlmostEqual(cost["total"], 0.2 + 1.2)
        self.assertEqual(evidence["longContextRequests"], 1)

    def test_splits_cached_input_and_output(self):
        steps = self.trajectory(self.step(200_000, 100_000, 50_000))
        cost, _ = list_cost("openai/gpt-6.2-astra", steps)
        # Short context: 100K uncached at $8/M, 100K cached at $0.40/M, 50K out at $40/M.
        self.assertAlmostEqual(cost["input"], 0.8)
        self.assertAlmostEqual(cost["cachedInput"], 0.04)
        self.assertAlmostEqual(cost["output"], 2.0)

    def test_flat_rates_price_run_totals(self):
        trajectory = {
            "steps": [],
            "final_metrics": {
                "total_prompt_tokens": 1_000_000,
                "total_cached_tokens": 800_000,
                "total_completion_tokens": 100_000,
            },
        }
        cost, evidence = list_cost("openrouter/google/gemini-4-neon", trajectory)
        # 200K uncached at $3/M, 800K cached at $0.15/M, 100K out at $15/M.
        self.assertAlmostEqual(cost["total"], 0.6 + 0.12 + 1.5)
        self.assertNotIn("longContextRequests", evidence)

    def test_unknown_model_cache_writes_or_missing_requests_stay_unpriced(self):
        self.assertIsNone(list_cost("unpriced", self.trajectory(self.step(1, 0, 1))))
        writes = self.trajectory(self.step(10, 0, 1, writes=5))
        self.assertIsNone(list_cost("openai/gpt-6.2-sol", writes))
        self.assertIsNone(list_cost("openai/gpt-6.2-sol", self.trajectory()))


class RegisterTest(unittest.TestCase):
    def registered(self, runs, ids):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "registry.json").write_text(
                json.dumps({"runs": runs, "modelAddedAt": {}})
            )
            with mock.patch.object(import_harbor, "RUNS", root):
                register([{"id": run_id} for run_id in ids])
            return json.loads((root / "registry.json").read_text())

    def test_new_model_goes_first_among_its_vendor(self):
        registry = self.registered(
            ["anthropic/a/high/run.json", "openai/old/high/run.json"],
            ["openai/new/low", "openai/new/max"],
        )
        self.assertEqual(
            registry["runs"],
            [
                "anthropic/a/high/run.json",
                "openai/new/max/run.json",
                "openai/new/low/run.json",
                "openai/old/high/run.json",
            ],
        )
        self.assertIn("openai/new", registry["modelAddedAt"])

    def test_existing_model_keeps_its_position(self):
        registry = self.registered(
            [
                "openai/a/low/run.json",
                "openai/b/high/run.json",
                "openai/b/low/run.json",
            ],
            ["openai/b/max"],
        )
        self.assertEqual(
            registry["runs"],
            [
                "openai/a/low/run.json",
                "openai/b/max/run.json",
                "openai/b/high/run.json",
                "openai/b/low/run.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
