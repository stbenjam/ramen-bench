# Vegan ramen

Create an interactive, steaming bowl of vegan ramen in a single, dependency-free `/app/index.html`, with the artwork drawn in code. See `instruction.md` for the exact prompt. The agent has up to three hours, and headless Chromium is available for checking the page.

| Key | Passes when |
| --- | --- |
| `reward` | All three checks below pass |
| `selfDrawn` | No embedded raster images |
| `standalone` | No external or relative resources, imports, or import maps |
| `wellFormed` | UTF-8 HTML with doctype, `<html>`, `<head>`, `<body>`, and closed `<script>`/`<style>` |

`solution/solve.sh` writes a reference bowl that passes every check.
