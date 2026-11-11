"""Import native Harbor Claude Code runs from retained, recorded evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from backfill_session_metadata import (
    EFFORT_NAMES,
    ROOT,
    claude_tool_call_count,
    latest_claude_messages,
    normalize_claude_events,
    read_jsonl,
    run_base,
    transcript_base,
    verify_claude_result,
    write_json,
)
from censor_transcripts import censor_value
from censor_transcripts import main as censor_transcripts
from import_harbor_codex import native_artifact, read_json

# Native Claude model IDs accepted from Harbor, mapped to their public model slugs.
MODELS = {
    "claude-fable-5-2": "fable-5.2",
    "claude-haiku-5-5": "haiku-5.5",
}


CLI_DIAGNOSTIC = re.compile(r"\[claude-code:[a-z_]+\] \{.*\}")


def read_stream(path: Path) -> tuple[list[dict], list[str]]:
    """Read stream-json events, keeping the CLI's plain-text diagnostics apart."""
    events, diagnostics = [], []
    for line in path.read_text().splitlines():
        if CLI_DIAGNOSTIC.fullmatch(line):
            diagnostics.append(line)
        elif line.strip():
            events.append(json.loads(line))
    return events, diagnostics


def shell_touches_artifact(rows: list[dict]) -> bool:
    return any(
        block.get("type") == "tool_use"
        and block.get("name") == "Bash"
        and "index.html" in str(block.get("input", {}).get("command", ""))
        for row in rows
        if row.get("type") == "assistant"
        for block in row.get("message", {}).get("content", [])
        if isinstance(block, dict)
    )


def count(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Missing or invalid recorded token count: {label}")
    return value


def native_usage(rows: list[dict], result: dict, completion: dict) -> dict:
    """Use recorded token categories and CLI prices, never fallback estimates."""
    messages = list(latest_claude_messages(rows).values())
    categories = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cachedInput": "cache_read_input_tokens",
        "cacheCreationInput": "cache_creation_input_tokens",
    }
    tokens = {
        name: sum(
            count(row["message"].get("usage", {}).get(key), key) for row in messages
        )
        for name, key in categories.items()
    }
    details = [
        row["message"]["usage"].get("output_tokens_details", {}) for row in messages
    ]
    if all("thinking_tokens" in detail for detail in details):
        thinking = [
            count(detail["thinking_tokens"], "thinking_tokens") for detail in details
        ]
        if any(
            value > row["message"]["usage"]["output_tokens"]
            for value, row in zip(thinking, messages, strict=True)
        ):
            raise ValueError("Recorded thinking tokens exceed output tokens")
        tokens["reasoning"] = sum(thinking)
    # Native Anthropic input excludes both cache categories. Harbor prompt includes them.
    context = result["agent_result"]
    prompt = tokens["input"] + tokens["cachedInput"] + tokens["cacheCreationInput"]
    for key, expected in (
        ("n_input_tokens", prompt),
        ("n_cache_tokens", tokens["cachedInput"]),
        ("n_output_tokens", tokens["output"]),
    ):
        if count(context.get(key), key) != expected:
            raise ValueError(f"Claude session usage disagrees with Harbor: {key}")
    # The CLI result can include auxiliary requests outside the main session.
    # Keep its accounting separately rather than treating it as main-session tokens.
    tokens["total"] = prompt + tokens["output"]
    price = completion.get("total_cost_usd")
    cost = None
    if price is not None:
        if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
            raise ValueError("Invalid Claude Code recorded cost")
        if context.get("cost_usd") != price:
            raise ValueError("Claude Code cost disagrees with Harbor")
        model_usage = completion.get("modelUsage", {})
        known = (
            not completion.get("hasUnknownModelCost", False)
            and bool(model_usage)
            and all(
                type(item.get("costUSD")) in (int, float)
                and math.isfinite(item["costUSD"])
                and item["costUSD"] >= 0
                for item in model_usage.values()
            )
            and math.isclose(
                sum(item["costUSD"] for item in model_usage.values()),
                price,
                abs_tol=1e-9,
            )
            # A model the CLI cannot price is recorded with costBasis "unknown".
            and all(item.get("costBasis") != "unknown" for item in model_usage.values())
            and (price > 0 or tokens["total"] == 0)
        )
        if known:
            cost = {
                "currency": "USD",
                "total": price,
                "estimated": any(
                    item.get("costBasis") == "list" for item in model_usage.values()
                ),
            }
    return {
        "tokens": tokens,
        "cost": cost,
        "toolCalls": claude_tool_call_count(rows),
        "providerReported": True,
        "raw": {
            "harborAgentContext": context,
            "claudeCodeResult": {
                key: completion[key]
                for key in (
                    "usage",
                    "modelUsage",
                    "total_cost_usd",
                    "duration_ms",
                    "duration_api_ms",
                    "num_turns",
                    "hasUnknownModelCost",
                )
                if key in completion
            },
            "inputExcludesCachedInputAndCacheCreation": True,
            "costIncludesRecordedAuxiliaryRequests": True,
        },
    }


