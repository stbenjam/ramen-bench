#!/bin/bash
# Reference bowl: one standalone file, drawn entirely with canvas code.
set -euo pipefail
cat > /app/index.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vegan Ramen</title>
<style>
  html, body { margin: 0; height: 100%; background: #1d1410; }
  canvas { display: block; width: 100%; height: 100%; }
</style>
</head>
<body>
<canvas id="bowl" aria-label="A steaming bowl of vegan ramen"></canvas>
<script>
const canvas = document.getElementById("bowl");
const ctx = canvas.getContext("2d");
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

function draw(time) {
  const w = canvas.width = innerWidth * devicePixelRatio;
  const h = canvas.height = innerHeight * devicePixelRatio;
  const r = Math.min(w, h) * 0.32, cx = w / 2, cy = h * 0.56;
  ctx.fillStyle = "#1d1410"; ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#e9e2d6";
  ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.08, r * 0.42, 0, 0, Math.PI); ctx.lineTo(cx - r * 1.08, cy); ctx.fill();
  ctx.fillStyle = "#c98a3d";
  ctx.beginPath(); ctx.ellipse(cx, cy, r, r * 0.34, 0, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = "#f3d58c"; ctx.lineWidth = r * 0.03;
  for (let i = 0; i < 9; i++) {
    ctx.beginPath();
    for (let x = -0.8; x <= 0.8; x += 0.05) {
      const y = Math.sin(x * 9 + i) * 0.05 + (i - 4) * 0.05;
      ctx.lineTo(cx + x * r, cy + y * r);
    }
    ctx.stroke();
  }
  [["#3f7d3a", -0.45, -0.08], ["#f2efe4", 0.35, 0.05], ["#8a5a2b", 0.05, -0.15]].forEach(([color, x, y]) => {
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.ellipse(cx + x * r, cy + y * r, r * 0.16, r * 0.08, x, 0, Math.PI * 2); ctx.fill();
  });
  ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.lineWidth = r * 0.04; ctx.lineCap = "round";
  for (let i = -1; i <= 1; i++) {
    ctx.beginPath();
    for (let t = 0; t < 1; t += 0.05) {
      ctx.lineTo(cx + i * r * 0.35 + Math.sin(t * 6 + time / 700 + i) * r * 0.08, cy - r * 0.45 - t * r);
    }
    ctx.stroke();
  }
  if (!still) requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
addEventListener("resize", () => still && requestAnimationFrame(draw));
</script>
</body>
</html>
HTML
