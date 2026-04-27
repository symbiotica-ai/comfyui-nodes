# ABOUTME: Skill selector node for ComfyUI. Scans the skills directory and shows each skill
# ABOUTME: as a toggle. Enabled skills are loaded and output as a list for the agent settings node.

import configparser
import os
import re

_package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_skills_dir() -> str:
    """Resolve the skills directory path from env var, config.ini, or default."""
    env_path = os.environ.get("SYMBIOTICA_SKILLS_DIR")
    if env_path and os.path.isdir(env_path):
        return env_path

    config_path = os.path.join(_package_dir, "config.ini")
    if os.path.isfile(config_path):
        config = configparser.ConfigParser()
        config.read(config_path)
        ini_path = config.get("skills", "skills_dir", fallback=None)
        if ini_path and os.path.isdir(ini_path):
            return ini_path

    return os.path.join(_package_dir, "skills")


def _list_skills_from(skills_dir: str) -> list[str]:
    """Scan a directory for skill subdirectories containing SKILL.md."""
    skills = []
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, name)
            if os.path.isdir(skill_path) and os.path.isfile(os.path.join(skill_path, "SKILL.md")):
                skills.append(name)
    return skills


def _list_skills() -> list[str]:
    """Scan the default skills directory for skill subdirectories containing SKILL.md."""
    return _list_skills_from(_get_skills_dir())


def _read_skill(skill_dir: str) -> dict:
    """Read a skill definition from a directory containing SKILL.md."""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_path):
        return {"name": os.path.basename(skill_dir), "content": ""}

    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract name from frontmatter
    name = os.path.basename(skill_dir)
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    body = content
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        body = content[frontmatter_match.end():]
        for line in frontmatter.strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                if key.strip().lower() == "name":
                    name = value.strip()

    return {"name": name, "content": body.strip()}


def _skill_to_param(skill_name: str) -> str:
    """Convert a skill directory name to a valid Python parameter name."""
    return skill_name.replace("-", "_")


def _param_to_skill(param_name: str, available_skills: list[str]) -> str | None:
    """Map a parameter name back to the original skill directory name."""
    for skill_name in available_skills:
        if _skill_to_param(skill_name) == param_name:
            return skill_name
    return None


class SymbioticaSkills:
    @classmethod
    def INPUT_TYPES(cls):
        skills = _list_skills()
        optional = {}
        for skill_name in skills:
            param = _skill_to_param(skill_name)
            optional[param] = ("BOOLEAN", {
                "default": False,
                "tooltip": f"Enable the '{skill_name}' skill.",
            })
        return {
            "required": {},
            "optional": {
                "skills_path": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "Path to skills directory. Overrides env var and config.ini.",
                }),
                **optional,
            },
        }

    RETURN_TYPES = ("AGENT_SKILLS",)
    RETURN_NAMES = ("skills",)
    FUNCTION = "load"
    CATEGORY = "symbiotica/LLM"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """Force re-evaluation when any skill file changes on disk."""
        skills_dir = _get_skills_dir()
        latest = 0.0
        for skill_name in _list_skills():
            skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")
            if os.path.isfile(skill_path):
                latest = max(latest, os.path.getmtime(skill_path))
        # Also detect added/removed skills by checking the directory itself
        if os.path.isdir(skills_dir):
            latest = max(latest, os.path.getmtime(skills_dir))
        return latest if latest > 0 else float("nan")

    def load(self, **kwargs):
        path_override = kwargs.pop("skills_path", "")
        if path_override and path_override.strip() and os.path.isdir(path_override.strip()):
            skills_dir = path_override.strip()
        else:
            skills_dir = _get_skills_dir()
        available_skills = _list_skills_from(skills_dir)
        enabled = []

        for param_name, is_enabled in kwargs.items():
            if not is_enabled:
                continue
            skill_name = _param_to_skill(param_name, available_skills)
            if not skill_name:
                continue
            skill_dir = os.path.join(skills_dir, skill_name)
            if os.path.isdir(skill_dir):
                skill_data = _read_skill(skill_dir)
                enabled.append(skill_data)
                print(f"[Symbiotica] Skill enabled: {skill_name}")

        return (enabled,)


NODE_CLASS_MAPPINGS = {
    "SymbioticaSkills": SymbioticaSkills,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaSkills": "Symbiotica Skills",
}