def build_trial(trial: Path) -> tuple[dict, dict, Path]:
    result = read_json(trial / "result.json")
    failure = result.get("exception_info")
    config = read_json(trial / "config.json")["agent"]
    effort = config.get("kwargs", {}).get("reasoning_effort")
    model = config.get("model_name", "").removeprefix("anthropic/")
    if (
        (
            failure
            and failure.get("exception_type")
            not in ("RewardFileNotFoundError", "VerifierTimeoutError")
        )
        or not result.get("agent_result")
        or config.get("name") != "claude-code"
        or model not in MODELS
        or effort not in ("low", "medium", "high", "xhigh", "max")
    ):
        raise ValueError("Unsupported or unsuccessful Harbor Claude trial")
    stream, diagnostics = read_stream(trial / "agent/claude-code.txt")
    initial = [
        event
        for event in stream
        if event.get("type") == "system" and event.get("subtype") == "init"
    ]
    completed = [event for event in stream if event.get("type") == "result"]
    if len(initial) != 1 or len(completed) != 1:
        raise ValueError(
            "Expected exactly one native Claude initialization and completion"
        )
    init, completion = initial[0], completed[0]
    if (
        init.get("model") != model
        or completion.get("is_error") is not False
        or completion.get("subtype") != "success"
        or completion.get("session_id") != init.get("session_id")
    ):
        raise ValueError("Claude Code did not complete the requested model session")
    source = trial / "agent/sessions/projects/-app" / f"{init['session_id']}.jsonl"
    rows = read_jsonl(source)
    messages = list(latest_claude_messages(rows).values())
    version = result["agent_info"]["version"]
    if (
        not messages
        or result["agent_info"]["name"] != "claude-code"
        or init.get("claude_code_version") != version
        or config.get("kwargs", {}).get("version", version) != version
        or any(row["message"].get("model") != model for row in messages)
        or any(row.get("version", version) != version for row in rows)
        # Shell `cd` moves the recorded cwd; the session must stay inside /app.
        or any(
            row.get("cwd", "/app") != "/app"
            and not row["cwd"].startswith("/app/")
            for row in rows
        )
    ):
        raise ValueError(
            "Recorded session model, version, or working directory mismatch"
        )
    # Require the exact task instruction, including the v3 procedural-art rule.
    instruction = (ROOT / "harbor/ramen/instruction.md").read_text()
    if not any(
        row.get("type") == "user"
        and row.get("message", {}).get("content") == instruction
        for row in rows
    ):
        raise ValueError("Session does not contain the exact Harbor ramen instruction")
    artifact = native_artifact(trial)
    run_id = f"anthropic/{MODELS[model]}/{effort}"
    try:
        verification = verify_claude_result(rows, run_id, artifact)
        provenance = "HTML matches the final recorded file-operation replay."
    except ValueError as error:
        # Shell edits (sed, scripts, concatenated parts) cannot be replayed safely.
        # Harbor's own collection of /app/index.html is then the recorded final write.
        if not shell_touches_artifact(rows):
            raise
        verification = f"Harbor artifact collection; transcript replay unsupported ({error})"
        provenance = "HTML is Harbor's collected /app/index.html; the session's shell edits are not replayed."
    events, omitted = normalize_claude_events(rows, preserve_task=True)
    execution = result["agent_execution"]
    started = datetime.fromisoformat(execution["started_at"])
    finished = datetime.fromisoformat(execution["finished_at"])
    if started.tzinfo is None or finished.tzinfo is None or finished < started:
        raise ValueError("Invalid Harbor generation timestamps")
    usage = native_usage(rows, result, completion)
    usage["raw"].update(
        harborTrial=trial.name,
        harborTaskChecksum=result["task_checksum"],
        artifactVerification=verification,
    )
    if diagnostics:
        usage["raw"]["claudeCodeDiagnostics"] = diagnostics
    if failure:
        usage["raw"]["harborVerifierFailure"] = failure["exception_type"]
    run = run_base(
        run_id,
        model,
        {
            "name": "Claude Code",
            "version": version,
            "runtime": "Harbor",
            "invocation": f"Native Harbor claude-code agent; {model} @ {effort}; mounted Claude subscription authentication",
        },
        {
            "startedAt": execution["started_at"],
            "completedAt": execution["finished_at"],
            "wallDurationMs": round((finished - started).total_seconds() * 1000),
        },
        usage,
        f"Generated by native Harbor. {provenance} Tokens retain exact main-session categories; input excludes cache reads and writes, and reasoning is included in output. CLI cost includes recorded auxiliary requests; list-price costs are marked estimated and unavailable or unverified prices remain unknown. Generation duration excludes setup and verification. Public transcripts exclude hidden reasoning and private data.",
        "Claude Code final stream-json result total_cost_usd and modelUsage; unknown prices are not inferred",
        artifact,
    )
    transcript = transcript_base(
        run_id, init["session_id"], "harbor-claude-code-jsonl", source, events, omitted
    )
    return run, transcript, artifact


