# Ramen Bench in Harbor

This directory is the `stbenjam/ramen-bench` Harbor dataset. `dataset.toml` lists its one task, `stbenjam/ramen` in `ramen/`, pinned by content digest. Agents write `/app/index.html`, which Harbor records as an artifact. The agent may run for up to three hours.

Pass the dataset directory to Harbor with `-p harbor`. After editing any task file, run `harbor sync harbor` to update the pinned digest. `ramen/solution/solve.sh` writes a small reference bowl. `harbor run -p harbor -a oracle` runs it through the real verifier and should earn reward 1.0.

## Static checks

The verifier runs `tests/check.py` in a separate container, using only the Python standard library. It awards reward 1.0 when the artifact passes all three checks and 0.0 otherwise:

| Check | Requirement |
| --- | --- |
| `wellFormed` | UTF-8 text with `<!doctype html>`, `<html>`, `<head>` and `<body>`, and no unclosed `<script>` or `<style>` |
| `standalone` | No external or relative assets, CSS imports, JavaScript module imports, import maps, `<base>` or meta refresh; inline SVG, fragment references and data/blob URLs are allowed |
| `codeDrawn` | No embedded raster images (`data:image/png`, JPEG, WebP, GIF and similar) |

A missing or empty artifact earns 0.0. Source checks cannot catch every obfuscated encoding or prove which tools an agent used.

`scripts/static_checks.py --write` runs the same checks over every registered bowl and writes `checks.json`, which the viewer shows as each run's reward. `scripts/validate_registry.py` fails when `checks.json` is stale.

## Setup

Use a separate Python environment from the historical importers: their pinned pricing catalog has incompatible dependencies with current Harbor.

```sh
uv venv .harbor/venv
uv pip install --python .harbor/venv/bin/python -r requirements-harbor.txt
```

## Generate new ramens

```sh
.harbor/venv/bin/harbor run \
  -p harbor -a codex -m openai/gpt-6-luna \
  --ak reasoning_effort=high \
  --jobs-dir "$PWD/.harbor/jobs"
```

The selected coding agent also needs its own credentials/configuration. The task instruction follows `PROMPT.md`, makes the output path absolute, and explicitly prohibits embedded raster artwork for v3. Harbor writes each trial's `verifier/reward.json` and `verifier/check.json` (the individual checks and any violations). Generated trials remain local until deliberately imported/published; the existing harness importers still govern public transcripts and accounting.

For Codex subscription authentication, use Harbor's native agent environment
`CODEX_AUTH_JSON_PATH` pointing to your local `auth.json`, for example
`/home/your-user/.codex2/auth.json`. Harbor uploads the credential into the
ephemeral agent environment; never bake it into an image or publish it. Use the
agent's `config` keyword argument to set `model_reasoning_effort`, including
`ultra` when your installed Codex client supports it. A custom image containing
Codex must include both `codex` and its companion `codex-code-mode-host` binary.

Import completed native Codex trials with the Harbor environment:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/venv/bin/python scripts/import_codex.py \
  --harbor-job .harbor/jobs/<job-name> --dry-run
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/venv/bin/python scripts/import_codex.py \
  --harbor-job .harbor/jobs/<job-name>
