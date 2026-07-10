import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# pytest 9 imports its bundled `py` shim module at startup (_pytest/compat.py),
# so by conftest time the top-level name `py` is already a plain module and our
# local py/ package can never win the import. Point the shim's __path__ at py/
# so `import py.pipeline.*` resolves locally (py.path/py.error keep working).
import py

if not hasattr(py, "__path__"):
    py.__path__ = [os.path.join(_REPO_ROOT, "py")]

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
