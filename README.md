# Ramen Bench

Every model gets the same prompt: create a polished, interactive bowl of vegan ramen in one dependency-free HTML file. Browse the results at <https://stbenjam.github.io/ramen-bench/>.

## Generate new ramens

```sh
harbor run -d stbenjam/ramen-bench -a claude-code -m anthropic/claude-fable-5-2 \
  --ak reasoning_effort=high
```

The [`stbenjam/ramen-bench`](harbor/) dataset's verifier checks that each page is well-formed, standalone, and drawn with code, and awards reward 1.0 or 0.0. For Claude Code on a subscription, set `CLAUDE_CODE_OAUTH_TOKEN` to a token from `claude setup-token`. After editing the task in `harbor/ramen/`, run `harbor sync harbor` before publishing.

## Import a run

```sh
python3 scripts/import_claude_code.py --harbor-job .harbor/jobs/<job>
python3 scripts/censor_transcripts.py --write
python3 scripts/static_checks.py --write
python3 scripts/validate_registry.py
```

Each run lives at `<vendor>/<model>/<variation>/` with the model's unmodified `index.html`, a `run.json` manifest, and a public `transcript.json`. Other harnesses have their own `scripts/import_*.py`; install their dependencies from `requirements-backfill.txt`.

## Run the site locally

```sh
python3 scripts/serve.py
```

Then open <http://localhost:8000>. Pushes to `main` deploy to GitHub Pages. Community ratings are served by the Cloudflare Worker in `api/`; see `api/wrangler.jsonc.example`.
