# Vegan ramen

Create an interactive, steaming bowl of vegan ramen in a single, dependency-free `/app/index.html`, with the artwork drawn in code. See `instruction.md` for the exact prompt. The agent has up to three hours, and headless Chromium is available for checking the page.

The verifier uses [Reward Kit](https://pypi.org/project/harbor-rewardkit/) and writes one reward: `reward` is 1.0 when all three checks pass and 0.0 otherwise. Each check is also reported as a test in `/logs/verifier/ctrf.json`.

| Check | Passes when |
| --- | --- |
| `well_formed` | UTF-8 HTML with doctype, `<html>`, `<head>`, `<body>`, and closed `<script>`/`<style>` |
| `standalone` | No external or relative resources, imports, or import maps |
| `self_drawn` | No embedded raster images |

`solution/solve.sh` writes a reference bowl that passes every check.
