"""Windows-compatibility invariants (lessons carried from coop-data-doc).

- CRLF source must yield the same findings/line numbers as LF.
- The tool's own console chrome must be ASCII (a legacy Windows console on
  cp1252/cp437 raises UnicodeEncodeError on box/geometric glyphs).
- JSON output must be ASCII (ensure_ascii) so it is safe on any console.
"""

from coop_sql_review.engine import Result
from coop_sql_review.finding import Finding
from coop_sql_review.parser import parse_sql
from coop_sql_review.report import console_lines, json_text
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_no_select_star import RULE


def test_crlf_line_numbers_match_lf():
    body = "-- header\nCREATE VIEW gold.v AS\nSELECT * FROM t;\n"
    lf = parse_sql("a.sql", body)
    crlf = parse_sql("a.sql", body.replace("\n", "\r\n"))
    lines_lf = [f.line for f in RULE.check(RuleContext(RULE, lf))]
    lines_crlf = [f.line for f in RULE.check(RuleContext(RULE, crlf))]
    assert lines_lf == lines_crlf == [3]
    assert "\r" not in crlf.text  # carriage returns normalized away


def test_console_chrome_is_cp1252_safe():
    # No findings -> only the tool's own chrome, which must survive a legacy code page.
    text = "\n".join(console_lines(Result(files_checked=1)))
    text.encode("cp1252")  # raises if a non-cp1252 glyph slipped into the chrome
    assert text.isascii()


def test_json_output_is_ascii():
    result = Result(
        findings=[Finding("R", "warning", "f.sql", 1, "o", "message with § and — chars", "§9")],
        files_checked=1,
    )
    out = json_text(result, version="0.1.0", standards={"path": "p", "sha256": "s"})
    assert out.isascii()  # ensure_ascii escapes non-ASCII -> safe on any console
    out.encode("cp1252")
