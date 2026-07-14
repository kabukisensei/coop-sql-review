"""Parser foundation: batches, line mapping, comments, objects, masking."""

from coop_sql_review.parser import extract_comments, parse_sql
from coop_sql_review.sql_common import mask_noncode, split_batches_with_lines

SQL = """-- header on line 1
CREATE TABLE silver.dim_customer (
    CustomerId  bigint        NOT NULL,
    Amount      money         NOT NULL,
    Descr       nvarchar(50)  NULL,
    CreatedDt   datetime      NOT NULL,
    ModDt       datetime2(3)  NULL
);
GO
INSERT INTO gold.audit VALUES (1), (2);
"""


def test_batches_track_start_line():
    batches = split_batches_with_lines(SQL)
    assert len(batches) == 2
    assert batches[0][1] == 1  # CREATE batch starts at line 1 (the comment)
    assert batches[1][1] == 10  # INSERT batch starts at line 10


def test_objects_and_column_types_with_lines():
    parsed = parse_sql("dim.sql", SQL)
    assert len(parsed.objects) == 1
    obj = parsed.objects[0]
    assert (obj.kind, obj.schema, obj.name) == ("table", "silver", "dim_customer")
    assert obj.layer == "silver"
    cols = {c.name: c for c in obj.columns}
    assert cols["Amount"].base_type == "MONEY"
    assert cols["Descr"].base_type == "NVARCHAR"
    assert cols["CreatedDt"].base_type == "DATETIME"
    assert cols["ModDt"].base_type == "DATETIME2"  # must NOT collapse to DATETIME
    # precise file line numbers come from the column identifier
    assert cols["Amount"].line == 4
    assert cols["Descr"].line == 5
    assert cols["CreatedDt"].line == 6


def test_column_nullability_matches_declaration():
    # Pin the NOT NULL / NULL sense so a future sqlglot bump can't silently
    # re-invert it (the NotNullColumnConstraint.allow_null semantics flipped
    # at sqlglot 26: NOT NULL -> no allow_null key; explicit NULL -> True).
    sql = "CREATE TABLE dbo.t (a INT NOT NULL, b INT NULL, c INT, d INT PRIMARY KEY)\n"
    parsed = parse_sql("nullability.sql", sql)
    cols = {c.name: c for c in parsed.objects[0].columns}
    assert cols["a"].nullable is False  # INT NOT NULL
    assert cols["b"].nullable is True  # INT NULL
    assert cols["c"].nullable is True  # bare INT defaults to nullable
    assert cols["d"].nullable is False  # PRIMARY KEY is implicitly NOT NULL
    assert "PK" in cols["d"].constraints


def test_identity_tag_covers_both_spellings():
    # sqlglot parses seeded `IDENTITY(1,1)` as GeneratedAsIdentity but bare
    # `IDENTITY` (no seed) as AutoIncrement; the parser must tag both so the two
    # spellings can never silently diverge in ColumnDef.constraints (issue #31).
    sql = (
        "CREATE TABLE s.t (bare BIGINT IDENTITY NOT NULL, seeded BIGINT IDENTITY(1,1) NOT NULL, plain INT)\n"
    )
    parsed = parse_sql("identity.sql", sql)
    cols = {c.name: c for c in parsed.objects[0].columns}
    assert "IDENTITY" in cols["bare"].constraints
    assert "IDENTITY" in cols["seeded"].constraints
    assert "IDENTITY" not in cols["plain"].constraints


def test_node_line_offsets_into_second_batch():
    parsed = parse_sql("dim.sql", SQL)
    from sqlglot import exp

    insert_lines = [parsed.node_line(b, n) for b, n in parsed.find_all(exp.Insert)]
    assert insert_lines == [10]


def test_comments_have_line_spans():
    comments = extract_comments("SELECT 1\n/* a\n   b */\n-- tail\n")
    kinds = [(c.kind, c.line_start, c.line_end) for c in comments]
    assert ("block", 2, 3) in kinds
    assert ("line", 4, 4) in kinds


def test_mask_noncode_preserves_offsets_and_hides_noncode():
    s = "SELECT 1 -- nvarchar money\n/* datetime */ FROM t WHERE x = 'money nvarchar'"
    masked = mask_noncode(s)
    assert len(masked) == len(s)
    assert masked.count("\n") == s.count("\n")
    # keywords living only in comments/strings disappear from the mask
    assert "nvarchar" not in masked
    assert "datetime" not in masked
    assert "money" not in masked
    # real code survives at the same positions
    assert masked.startswith("SELECT 1")
    assert "FROM t WHERE x =" in masked


