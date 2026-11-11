# Ramen Bench contributor instructions

## Generate rollouts for a new model

- Run the published `stbenjam/ramen-bench` dataset on Harbor Hub with `harbor run --launch -d stbenjam/ramen-bench`. Validate each launch with `--dry-run` first.
- Launch one job per effort, setting the effort explicitly. Name every job `<model>-<effort>` with the run's slugs, for example `--job-name fable-5.2-xhigh`. Never leave the default timestamp name.
- Grant only the credential the harness needs with `--stored-secret`. For Claude Code, grant `CLAUDE_CODE_OAUTH_TOKEN` alone; an injected `ANTHROPIC_API_KEY` takes precedence over it.
- Pin the harness version with `--ak version=<version>` and keep it the same across a model's efforts.
- Download finished jobs with `harbor hub job download <job-id> -o .harbor/jobs`, then import them as described below.

## Onboard benchmark runs from recorded sessions

- Treat each model's `index.html` as an immutable benchmark artifact. Verify it against the harness's final recorded write; do not clean up, reformat, or otherwise edit the model output.
- Generate `run.json` and `transcript.json` with the repository importer for that harness. Do not write or fill transcript events, token counts, timing, costs, or provenance by hand.
- Use the harness entry points in `scripts/`: `import_claude_code.py`, `import_codex.py`, `import_antigravity.py`, or `import_muse.py`. Extend the appropriate importer when adding another run so the result is reproducible.
- Prefer provider-recorded costs. Otherwise calculate costs with the pinned LiteLLM catalog only when the recorded token categories are sufficient. Keep cost unknown when calculating it would require guessing.
- Add the run manifest to `runs/registry.json` under Vendor → Model → Effort. Order models newest to oldest and efforts highest to lowest: Ultra, Max, XHigh, High, Medium, Low.

## Censor every public transcript with the shared tool

- Run `python3 scripts/censor_transcripts.py --write` after importing or changing public transcript data. Never rely on one-off manual redaction.
- Run `python3 scripts/censor_transcripts.py` again in read-only mode and require zero files needing changes before publishing.
- Preserve ordinary user and assistant messages, including plain-text reasoning that the model intentionally exposed. Preserve readable source code and tool activity.
- Exclude structured hidden reasoning, system and developer prompts, encrypted or otherwise opaque payloads, private agent-mail activity, credentials, secret-like values, signed asset URLs, personal paths, usernames, email addresses, and private or LAN IP addresses.
- Replace large embedded images, base64, binary, and opaque encrypted strings with the shared censor's factual encoding-and-size marker. Do not publish undecodable payload chunks.
- Never fabricate, summarize, or reconstruct missing transcript content. A factual omission marker is allowed; invented model text is not.

## Validate before committing

- Run `python3 scripts/validate_registry.py`. It must validate every registered manifest, artifact, transcript schema, result statistic, and censor state.
- Run the relevant importer source check and confirm regenerated output is deterministic for the run being added.
- Run `python3 -m unittest scripts/test_censor_transcripts.py`, Python compilation and Ruff for changed importers, the API tests when API code changes, and the LeakTK pre-commit scan.
- Keep unrelated working-tree changes out of the commit.