def build_registered_trial(run_id: str) -> tuple[dict, dict, Path]:
    recorded = read_json(ROOT / run_id / "run.json")
    raw = recorded["usage"]["raw"]
    name = raw["harborTrial"]
    if Path(name).name != name:
        raise ValueError("Invalid retained native trial identifier")
    matches = list((ROOT / ".harbor/jobs").glob(f"*/{name}"))
    if len(matches) != 1:
        raise ValueError("Expected one retained native Claude generation")
    run, transcript, artifact = build_trial(matches[0])
    if (
        run["id"] != run_id
        or artifact.read_bytes() != (ROOT / run_id / "index.html").read_bytes()
    ):
        raise ValueError("Registered bowl differs from its native Claude source")
    return run, transcript, artifact


def register(runs: list[dict]) -> None:
    path = ROOT / "registry.json"
    registry = read_json(path)
    fresh = sorted(
        {f"{run['id']}/run.json" for run in runs},
        key=lambda name: -list(EFFORT_NAMES).index(name.split("/")[2]),
    )
    models = {name.rsplit("/", 2)[0] for name in fresh}
    remaining = [name for name in registry["runs"] if name not in fresh]
    # Keep an existing model in place; a new model is the newest Anthropic entry.
    existing = [
        i
        for i, name in enumerate(registry["runs"])
        if name.rsplit("/", 2)[0] in models
    ]
    if existing:
        insertion = existing[0]
    else:
        insertion = next(
            (i for i, name in enumerate(remaining) if name.startswith("anthropic/")),
            0,
        )
    registry["runs"] = remaining[:insertion] + fresh + remaining[insertion:]
    added = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for model in sorted(models):
        registry.setdefault("modelAddedAt", {}).setdefault(model, added)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-job", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-sources", action="store_true")
    args = parser.parse_args(argv)
    trials = sorted(args.harbor_job.glob("*/result.json"))
    if not trials:
        raise ValueError("No completed native Harbor trials")
    built = [(path.parent, *build_trial(path.parent)) for path in trials]
    ids = [run["id"] for _, run, _, _ in built]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate native Claude effort runs")
    for _, run, transcript, artifact in built:
        target = ROOT / run["id"]
        for name, document in (("run.json", run), ("transcript.json", transcript)):
            write_json(target / name, document, True)
            if args.check_sources and read_json(target / name) != censor_value(
                document
            ):
                raise ValueError(f"{run['id']}: {name} differs from regenerated source")
        if (
            target.joinpath("index.html").exists()
            and target.joinpath("index.html").read_bytes() != artifact.read_bytes()
        ):
            raise ValueError("Refusing to overwrite a different immutable artifact")
        if not args.dry_run and not args.check_sources:
            target.mkdir(parents=True, exist_ok=True)
            (target / "index.html").write_bytes(artifact.read_bytes())
            write_json(target / "run.json", run, False)
            write_json(target / "transcript.json", transcript, False)
    if not args.dry_run and not args.check_sources:
        register([run for _, run, _, _ in built])
        censor_transcripts(["--write", str(ROOT / "anthropic")])
    print(
        f"{'Checked' if args.check_sources or args.dry_run else 'Imported'} {len(built)} native Harbor Claude runs"
    )
    return censor_transcripts([str(ROOT / "anthropic")])