def test_go_inside_comment_does_not_split():
    sql = "SELECT 1\n/* GO\nGO */\nSELECT 2\nGO\nSELECT 3\n"
    batches = split_batches_with_lines(sql)
    # only the real standalone GO (line 5) splits -> two batches
    assert len(batches) == 2


def test_mask_keeps_delimited_identifiers_intact():
    # A `'`, `--` or `/*` inside a bracket-/quote-delimited identifier is part
    # of the name, not the start of a string/comment, and must not blank the
    # rest of the statement.
    s = "SELECT [Customer's Name], COUNT(*) FROM dbo.t WHERE x = 1"
    masked = mask_noncode(s)
    assert len(masked) == len(s)
    assert "FROM dbo.t WHERE x = 1" in masked

    s2 = "SELECT [a--b] AS c FROM t"
    assert "FROM t" in mask_noncode(s2)

    s3 = 'SELECT "weird/*col" FROM t'
    assert "FROM t" in mask_noncode(s3)


def test_go_after_bracketed_apostrophe_still_splits():
    # The apostrophe in `[O'Brien]` must not start a string that masks the GO.
    sql = "CREATE TABLE [O'Brien] (id int)\nGO\nSELECT 1\n"
    assert len(split_batches_with_lines(sql)) == 2


def test_nested_block_comments_fully_masked():
    # T-SQL block comments nest; the mask must pair `/*`/`*/` by depth, not stop
    # at the first `*/`.
    s = "SELECT 1 /* a /* b */ c */ , 2"
    masked = mask_noncode(s)
    assert len(masked) == len(s)
    assert "a" not in masked and "b" not in masked and "c" not in masked
    assert masked.startswith("SELECT 1")
    assert masked.rstrip().endswith(", 2")


def test_nested_block_comment_is_one_comment_with_correct_span():
    comments = extract_comments("A\n/* outer /* inner */ still */\nSELECT 1\n")
    blocks = [c for c in comments if c.kind == "block"]
    assert len(blocks) == 1
    assert (blocks[0].line_start, blocks[0].line_end) == (2, 2)


def test_comment_after_dashed_identifier_is_still_found():
    comments = extract_comments("SELECT [a--b] -- real comment\nFROM t\n")
    lines = [c for c in comments if c.kind == "line"]
    assert len(lines) == 1
    assert "real comment" in lines[0].text


def test_unparseable_text_is_tolerated():
    parsed = parse_sql("weird.sql", "CREATE TABLE t (a int);\nGO\nCURSOR nonsense ((( ;\n")
    assert any(o.name == "t" for o in parsed.objects)  # the good batch still parses


def test_go_with_count_is_a_batch_separator():
    # REGRESSION: T-SQL's repeat form `GO 5` must split batches like a plain GO
    # — otherwise every statement after it is silently swallowed (sqlglot drops
    # them from the merged batch with no diagnostic).
    sql = "INSERT INTO dbo.t VALUES (1)\nGO 5\nSELECT * FROM dbo.x\n"
    batches = split_batches_with_lines(sql)
    assert len(batches) == 2
    batch_text, start_line = batches[1]
    assert batch_text.strip() == "SELECT * FROM dbo.x"
    assert start_line == 3


def test_go_count_variants_split():
    # Whitespace/casing/semicolon variants of `GO n` all separate batches.
    for go in ("GO 2", "go 10", "  GO   3  ", "GO 2;"):
        sql = f"SELECT 1\n{go}\nSELECT 2\n"
        assert len(split_batches_with_lines(sql)) == 2, go


def test_go_with_trailing_junk_does_not_split():
    # `GO` followed by anything that is not a count is NOT a separator line.
    sql = "SELECT 1\nGO TO work\nSELECT 2\n"
    assert len(split_batches_with_lines(sql)) == 1


def test_procedure_lifted_as_object():
    # CREATE PROCEDURE parses to Create(this=StoredProcedure(this=Table)); the parser
    # must lift it as a SqlObject(kind="proc") so file-level rules/reports can name it
    # (issue #2 — the estate is almost all procs).
    sql = "CREATE OR ALTER PROCEDURE silver.load_dim_customer AS BEGIN SELECT 1; END"
    parsed = parse_sql("proc.sql", sql)
    procs = [o for o in parsed.objects if o.kind == "proc"]
    assert len(procs) == 1
    assert (procs[0].kind, procs[0].schema, procs[0].name) == ("proc", "silver", "load_dim_customer")


def test_procedure_bracketed_name_lifted():
    parsed = parse_sql("proc.sql", "CREATE PROCEDURE [silver].[p] AS BEGIN SELECT 1; END")
    procs = [o for o in parsed.objects if o.kind == "proc"]
    assert len(procs) == 1
    assert (procs[0].schema, procs[0].name) == ("silver", "p")
