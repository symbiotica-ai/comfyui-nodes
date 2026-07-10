# ABOUTME: Shared test fixtures — builds minimal xlsx byte blobs in memory
# ABOUTME: (sheet XML + optional sharedStrings) for the order-sheet parser tests.
import io
import os
import sys
import zipfile

import pytest

# Add repo root to sys.path early so imports work
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


def pytest_configure(config):
    """Ensure repo root is on sys.path after pytest has loaded its own modules."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


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