python3 scripts/censor_transcripts.py
python3 scripts/static_checks.py --write
python3 scripts/validate_registry.py
```

The importer checks the main recorded session, model, effort, collected artifact,
and exact final file writes. It copies the HTML unchanged and preserves native
Harbor tokens, cost, and generation duration. Harbor's own LiteLLM cost estimates
are marked estimated; unknown costs remain unknown. Repeated imports
are deterministic. Retain the private native job directory for later source
checks; `--run openai/<model>/<effort> --dry-run` can verify an imported run again.

Codex runs that spawn review subagents can expose a Harbor export bug: Harbor
selects the newest rollout rather than the main thread. The importer identifies
the main thread from Codex's recorded `thread.started` event and verifies the bowl
against that thread's final writes. When the exported trajectory belongs to a
descendant, it validates and retains Harbor's accounting separately, sums the
recorded per-session token totals once each, and leaves missing cost unknown.
The manifest records this accounting distinction; the public transcript uses
the main thread and excludes private agent communication.

If the job stops after generation but before Harbor finalizes
the trial's `result.json`, add `--recover-completed`. Recovery requires a recorded
Codex task completion, a matching collected artifact, and the native ATIF
trajectory. It never creates a trial
result or an AgentContext. Recovered manifests explicitly record that the trial
result is missing, retain the trajectory's native accounting, and use the recorded
Codex session start and completion for generation timing. Incomplete generations
cannot be recovered this way.

### Claude Code subscription authentication

Harbor's Claude Code agent reads a subscription token from
`CLAUDE_CODE_OAUTH_TOKEN` in the host process. Create a long-lived token with
`claude setup-token`; the short-lived access token in `~/.claude/.credentials.json`
can expire during a three-hour trial. Keep the token out of the command line and
job configuration:

```sh
CLAUDE_CODE_OAUTH_TOKEN="$(cat /path/to/private/claude-token)" \
  .harbor/venv/bin/harbor run \
  -p harbor -a claude-code -m anthropic/claude-fable-5-2 \
  --ak reasoning_effort=max --ak version=2.1.319 \
  --jobs-dir "$PWD/.harbor/jobs"
```

Bind-mounting `.credentials.json` into `/logs/agent/sessions` does not work with
rootful Docker: the mount leaves that directory owned by root, and Claude Code
cannot create its configuration there.

Haiku 5.5 and Fable 5.2 support `low`, `medium`, `high`, `xhigh`, and `max`. Set
the effort explicitly for each trial. Credentials and native jobs remain private.

Import completed trials through the Claude entry point:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_claude_code.py \
  --harbor-job .harbor/jobs/<job-name> --dry-run
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_claude_code.py \
  --harbor-job .harbor/jobs/<job-name>
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_claude_code.py \
  --harbor-job .harbor/jobs/<job-name> --check-sources
```

Use the pinned historical importer dependencies in `requirements-backfill.txt`
for `.harbor/import-venv`, separately from Harbor's environment. The importer
requires successful native completion, checks the model and recorded effort,
matches the exact task instruction, and compares every HTML byte to recorded
Write and Edit operations. When the session edited `index.html` from the shell
(`sed`, scripts, or concatenated parts), those edits cannot be replayed safely;
the importer then uses Harbor's collected `/app/index.html` and records that
basis in `run.json`. Claude Code may not know a new model's price and records
`costBasis: "unknown"`; that cost stays unknown. It checks native main-session tokens against Harbor accounting
and retains the CLI's auxiliary accounting separately. Unknown or unverified
costs remain unknown. Source checks regenerate both public JSON documents and
require them to match the censored import. Retain the native job for these checks.

### Antigravity CLI and Gemini 4 Argon

Use native Harbor trials for every Argon effort, including Low. The provider's
`agy models` catalog lists `gemini-4-argon-low`, `gemini-4-argon-medium`, and
`gemini-4-argon-high`. Select the exact catalog model and its matching `--effort`.
The repository adapter accepts Medium for Argon, pins an existing local `agy`
executable, and copies the existing consumer OAuth login into the ephemeral
container with private permissions. It retains Harbor's native run command,
session collection, and accounting. It does not select an
API-key billing path or change the host login.

Run one effort per job, with one concurrent trial and no retries. Wait for its
completion before starting the next effort, and stop on subscription exhaustion:

```sh
PYTHONPATH=. harbor run --yes --path harbor --n-concurrent 1 --max-retries 0 \
  --agent scripts.harbor_agy:SubscriptionAgy \
  --model google/gemini-4-argon-low --ak reasoning_effort=low \
  --ak binary_path=/path/to/pinned/agy \
  --ak auth_path=/path/to/antigravity-oauth-token \
  --ae AGY_CLI_DISABLE_AUTO_UPDATE=true \
  --job-name argon-low --jobs-dir .harbor/jobs
```

