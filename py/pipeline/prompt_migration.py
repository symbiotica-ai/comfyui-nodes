# ABOUTME: One-time split of monolithic per-type architect prompts into shared
# ABOUTME: <project>/prompts/_rules/ blocks plus the type-specific remainder.
import os
import re
import shutil

from .prompt_book import RULES_DIR, prompts_dir, rules_dir

# The rules that describe the GAME rather than one asset type, in the order they
# should compose. Footprint is deliberately absent: it reads as universal, but
# only across three names — FOOTPRINT LOCK, & SCALE (food, appliances), & ANCHOR
# (wall decoration) — because what a type anchors to genuinely differs. Sharing
# it would force one anchor rule onto types that need another.
SHARED_RULES = [
    ("01-reference-usage-split", "REFERENCE USAGE SPLIT"),
    ("02-style-lock", "STYLE LOCK"),
    ("03-unified-lighting", "UNIFIED LIGHTING"),
    ("04-negatives", "NEGATIVES"),
]

# A numbered rule heading: "3. UNIFIED LIGHTING — ..." or "3) STYLE LOCK:".
_HEADING = re.compile(r"^[ \t]*(\d+)[.)][ \t]+(.{4,70}?)[ \t]*(?=—|-|:|$)",
                      re.M)


def split_sections(text):
    """The numbered rule sections of one prompt, as (heading, body) in order.

    Everything before the first numbered heading is returned under the empty
    heading — that is the ROLE / YOUR JOB preamble, which is type-specific and
    must survive the split untouched.
    """
    marks = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]
    if not marks:
        return [("", text)]
    out = [("", text[:marks[0][0]])]
    for i, (start, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out.append((heading, text[start:end]))
    return out


def renumber(sections):
    """Renumber what is left after sections are removed, so the type block does
    not read '1. ... 4. ... 6.' — a model given a gappy list treats the gaps as
    something it was not told."""
    n = 0
    parts = []
    for heading, body in sections:
        if not heading:
            parts.append(body)
            continue
        n += 1
        parts.append(_HEADING.sub(lambda m: f"{n}. {m.group(2)}", body, count=1))
    return "".join(parts)


def plan_migration(project_path):
    """What the split would do, without touching anything.

    For each shared rule, the SOURCE is the type file carrying the longest
    version of it — the most complete wording, not a merge of all eight. Merging
    is an editorial judgement that would be invisible in the resulting diff.
    """
    root = prompts_dir(project_path)
    try:
        names = sorted(n for n in os.listdir(root)
                       if n.endswith(".md") and not n.startswith("_"))
    except OSError:
        names = []
    per_type = {}
    for name in names:
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            per_type[name[:-3]] = split_sections(fh.read())
    extracted, missing = [], []
    for slug, heading in SHARED_RULES:
        found = [(len(body), cat, body)
                 for cat, secs in per_type.items()
                 for h, body in secs if h == heading]
        if not found:
            missing.append(heading)
            continue
        found.sort(reverse=True)
        size, cat, body = found[0]
        extracted.append({"slug": slug, "heading": heading, "source": cat,
                          "chars": size, "text": body.strip(),
                          "in_types": sorted({c for _, c, _ in found})})
    return {"types": per_type, "extracted": extracted, "missing": missing}


def apply_migration(project_path):
    """Write _rules/ and strip those sections from every type file.

    Refuses when _rules/ already exists: a second run would strip sections that
    are no longer there and silently rewrite the type files for nothing. Every
    file is backed up beside itself before it is modified.
    """
    rules = rules_dir(project_path)
    if os.path.isdir(rules):
        raise FileExistsError(
            f"{rules} already exists — this project has been split already. "
            "Remove or rename it to re-run.")
    plan = plan_migration(project_path)
    if not plan["extracted"]:
        raise ValueError(
            f"no shared rules found under {prompts_dir(project_path)} — "
            "nothing to split")
    os.makedirs(rules, exist_ok=True)
    for block in plan["extracted"]:
        with open(os.path.join(rules, f"{block['slug']}.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(block["text"] + "\n")
    shared = {b["heading"] for b in plan["extracted"]}
    root = prompts_dir(project_path)
    changed = []
    for cat, secs in plan["types"].items():
        kept = [(h, b) for h, b in secs if h not in shared]
        if len(kept) == len(secs):
            continue
        path = os.path.join(root, f"{cat}.md")
        shutil.copyfile(path, path + ".before-split")
        before = sum(len(b) for _, b in secs)
        text = renumber(kept).rstrip() + "\n"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        changed.append({"category": cat, "before": before, "after": len(text)})
    return {"rules_dir": rules, "extracted": plan["extracted"],
            "missing": plan["missing"], "changed": sorted(
                changed, key=lambda c: c["category"])}
