"""Evidence and accounting checks for native Harbor Claude imports."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_list_prices import model_usage_list_cost
from import_harbor_claude import ROOT, build_trial, native_usage


class HarborClaudeTests(unittest.TestCase):
    def fixture(self, trial):
        artifact = b"<!doctype html>\r\n<html>ramen</html>\r\n"
        rows = [
            {
                "type": "user",
                "message": {
                    "content": (ROOT / "harbor/ramen/instruction.md").read_text()
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "fixture-message",
                    "model": "claude-haiku-5-5",
                    "content": [
                        {"type": "thinking", "thinking": "private fixture reasoning"},
                        {
                            "type": "tool_use",
                            "id": "fixture-write",
                            "name": "Write",
                            "input": {
                                "file_path": "/app/index.html",
                                "content": artifact.decode(),
                            },
                        },
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 30,
                        "cache_creation_input_tokens": 40,
                        "output_tokens_details": {"thinking_tokens": 5},
                    },
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "fixture-write",
                            "content": "Created index.html",
                        }
                    ]
                },
            },
        ]
        result = {
            "id": "fixture-trial",
            "exception_info": None,
            "task_checksum": "fixture-task",
            "agent_info": {"name": "claude-code", "version": "2.1.295"},
            "agent_execution": {
                "started_at": "2026-10-08T10:00:00Z",
                "finished_at": "2026-10-08T10:00:01Z",
            },
            "agent_result": {
                "n_input_tokens": 80,
                "n_cache_tokens": 30,
                "n_output_tokens": 20,
                "cost_usd": 0.25,
            },
        }
        completion = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "fixture-session",
            "total_cost_usd": 0.25,
            "modelUsage": {"claude-haiku-5-5": {"costUSD": 0.25, "costBasis": "list"}},
        }
        init = {
            "type": "system",
            "subtype": "init",
            "model": "claude-haiku-5-5",
            "claude_code_version": "2.1.295",
            "session_id": "fixture-session",
        }
        documents = {
            "config.json": {
                "agent": {
                    "name": "claude-code",
                    "model_name": "anthropic/claude-haiku-5-5",
                    "kwargs": {"reasoning_effort": "max"},
                }
            },
            "result.json": result,
            "artifacts/manifest.json": [
                {
                    "source": "/app/index.html",
                    "destination": "artifacts/app/index.html",
                    "status": "ok",
                }
            ],
        }
        for name, value in documents.items():
            path = trial / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        path = trial / "agent/sessions/projects/-app/fixture-session.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        (trial / "agent/claude-code.txt").write_text(
            "".join(json.dumps(event) + "\n" for event in (init, completion))
        )
        path = trial / "artifacts/app/index.html"
        path.parent.mkdir(parents=True)
        path.write_bytes(artifact)
        return rows, result, completion

    def test_import_preserves_bytes_and_excludes_hidden_reasoning(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            self.fixture(trial)
            run, transcript, artifact = build_trial(trial)
            self.assertEqual(run["id"], "anthropic/haiku-5.5/max")
            self.assertEqual(run["usage"]["tokens"]["total"], 100)
            self.assertEqual(run["usage"]["tokens"]["reasoning"], 5)
            self.assertTrue(run["usage"]["cost"]["estimated"])
            self.assertEqual(run["timing"]["wallDurationMs"], 1000)
            self.assertEqual(run["resultStats"]["bytes"], len(artifact.read_bytes()))
            self.assertNotIn("private fixture reasoning", json.dumps(transcript))
            self.assertEqual(
                transcript["events"][0]["content"],
                (ROOT / "harbor/ramen/instruction.md").read_text().strip(),
            )

    def test_maps_each_supported_model_to_its_run(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            self.fixture(trial)
            for path in trial.rglob("*"):
                if path.is_file() and path.suffix in (".json", ".jsonl", ".txt"):
                    path.write_text(
                        path.read_text().replace("claude-haiku-5-5", "claude-fable-5-2")
                    )
            run, _, _ = build_trial(trial)
            self.assertEqual(run["id"], "anthropic/fable-5.2/max")
            self.assertEqual(run["model"]["providerModelId"], "claude-fable-5-2")

    def test_cli_diagnostic_lines_are_retained_outside_the_event_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            self.fixture(trial)
            path = trial / "agent/claude-code.txt"
            first, *rest = path.read_text().splitlines()
            line = '[claude-code:unrecognized_model] {"model":"claude-haiku-5-5"}'
            path.write_text("\n".join([first, line, *rest]) + "\n")
            run, _, _ = build_trial(trial)
            self.assertEqual(run["usage"]["raw"]["claudeCodeDiagnostics"], [line])
            path.write_text("\n".join([first, "not json", *rest]) + "\n")
            with self.assertRaises(ValueError):
                build_trial(trial)

    def test_rejects_changed_artifact_even_with_equivalent_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            self.fixture(trial)
            path = trial / "artifacts/app/index.html"
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
            with self.assertRaisesRegex(ValueError, "final recorded write"):
                build_trial(trial)

    def test_shell_edited_artifact_falls_back_to_harbor_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            rows, _, _ = self.fixture(trial)
            rows[1]["message"]["content"].append(
                {
                    "type": "tool_use",
                    "id": "fixture-sed",
                    "name": "Bash",
                    "input": {"command": "sed -i 's/ramen/bowl/' /app/index.html"},
                }
            )
            path = trial / "agent/sessions/projects/-app/fixture-session.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            path = trial / "artifacts/app/index.html"
            path.write_bytes(path.read_bytes().replace(b"ramen", b"bowl"))
            run, _, _ = build_trial(trial)
            self.assertTrue(
                run["usage"]["raw"]["artifactVerification"].startswith(
                    "Harbor artifact collection"
                )
            )
            self.assertIn("Harbor's collected /app/index.html", run["notes"])

    def test_rejects_failed_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            _, _, completion = self.fixture(trial)
            completion["is_error"] = True
            path = trial / "agent/claude-code.txt"
            path.write_text(
                path.read_text().splitlines()[0] + "\n" + json.dumps(completion) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "did not complete"):
                build_trial(trial)

    def test_unknown_cost_is_not_promoted_and_usage_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            rows, result, completion = self.fixture(Path(directory))
            self.assertEqual(
                native_usage(rows, result, completion)["cost"]["total"], 0.25
            )
            completion["hasUnknownModelCost"] = True
            self.assertIsNone(native_usage(rows, result, completion)["cost"])
            completion["hasUnknownModelCost"] = False
            completion["modelUsage"]["claude-haiku-5-5"]["costBasis"] = "unknown"
            self.assertIsNone(native_usage(rows, result, completion)["cost"])
            result["agent_result"]["n_input_tokens"] += 1
            with self.assertRaisesRegex(ValueError, "usage disagrees"):
                native_usage(rows, result, completion)

    def test_unpriced_model_uses_list_rates_that_match_recorded_cli_prices(self):
        # Fable 5.2 Max as Claude Code 2.1.322 recorded it with costBasis "list".
        recorded = {
            "inputTokens": 4839,
            "outputTokens": 455809,
            "cacheReadInputTokens": 26762291,
            "cacheCreationInputTokens": 718835,
            "cacheCreationEphemeral5mInputTokens": 11543,
            "cacheCreationEphemeral1hInputTokens": 707292,
            "webSearchRequests": 0,
        }
        usage = {"speed": "standard", "inference_geo": "global"}
        cost, evidence = model_usage_list_cost({"claude-fable-5-2": recorded}, usage)
        self.assertAlmostEqual(cost["total"], 35.0556322, places=9)
        self.assertTrue(cost["estimated"])
        self.assertEqual(evidence["usdPerMillionTokens"]["claude-fable-5-2"]["input"], 8)
        for change in (
            {"speed": "fast"},
            {"inference_geo": "us"},
        ):
            self.assertIsNone(
                model_usage_list_cost({"claude-fable-5-2": recorded}, usage | change)
            )
        for change in (
            {"webSearchRequests": 1},
            {"cacheCreationEphemeral5mInputTokens": 0},
        ):
            self.assertIsNone(
                model_usage_list_cost({"claude-fable-5-2": recorded | change}, usage)
            )
        self.assertIsNone(model_usage_list_cost({"claude-haiku-5-5": recorded}, usage))

    def test_verifier_failure_retains_generation_but_agent_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            _, result, _ = self.fixture(trial)
            result["exception_info"] = {"exception_type": "RewardFileNotFoundError"}
            (trial / "result.json").write_text(json.dumps(result))
            run, _, _ = build_trial(trial)
            self.assertEqual(
                run["usage"]["raw"]["harborVerifierFailure"], "RewardFileNotFoundError"
            )
            result["exception_info"]["exception_type"] = "AgentTimeoutError"
            (trial / "result.json").write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, "unsuccessful"):
                build_trial(trial)


if __name__ == "__main__":
    unittest.main()