Disable auto-updates in the agent environment to keep the uploaded version
pinned. In JSON job configuration this is
`agents[].env.AGY_CLI_DISABLE_AUTO_UPDATE = "true"`.

Import and source-check only native Harbor results:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_antigravity.py \
  --harbor-job .harbor/jobs/argon-low
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_antigravity.py \
  --harbor-job .harbor/jobs/argon-low --check-sources
```

Repeat `--harbor-job` to import the separately completed Medium and High jobs.
The importer requires the exact prompt, native model identity and effort,
successful native generation, and unchanged recorded final writes. Tokens come
from native stream usage, checked against individual steps. Costs remain unknown
without verified pricing. The public transcript excludes structured hidden
reasoning, system/developer prompts, private agent activity, credentials, and
opaque payloads using the shared censor. Direct host runs cannot be imported
through this path.

`scripts/agy_list_prices.py` pins Google's published Standard rates on October
15, 2026: $2/M uncached input, $0.10/M implicit cache reads, and $10/M output
including thinking through November 30; $4/$0.20/$20 from December 1. These are
API-equivalent estimates, not recorded subscription charges. The source is
[Google's pricing page](https://ai.google.dev/gemini-api/docs/pricing#gemini-4-argon).
When stream failures leave unknown usage, retain the priced recorded-token
subtotal as a lower bound and keep the full run cost unknown.

agy 1.3.6 can retain `ERROR` after an internal API retry produces a completed
artifact and final response. The importer accepts that recovery only when Harbor
exited normally, completed file writes follow the recorded API error, exact file
replay succeeds, and the final native response matches the last completed
assistant message. It preserves `ERROR` and the runtime error in public metadata
and transcript. Usage for timed-out requests remains unknown; completed-request
token totals are marked as a lower bound, and the full request count is omitted.

### Muse Code and Muse Wonder

Muse Wonder (`muse-wonder-1.0`) advertises `minimal`, `low`, `medium`, `high`,
`xhigh`, and `max` in Muse Code's provider catalog. Generate a separate trial
for each explicitly requested effort. The repository adapter extends Harbor
0.23.0's Muse effort schema to include Max and uploads an already installed
native executable to pin the harness version. It retains Harbor's native
execution command and session collection.

```sh
PYTHONPATH="$PWD" harbor run \
  -p harbor -a scripts.harbor_muse:PinnedMuseCode \
  -m meta/muse-wonder-1.0 --ak reasoning_effort=max \
  --ak binary_path=/path/to/native/muse-executable \
  --jobs-dir "$PWD/.harbor/jobs"
```

Use the native executable downloaded by the Muse launcher, rather than the
launcher script, and set `META_API_KEY` in the host process environment from
your local Muse authentication. Never place credentials in the image or
publish the private job directory.

Import completed generations through the Muse entry point:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_muse.py \
  --harbor-job .harbor/jobs/<generation-job> --muse-binary /path/to/native/muse-executable \
  --dry-run
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_muse.py \
  --harbor-job .harbor/jobs/<generation-job> --muse-binary /path/to/native/muse-executable
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/import-venv/bin/python scripts/import_muse.py \
  --harbor-job .harbor/jobs/<generation-job> --muse-binary /path/to/native/muse-executable \
  --check-sources
```

Use repeatable `--effort` filters to import completed generations
incrementally. The importer uses Muse's own offline exporter on the retained
sessions; raw exports stay private. It verifies the exact benchmark prompt,
model, requested effort, native completion and final file operations. Public
transcripts contain the recorded main-session user/assistant messages and
tools, with factual markers for native export gaps. Structured reasoning,
system/developer instructions, private inter-session messages and auxiliary
session content are excluded, then the shared censor runs over the result.

