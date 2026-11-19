#!/usr/bin/env python3
"""Import completed Harbor trials from their ATIF trajectories and collected HTML."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backfill_session_metadata import (
    DISPLAY_NAMES,
    EFFORT_NAMES,
    PRIVATE_TOOL_RE,
    ROOT,
    RUNS,
    content_text,
    public_user_text,
    run_base,
    scrub,
    transcript_base,
    write_json,
)
from censor_transcripts import main as censor_transcripts
from list_prices import list_cost

INSTRUCTION = (ROOT / "harbor/ramen/instruction.md").read_text().strip()
# Provider model IDs whose site slug differs from the ID itself.
MODEL_SLUGS = {
    "claude-fable-5-2": "fable-5.2",
    "claude-haiku-5-5": "haiku-5.5",
}
# Harbor provider names that differ from the site vendor slug.
PROVIDER_VENDORS = {"gemini": "google"}
HARNESS_NAMES = {
    "claude-code": "Claude Code",
    "codex": "Codex",
    "antigravity-cli": "Antigravity CLI",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def collected_artifact(trial: Path) -> Path:
    records = read_json(trial / "artifacts/manifest.json")
    matches = [r for r in records if r.get("source") == "/app/index.html"]
    if len(matches) != 1 or matches[0].get("status") != "ok":
        raise ValueError(f"{trial.name}: Harbor did not collect index.html")
    artifact = (trial / matches[0]["destination"]).resolve()
    if not artifact.is_relative_to((trial / "artifacts").resolve()):
        raise ValueError(f"{trial.name}: artifact is outside the trial directory")
    return artifact


# Antigravity wraps the user's prompt and appends harness metadata blocks.
USER_REQUEST = re.compile(r"<USER_REQUEST>\n?(.*?)\n*</USER_REQUEST>", re.DOTALL)


def user_text(message: Any) -> str:
    text = message if isinstance(message, str) else content_text(message)
    match = USER_REQUEST.search(text)
    return match.group(1) if match else text


def transcript_events(steps: list[dict]) -> tuple[list[dict], int]:
    """Public messages and tool activity; system prompts and reasoning are dropped."""
    events: list[dict] = []
    private_calls: set[str] = set()
    for step in steps:
        timestamp = step.get("timestamp")
        stamp = {"timestamp": timestamp} if timestamp else {}
        message = step.get("message")
        text = message if isinstance(message, str) else content_text(message)
        if step["source"] == "user":
            text = public_user_text(user_text(message), preserve_task=True)
            if text:
                events.append(
                    {"type": "message", "role": "user", "content": text, **stamp}
                )
            continue
        if step["source"] != "agent":
            continue
        if text and text.strip():
            events.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": scrub(text),
                    **stamp,
                }
            )
        for call in step.get("tool_calls") or []:
            if PRIVATE_TOOL_RE.search(json.dumps(call)):
                private_calls.add(call["tool_call_id"])
                continue
            events.append(
                {
                    "type": "tool_call",
                    "id": call["tool_call_id"],
                    "tool": call["function_name"],
                    "input": scrub(call.get("arguments")),
                    **stamp,
                }
            )
        for result in (step.get("observation") or {}).get("results") or []:
            call_id = result.get("source_call_id")
            if call_id is None or call_id in private_calls:
                continue
            events.append(
                {
                    "type": "tool_result",
                    "callId": call_id,
                    "output": scrub(result.get("content")),
                    **stamp,
                }
            )
    return events, len(private_calls)


def usage(trajectory: dict, model: str, tool_calls: int) -> tuple[dict, str]:
    """Return usage and its pricing source; list rates apply only when the harness recorded no cost."""
    metrics = trajectory["final_metrics"]
    extra = metrics.get("extra") or {}
    prompt = metrics["total_prompt_tokens"]
    completion = metrics["total_completion_tokens"]
    tokens = {
        "input": prompt,
        "cachedInput": metrics.get("total_cached_tokens") or 0,
        "cacheCreationInput": extra.get("total_cache_creation_input_tokens")
        or extra.get("total_cache_write_input_tokens")
        or 0,
        "reasoning": extra.get("reasoning_output_tokens") or 0,
        "output": completion,
        "total": prompt + completion,
    }
    raw: dict = {"atifFinalMetrics": metrics}
    recorded = metrics.get("total_cost_usd")
    if recorded is not None:
        cost = {"currency": "USD", "total": recorded, "estimated": True}
        source = "Harbor ATIF final_metrics.total_cost_usd"
    elif priced := list_cost(model, trajectory):
        cost, raw["listPriceCalculation"] = priced
        source = f"{priced[1]['source']} (pinned {priced[1]['asOf']})"
    else:
        cost, source = None, "Not recorded by the harness"
    return {
        "tokens": tokens,
        "cost": cost,
        "toolCalls": tool_calls,
        "providerReported": True,
        "raw": raw,
    }, source


def build_trial(trial: Path) -> tuple[dict, dict, Path]:
    result = read_json(trial / "result.json")
    trajectory_path = trial / "agent/trajectory.json"
    trajectory = read_json(trajectory_path)
    steps = trajectory["steps"]
    if not any(
        step["source"] == "user"
        and user_text(step.get("message")).strip() == INSTRUCTION
        for step in steps
    ):
        raise ValueError(
            f"{trial.name}: trajectory is not the main session for the task"
        )

    agent = result["agent_info"]
    model_id = agent["model_info"]["name"]
    provider = agent["model_info"]["provider"]
    # A gateway such as OpenRouter names the model "<vendor>/<model>".
    vendor, model = (
        model_id.split("/", 1)
        if "/" in model_id
        else (PROVIDER_VENDORS.get(provider, provider), model_id)
    )
    effort = result["config"]["agent"]["kwargs"]["reasoning_effort"]
    run_id = f"{vendor}/{MODEL_SLUGS.get(model, model)}/{effort}"
    if run_id.split("/")[1] not in DISPLAY_NAMES or effort not in EFFORT_NAMES:
        raise ValueError(f"{run_id}: add the model or effort display name first")

    artifact = collected_artifact(trial)
    events, omitted = transcript_events(steps)
    execution = result["agent_execution"]
    started = datetime.fromisoformat(execution["started_at"])
    finished = datetime.fromisoformat(execution["finished_at"])
    run_usage, pricing_source = usage(
        trajectory,
        f"{provider}/{model_id}",
        sum(e["type"] == "tool_call" for e in events),
    )
    run_usage["raw"]["harborTrial"] = trial.name
    harness = HARNESS_NAMES.get(agent["name"], agent["name"])
    run = run_base(
        run_id,
        model_id,
        {
            "name": harness,
            "version": agent["version"],
            "runtime": "Harbor",
            "invocation": f"Harbor {agent['name']} agent; {model_id} @ {effort}"
            + (f" via {provider}" if provider != vendor else ""),
        },
        {
            "startedAt": execution["started_at"],
            "completedAt": execution["finished_at"],
            "wallDurationMs": round((finished - started).total_seconds() * 1000),
        },
        run_usage,
        f"Generated by {harness} in Harbor. HTML is Harbor's collected /app/index.html. "
        "Tokens and cost come from Harbor's ATIF trajectory: input includes cache reads "
        "and writes, and output includes reasoning. Cost is the harness's list-price "
        "estimate; when the harness records none, each request is priced at pinned "
        "published list rates, or cost stays unknown. Generation duration "
        "excludes setup and verification. Public transcripts exclude system prompts, "
        "hidden reasoning, and private data.",
        pricing_source,
        artifact,
    )
    transcript = transcript_base(
        run_id,
        trajectory["session_id"],
        "harbor-atif",
        trajectory_path,
        events,
        omitted,
    )
    return run, transcript, artifact


def register(runs: list[dict]) -> None:
    """Keep an existing model's position; put a new model first among its vendor's."""
    path = RUNS / "registry.json"
    registry = read_json(path)
    efforts = list(EFFORT_NAMES)
    for model in dict.fromkeys(r["id"].rsplit("/", 1)[0] for r in runs):
        current = registry["runs"]
        vendor = model.split("/")[0]
        index = next(
            (i for i, p in enumerate(current) if p.startswith(f"{model}/")),
            next(
                (i for i, p in enumerate(current) if p.startswith(f"{vendor}/")),
                len(current),
            ),
        )
        paths = {p for p in current if p.startswith(f"{model}/")}
        paths |= {
            f"{r['id']}/run.json" for r in runs if r["id"].startswith(f"{model}/")
        }
        ordered = sorted(paths, key=lambda p: -efforts.index(p.split("/")[2]))
        remaining = [p for p in current if p not in paths]
        registry["runs"] = remaining[:index] + ordered + remaining[index:]
        registry.setdefault("modelAddedAt", {}).setdefault(
            model, datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path, help="Harbor job directories")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    runs = []
    for trial in sorted(
        t.parent for job in args.jobs for t in job.glob("*/result.json")
    ):
        if read_json(trial / "result.json").get("exception_info"):
            print(f"Skipping unsuccessful trial: {trial}")
            continue
        run, transcript, artifact = build_trial(trial)
        destination = RUNS / run["id"]
        published = destination / "index.html"
        if published.exists() and published.read_bytes() != artifact.read_bytes():
            raise ValueError(
                f"{run['id']}: refusing to replace the published index.html"
            )
        if not args.dry_run:
            destination.mkdir(parents=True, exist_ok=True)
            published.write_bytes(artifact.read_bytes())
        write_json(destination / "run.json", run, args.dry_run)
        write_json(destination / "transcript.json", transcript, args.dry_run)
        runs.append(run)
        print(f"{'Checked' if args.dry_run else 'Imported'} {run['id']}")
    if not runs:
        raise SystemExit("No successful Harbor trials found")
    if not args.dry_run:
        register(runs)
        censor_transcripts(["--write", str(RUNS)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
