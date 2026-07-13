import os
import sys

# Insert <repo>/py (not the repo root): pytest bundles a top-level `py` shim
# module, so tests import the pipeline as `pipeline.*` to avoid shadowing it.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py"))

# ABOUTME: Shared test fixtures — builds minimal xlsx byte blobs in memory
# ABOUTME: (sheet XML + optional sharedStrings) for the order-sheet parser tests.
import io
import zipfile

import pytest


def make_xlsx(sheet_xml: str, shared_strings_xml: str | None = None) -> bytes:
    """A minimal xlsx: just the entries our parser reads."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if shared_strings_xml is not None:
            zf.writestr("xl/sharedStrings.xml", shared_strings_xml)
    return buf.getvalue()


def inline_cell(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def sheet_of_rows(*rows: str) -> str:
    body = "".join(f"<row>{r}</row>" for r in rows)
    return f'<worksheet><sheetData>{body}</sheetData></worksheet>'


@pytest.fixture
def xlsx():
    return make_xlsx
