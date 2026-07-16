import json
from pathlib import Path
from coop_sql_review.sql_model import EstateCatalog, ParsedFile, ColumnDef


def _normalize(s: str) -> str:
    s = s.strip()
    while len(s) >= 2 and s[0] in "'\"[" and s[-1] in "'\"]":
        s = s[1:-1].strip()
    return s.lower()


def build_catalog(parsed_files: list[ParsedFile], schema_path: str | None = None) -> EstateCatalog:
    catalog = EstateCatalog()

    # 1. Load external JSON schema if provided
    if schema_path:
        p = Path(schema_path)
        if p.is_file():
            try:
                data = json.loads(p.read_text())
                if isinstance(data, dict):
                    for table_name, cols in data.items():
                        norm_table = _normalize(table_name)
                        if isinstance(cols, dict):
                            cat_cols = {}
                            for col_name, col_type in cols.items():
                                norm_col = _normalize(col_name)
                                # Extracted types might not have a clean base_type unless we parse it.
                                # For our rules, they mostly check the start of the type (e.g. 'nvarchar')
                                base_type = col_type.split("(")[0].upper()
                                cat_cols[norm_col] = ColumnDef(
                                    name=col_name, data_type=col_type, base_type=base_type, line=0
                                )
                            catalog.tables[norm_table] = cat_cols
            except Exception:
                pass

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
