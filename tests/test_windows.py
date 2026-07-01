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


# --- Encodings Windows tooling actually produces (SSMS "Save with Encoding:
#     Unicode" = UTF-16, PowerShell 5.1 `>` redirection). A UTF-16 file must be
#     linted (BOM-aware), and one we can't decode must yield a diagnostic that
#     names the file — never a silent zero-findings pass. ---


def _check_json(path):
    import json

    from click.testing import CliRunner

    from coop_sql_review.cli import cli

    result = CliRunner().invoke(cli, ["check", str(path), "--format", "json"])
    assert result.exit_code == 0
    return json.loads(result.stdout)


def test_utf16_le_bom_file_is_linted(tmp_path):
    import codecs

    f = tmp_path / "u16le.sql"
    f.write_bytes(codecs.BOM_UTF16_LE + "SELECT * FROM dbo.t;\n".encode("utf-16-le"))
    payload = _check_json(f)
    assert payload["files_checked"] == 1
    assert any(x["rule_id"] == "SQL-NO-SELECT-STAR" for x in payload["findings"])


def test_utf16_be_bom_file_is_linted(tmp_path):
    import codecs

    f = tmp_path / "u16be.sql"
    f.write_bytes(codecs.BOM_UTF16_BE + "SELECT * FROM dbo.t;\n".encode("utf-16-be"))
    payload = _check_json(f)
    assert any(x["rule_id"] == "SQL-NO-SELECT-STAR" for x in payload["findings"])


def test_utf32_le_bom_file_is_linted(tmp_path):
    # The UTF-32-LE BOM starts with the UTF-16-LE BOM bytes — sniffing must
    # check the longer BOM first or the file decodes as NUL-riddled UTF-16.
    import codecs

    f = tmp_path / "u32le.sql"
    f.write_bytes(codecs.BOM_UTF32_LE + "SELECT * FROM dbo.t;\n".encode("utf-32-le"))
    payload = _check_json(f)
    assert any(x["rule_id"] == "SQL-NO-SELECT-STAR" for x in payload["findings"])


def test_utf16_without_bom_yields_diagnostic_not_silence(tmp_path):
    # No BOM to sniff: the NUL-interleaved decode parses into garbage, so the
    # file must be reported as unreadable — not counted as silently clean.
    f = tmp_path / "nobom.sql"
    f.write_bytes("SELECT * FROM dbo.t;\n".encode("utf-16-le"))
    payload = _check_json(f)
    assert payload["findings"] == []
    diags = [d for d in payload["diagnostics"] if d["category"] == "file_unreadable"]
    assert len(diags) == 1
    assert "nobom.sql" in diags[0]["file"]
    assert "UTF-8" in diags[0]["message"]


def test_invalid_utf8_bytes_yield_diagnostic_and_still_lint(tmp_path):
    # A stray cp1252 byte must not silently turn into U+FFFD: the file is still
    # linted (replacement-decoded) but the gap is surfaced as a diagnostic.
    f = tmp_path / "cp1252.sql"
    f.write_bytes(b"-- caf\xe9\nSELECT * FROM dbo.t;\n")
    payload = _check_json(f)
    assert any(x["rule_id"] == "SQL-NO-SELECT-STAR" for x in payload["findings"])
    assert any(
        d["category"] == "file_unreadable" and "cp1252.sql" in d["file"] for d in payload["diagnostics"]
    )
