"""Static checks for the ramen artifact: well-formed, standalone, code-drawn HTML."""

from __future__ import annotations

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


CHECKS = {
    "well_formed": structure_violations,
    "standalone": standalone_violations,
    "self_drawn": procedural_violations,
}


def check(artifact: Path) -> dict[str, list[str]]:
    """Return each check's violations; an unreadable artifact fails every check."""
    if not artifact.is_file() or not artifact.stat().st_size:
        problem = "Missing or empty artifact"
    else:
        try:
            source = artifact.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            problem = "Artifact is not UTF-8 text"
        else:
            return {name: run(source) for name, run in CHECKS.items()}
    return {name: [problem] for name in CHECKS}
