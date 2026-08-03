# ABOUTME: Records which architect prompt produced which image — the block
# ABOUTME: manifest, its hashes, the seed and the reference drawn — per render.
import hashlib
import json
import os

from .prompt_book import RULES_DIR, prompts_dir, rules_dir

LOG_NAME = "renders.jsonl"


def sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def block_manifest(project_path, category):
    """The blocks that compose one type's prompt, each with its own hash.

    Per BLOCK, not one hash for the composed whole: the point of feedback is to
    say which rule was at fault, and a single hash over the finished prompt
    cannot tell a lighting change from a negatives change. Order matches
    composition — shared rules, then the type block.
    """
    out = []
    root = rules_dir(project_path)
    try:
        names = sorted(n for n in os.listdir(root) if n.endswith(".md"))
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if text.strip():
            out.append({"block": f"{RULES_DIR}/{name}", "sha": sha(text),
                        "chars": len(text)})
    type_path = os.path.join(prompts_dir(project_path), f"{category}.md")
    try:
        with open(type_path, encoding="utf-8") as fh:
            text = fh.read()
        out.append({"block": f"{category}.md", "sha": sha(text),
                    "chars": len(text)})
    except OSError:
        pass
    return out


def build_record(*, project_path, asset_name, category, system_prompt,
                 client_prompt="", reference="", seed=None, feature="",
                 month="", image_file=""):
    """One render's provenance.

    `prompt_sha` hashes the composed text that was actually sent, so a record
    stays truthful even if the files change afterwards; `blocks` names the
    versions it came from, so feedback can be aimed at one of them.
    """
    return {
        "image": image_file,
        "asset": asset_name,
        "category": category,
        "feature": feature,
        "month": month,
        "seed": seed,
        "reference": reference,
        "prompt_sha": sha(system_prompt),
        "prompt_chars": len(system_prompt or ""),
        "client_prompt": client_prompt,
        "blocks": block_manifest(project_path, category),
    }


def log_path(project_path):
    """The run log sits in the prompt book: the thing it is a history OF."""
    return os.path.join(prompts_dir(project_path), LOG_NAME)


def append_records(project_path, records, timestamp=""):
    """Append to the project's render log, one JSON object per line.

    JSONL rather than one JSON document so a crashed or interrupted run leaves
    every completed render readable instead of a truncated array that no longer
    parses. Never raises: losing the log must not lose the images.
    """
    path = log_path(project_path)
    written = 0
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps({**rec, "at": timestamp},
                                    ensure_ascii=False) + "\n")
                written += 1
    except OSError:
        return 0
    return written


def read_records(project_path, limit=50):
    """The most recent records, newest last. A malformed line is skipped rather
    than failing the read — a half-written line from a killed run must not hide
    every good record behind it."""
    out = []
    try:
        with open(log_path(project_path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:] if limit else out
