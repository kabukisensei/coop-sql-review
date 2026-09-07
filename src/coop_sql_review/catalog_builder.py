import json
from pathlib import Path

from coop_sql_review.sql_model import ColumnDef, EstateCatalog, ParsedFile


class ExternalSchemaError(ValueError):
    """An explicitly requested external schema could not be loaded safely."""


def _normalize(s: str) -> str:
    s = s.strip()
    while len(s) >= 2 and s[0] in "'\"[" and s[-1] in "'\"]":
        s = s[1:-1].strip()
    return s.lower()


def _load_external_schema(schema_path: str) -> dict[str, dict[str, str]]:
    """Read and validate the documented ``table -> column -> SQL type`` shape."""
    path = Path(schema_path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExternalSchemaError(f"{path}: schema is not valid UTF-8") from exc
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ExternalSchemaError(f"{path}: schema could not be read ({reason})") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExternalSchemaError(
            f"{path}: schema is not valid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})"
        ) from exc

    if not isinstance(data, dict):
        raise ExternalSchemaError(
            f"{path}: schema root must be a JSON object mapping table names to column objects"
        )

    validated: dict[str, dict[str, str]] = {}
    for table_name, columns in data.items():
        if not isinstance(table_name, str) or not table_name.strip():
            raise ExternalSchemaError(f"{path}: table names must be non-empty strings (got {table_name!r})")
        if not isinstance(columns, dict):
            raise ExternalSchemaError(f"{path}: table {table_name!r} must map to a JSON object of columns")

        validated_columns: dict[str, str] = {}
        for column_name, column_type in columns.items():
            if not isinstance(column_name, str) or not column_name.strip():
                raise ExternalSchemaError(
                    f"{path}: column names in table {table_name!r} must be non-empty strings"
                )
            if not isinstance(column_type, str) or not column_type.strip():
                raise ExternalSchemaError(
                    f"{path}: column {column_name!r} in table {table_name!r} "
                    "must have a non-empty string SQL type"
                )
            normalized_type = column_type.strip()
            if not normalized_type.split("(", 1)[0].strip():
                raise ExternalSchemaError(
                    f"{path}: column {column_name!r} in table {table_name!r} has an invalid SQL type"
                )
            validated_columns[column_name] = normalized_type
        validated[table_name] = validated_columns
    return validated


def build_catalog(parsed_files: list[ParsedFile], schema_path: str | None = None) -> EstateCatalog:
    catalog = EstateCatalog()

    # 1. Load external JSON schema if provided
    if schema_path:
        data = _load_external_schema(schema_path)
        for table_name, cols in data.items():
            norm_table = _normalize(table_name)
            cat_cols = {}
            for col_name, col_type in cols.items():
                norm_col = _normalize(col_name)
                # Extracted types might not have a clean base_type unless we parse it.
                # For our rules, they mostly check the start of the type (e.g. 'nvarchar').
                base_type = col_type.split("(", 1)[0].strip().upper()
                cat_cols[norm_col] = ColumnDef(name=col_name, data_type=col_type, base_type=base_type, line=0)
            catalog.tables[norm_table] = cat_cols

    # 2. Add columns from parsed files
    for parsed in parsed_files:
        for obj in parsed.objects:
            if obj.kind == "table" and not obj.is_temp:
                norm_table = _normalize(obj.qualified)
                if norm_table not in catalog.tables:
                    catalog.tables[norm_table] = {}

                table_dict = catalog.tables[norm_table]

                for col in obj.columns:
                    norm_col = _normalize(col.name)
                    if norm_col in table_dict:
                        # Conflict handling: drop if base_type differs
                        existing = table_dict[norm_col]
                        if existing.base_type != col.base_type:
                            # Setting to a dummy with base_type = "CONFLICT" effectively drops it for rule use
                            table_dict[norm_col] = ColumnDef(
                                name=col.name, data_type="CONFLICT", base_type="CONFLICT", line=0
                            )
                    else:
                        table_dict[norm_col] = col

    return catalog
