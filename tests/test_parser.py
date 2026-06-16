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


def test_unparseable_text_is_tolerated():
    parsed = parse_sql("weird.sql", "CREATE TABLE t (a int);\nGO\nCURSOR nonsense ((( ;\n")
    assert any(o.name == "t" for o in parsed.objects)  # the good batch still parses
