"""The bundled standards must stay byte-identical to the authored canon.

The JSON contract ships the bundled file's sha256 as provenance ("this report was
produced against exactly these standards"); if `docs/standards.md` and the packaged
copy drift, that guarantee is hollow. This test makes the invariant self-enforcing.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_bundled_standards_matches_docs():
    docs = ROOT / "docs" / "standards.md"
    bundled = ROOT / "src" / "coop_sql_review" / "data" / "standards.md"
    assert docs.is_file() and bundled.is_file()
    docs_hash = hashlib.sha256(docs.read_bytes()).hexdigest()
    bundled_hash = hashlib.sha256(bundled.read_bytes()).hexdigest()
    assert docs_hash == bundled_hash, (
        "docs/standards.md and src/coop_sql_review/data/standards.md have drifted; "
        "re-copy the canon into the package so the JSON sha256 provenance stays honest."
    )
