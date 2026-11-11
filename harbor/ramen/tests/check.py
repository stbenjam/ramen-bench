#!/usr/bin/env python3
"""Static checks for the ramen artifact: well-formed, standalone, code-drawn HTML."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path


def procedural_violations(source: str) -> list[str]:
    # Raster artwork is prohibited even when embedded. Code-drawn SVG and canvas
    # sprites remain eligible. This source check cannot prove all tool provenance.
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    if re.search(
        r"data:image/(?:png|jpe?g|webp|gif|avif|bmp|tiff?|x-icon)(?:;|,)",
        source,
        re.IGNORECASE,
    ):
        return ["Embedded raster artwork; draw the scene with code instead"]
    return []


def inline_reference(value: str) -> bool:
    return not value.strip() or value.strip().lower().startswith(
        ("#", "data:", "blob:")
    )


def css_violations(source: str) -> list[str]:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    result = []
    if re.search(r"@import\b", source, re.IGNORECASE):
        result.append("CSS @import")
    for match in re.finditer(
        r"url\(\s*(['\"]?)(.*?)\1\s*\)", source, re.IGNORECASE | re.DOTALL
    ):
        if not inline_reference(match[2]):
            result.append("CSS external or relative url()")
    return result


def js_violations(source: str) -> list[str]:
    # Preserve string token boundaries, but discard their contents and comments so a
    # comment or a string describing imports cannot disqualify a standalone page.
    tokens = (
        r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`"
    )
    code = re.sub(
        tokens,
        lambda match: " " if match[0].startswith("/") else '""',
        source,
        flags=re.DOTALL,
    )
    result = []
    if re.search(r'\bimport\s*(?:\(|"|[\w*{][^;]*?\bfrom\s*")', code):
        result.append("JavaScript module import")
    if re.search(r'\bexport\s+[^;]*?\bfrom\s*"', code):
        result.append("JavaScript module re-export")
    return result


class Dependencies(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[str] = []
        self.content_tag = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for name, value in attrs:
            if (
                value
                and name
                in {
                    "src",
                    "href",
                    "xlink:href",
                    "poster",
                    "data",
                    "background",
                    "action",
                }
                and not inline_reference(value)
            ):
                self.violations.append(f"<{tag}> non-inline {name}")
            if name == "srcset" and value:
                # Data URLs may contain commas; remove their complete non-space token first.
                candidates = re.sub(r"data:[^\s]+", "", value, flags=re.IGNORECASE)
                if any(
                    not inline_reference(item.strip().split()[0])
                    for item in candidates.split(",")
                    if item.strip() and not re.fullmatch(r"\s*[\d.]+[wx]\s*", item)
                ):
                    self.violations.append(f"<{tag}> non-inline srcset")
            if name == "style" and value:
                self.violations.extend(css_violations(value))
        if tag == "base" or (
            tag == "meta" and values.get("http-equiv", "").lower() == "refresh"
        ):
            self.violations.append(f"<{tag}> changes document navigation")
        if tag == "script" and values.get("type") == "importmap":
            self.violations.append("JavaScript import map")
        if tag in {"script", "style"}:
            self.content_tag = tag

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.content_tag:
            self.content_tag = None

    def handle_data(self, data: str) -> None:
        if self.content_tag == "style":
            self.violations.extend(css_violations(data))
        elif self.content_tag == "script":
            self.violations.extend(js_violations(data))


def standalone_violations(source: str) -> list[str]:
    parser = Dependencies()
    parser.feed(source)
    return sorted(set(parser.violations))


class Structure(HTMLParser):
    """Track the document elements and raw-text blocks a browser needs to run the page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.tags: set[str] = set()
        self.open_raw: str | None = None

    def handle_decl(self, decl: str) -> None:
        self.doctype |= decl.strip().lower() == "doctype html"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        if tag in {"script", "style"}:
            self.open_raw = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == self.open_raw:
            self.open_raw = None


def structure_violations(source: str) -> list[str]:
    parser = Structure()
    parser.feed(source)
    parser.close()
    result = []
    if not parser.doctype:
        result.append("Missing <!doctype html>")
    result.extend(
        f"Missing <{tag}> element"
        for tag in ("html", "head", "body")
        if tag not in parser.tags
    )
    if parser.open_raw:
        result.append(f"Unclosed <{parser.open_raw}>")
    return result


def check(artifact: Path) -> dict:
    if not artifact.is_file() or not artifact.stat().st_size:
        return {"reward": 0, "violations": ["Missing or empty artifact"]}
    try:
        source = artifact.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return {"reward": 0, "violations": ["Artifact is not UTF-8 text"]}
    checks = {
        "wellFormed": structure_violations(source),
        "standalone": standalone_violations(source),
        "codeDrawn": procedural_violations(source),
    }
    violations = [item for items in checks.values() for item in items]
    return {
        "reward": 0 if violations else 1,
        **{name: int(not items) for name, items in checks.items()},
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.artifact)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "check.json").write_text(json.dumps(result, indent=2) + "\n")
    rewards = {key: value for key, value in result.items() if key != "violations"}
    (args.output / "reward.json").write_text(json.dumps(rewards) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