Tokens are exact sums of native `model_completed` events, with main and
auxiliary session totals retained separately. Cache hits are removed from
uncached input, and reasoning is separate from output. Generation duration
excludes setup and verification. Wonder costs are estimated
using [Meta's published Standard prices](https://dev.meta.ai/docs/pricing-rate-limits),
pinned on October 12, 2026: $4 per million uncached input tokens, $0.20 for
cached input, and $20 for output. Native output already includes reasoning;
the public output category excludes reasoning, and total tokens and costs
count it once. Estimates include the main session and its recorded auxiliary
requests, retain source URLs and rates, and are marked `estimated: true`.
They are API-equivalent list prices, not recorded subscription/API charges.
Unknown model rates, missing token categories or unaccounted search/image
charges leave cost unknown. No price is inferred from another model.
The historical Spark export workflow remains available through the same
Muse entry point.

### Pi and OpenRouter

Harbor's native Pi agent can generate bowls using an `OPENROUTER_API_KEY` in the
ignored local `.harbor/openrouter.env` file:

```sh
.harbor/venv/bin/harbor run \
  -p harbor -a pi -m openrouter/mistralai/mistral-large-4-0 \
  --ak version=1.0.4 --env-file .harbor/openrouter.env \
  --jobs-dir "$PWD/.harbor/jobs"
```

Mistral Large 4's [native API supports reasoning](https://docs.mistral.ai/studio/conversations/reasoning)
at `none` and `high`. OpenRouter's endpoint advertised neither reasoning nor
effort controls when added on October 6, 2026; a strict `high` request with
`provider.require_parameters=true` returned HTTP 404 because no endpoint could
handle those parameters. Direct requests without strict routing also returned
no separate thinking content and zero reported reasoning tokens: both `high` and `none`,
the `reasoning_effort="high"` shorthand, explicit
`reasoning={"effort":"high","enabled":true,"exclude":false}`, and streaming
were checked. Accepted requests therefore do not establish that effort controls
are honored. On a matched prompt, explicit `high`, `none`, and default requests
returned the same step-by-step explanation in ordinary answer text; that text
does not establish distinct reasoning modes. OpenRouter's [routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection#requiring-providers-to-support-all-parameters)
explains that unsupported parameters can be ignored without strict routing.
Verify returned reasoning before adding a `High` run when gateway support changes.
The recorded variation is therefore `Default`, with no
requested effort override. It must not be relabeled `None` or `High`. Pi's internal
thinking setting is recorded separately and does not establish provider support.

Import the completed native job with the Pi entry point:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/venv/bin/python scripts/import_pi.py \
  --harbor-job .harbor/jobs/<job-name> --dry-run
LITELLM_LOCAL_MODEL_COST_MAP=True .harbor/venv/bin/python scripts/import_pi.py \
  --harbor-job .harbor/jobs/<job-name> --refresh-provider-costs \
  --env-file .harbor/openrouter.env
python3 scripts/censor_transcripts.py
python3 scripts/static_checks.py --write
python3 scripts/validate_registry.py
```

The Pi importer replays recorded writes and edits, copies the HTML unchanged,
and validates session tokens against Harbor's native accounting and stdout.
Public transcripts preserve user/assistant text and tools while excluding system
messages and structured hidden reasoning. Original sessions and provider records
remain private in the native trial directory; retain them for source checks.
If the file write succeeds but Pi's final follow-up API requests fail, a finalized
Harbor trial can still supply a verifiable bowl. The importer requires the
successful recorded write and exact artifact match, explicitly records that API
failure, and preserves the original errors rather than inventing a final reply.

Pi's bundled catalog initially did not recognize this new model, so its fallback
pricing estimate is unsuitable for the chart. `--refresh-provider-costs` obtains
OpenRouter's original generation records for each recorded response ID. Cost is
the sum of their provider-recorded `total_cost` fields, with session and model
identity checked; incomplete charge records leave cost unknown. The native Pi
estimate is retained separately. Further imports use those saved records offline
and produce deterministic output, without implementing our own pricing logic.
