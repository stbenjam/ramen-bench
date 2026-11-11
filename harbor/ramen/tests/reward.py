"""Reward Kit criteria: the bowl passes only when every static check passes."""

from pathlib import Path

from check import check
from rewardkit import criterion

ARTIFACT = "index.html"


def outcome(workspace: Path, name: str) -> dict:
    violations = check(workspace / ARTIFACT)[name]
    return {"score": float(not violations), "reasoning": "; ".join(violations)}


@criterion(
    description="UTF-8 HTML with a doctype, <html>, <head>, <body>, and closed <script> and <style>"
)
def well_formed(workspace: Path) -> dict:
    return outcome(workspace, "well_formed")


@criterion(
    description="No external or relative resources, module imports, or import maps"
)
def standalone(workspace: Path) -> dict:
    return outcome(workspace, "standalone")


@criterion(description="No embedded raster images; the artwork is drawn with code")
def self_drawn(workspace: Path) -> dict:
    return outcome(workspace, "self_drawn")
