"""Static artifact checks shared by the Harbor verifier and checks.json."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harbor/ramen/tests"))
from check import check

PAGE = "<!doctype html><html><head><style>{style}</style></head><body>{body}<script>{script}</script></body></html>"


def run(style="", body="<canvas></canvas>", script="draw()", raw=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "index.html"
        path.write_bytes(
            raw
            if raw is not None
            else PAGE.format(style=style, body=body, script=script).encode()
        )
        return check(path)


class StaticCheckTests(unittest.TestCase):
    def test_standalone_code_drawn_page_passes(self):
        result = run(
            body='<svg><use href="#bowl"/></svg><img src="data:image/svg+xml,<svg/>">'
        )
        self.assertEqual(result, {name: [] for name in result})

    def test_each_check_fails_independently(self):
        cases = {
            "well_formed": run(raw=b"<html><body>ramen</body></html>"),
            "standalone": run(style="body{background:url(https://example.com/a.png)}"),
            "self_drawn": run(body='<img src="data:image/png;base64,AAAA">'),
        }
        for name, result in cases.items():
            failed = [check for check, violations in result.items() if violations]
            self.assertEqual(failed, [name])

    def test_missing_empty_and_binary_artifacts_fail_every_check(self):
        for result in (
            check(Path("/nonexistent/index.html")),
            run(raw=b""),
            run(raw=b"\xff\xfe"),
        ):
            self.assertTrue(all(result.values()))

    def test_comments_and_strings_do_not_count_as_imports(self):
        result = run(script='// import x from "y"\nconst s = "import z from \\"w\\"";')
        self.assertFalse(any(result.values()))


if __name__ == "__main__":
    unittest.main()
