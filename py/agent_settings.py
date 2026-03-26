# ABOUTME: Agent settings node for ComfyUI. Loads agent definitions from CLAUDE.md + SOUL.md
# ABOUTME: per agent, plus shared SOUL.md and USER.md from the agents root directory.

import configparser
import os

from .llm_api import all_models

_package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_agents_dir() -> str:
    """Resolve the agents directory path from env var, config.ini, or default."""
    env_path = os.environ.get("SYMBIOTICA_AGENTS_DIR")
    if env_path and os.path.isdir(env_path):
        return env_path

    config_path = os.path.join(_package_dir, "config.ini")
    if os.path.isfile(config_path):
        config = configparser.ConfigParser()
        config.read(config_path)
        ini_path = config.get("agents", "agents_dir", fallback=None)
        if ini_path and os.path.isdir(ini_path):
            return ini_path

    return os.path.join(_package_dir, "agents")


def _read_file(filepath: str) -> str:
    """Read a file and return its content, or empty string if not found."""
    if os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _read_agent(agent_dir: str) -> dict:
    """Read an agent definition: CLAUDE.md + SOUL.md from agent dir, shared files from parent."""
    agents_root = os.path.dirname(agent_dir)

    # Agent-specific soul layered on shared soul
    shared_soul = _read_file(os.path.join(agents_root, "SOUL.md"))
    agent_soul = _read_file(os.path.join(agent_dir, "SOUL.md"))
    if shared_soul and agent_soul:
        soul = shared_soul + "\n\n" + agent_soul
    else:
        soul = agent_soul or shared_soul

    return {
        "soul": soul,
        "instructions": _read_file(os.path.join(agent_dir, "CLAUDE.md")),
        "user_context": _read_file(os.path.join(agents_root, "USER.md")),
    }


def _list_agents() -> list[str]:
    """Scan the agents directory for agent subdirectories."""
    agents_dir = _get_agents_dir()
    agents = []
    if os.path.isdir(agents_dir):
        for name in sorted(os.listdir(agents_dir)):
            agent_path = os.path.join(agents_dir, name)
            if os.path.isdir(agent_path) and os.path.isfile(os.path.join(agent_path, "CLAUDE.md")):
                agents.append(name)
    return agents


def _get_agent_choices() -> list[str]:
    """Build dropdown: (custom) + discovered agents."""
    return ["(custom)"] + _list_agents()


def _latest_mtime(agent_dir: str) -> float:
    """Get the most recent modification time across agent and shared files."""
    agents_root = os.path.dirname(agent_dir)
    latest = 0.0
    paths = [
        os.path.join(agent_dir, "CLAUDE.md"),
        os.path.join(agent_dir, "SOUL.md"),
        os.path.join(agents_root, "SOUL.md"),
        os.path.join(agents_root, "USER.md"),
    ]
    for filepath in paths:
        if os.path.isfile(filepath):
            latest = max(latest, os.path.getmtime(filepath))
    return latest


class SymbioticaAgentSettings:
    @classmethod
    def INPUT_TYPES(cls):
        choices = _get_agent_choices()
        return {
            "required": {
                "agent": (choices, {
                    "default": choices[0],
                    "tooltip": "Select an agent to pre-fill fields, or (custom) to define manually.",
                }),
                "soul": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Personality, values, boundaries. Loaded from shared + agent SOUL.md.",
                }),
                "instructions": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Identity and operating instructions. Loaded from agent CLAUDE.md.",
                }),
            },
            "optional": {
                "user_context": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Who the agent serves. Loaded from shared USER.md.",
                }),
                "model": (all_models, {
                    "default": "claude-sonnet-4-6",
                    "tooltip": "LLM model for this agent.",
                }),
                "api_key": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "API key. Falls back to environment variable if empty.",
                }),
                "skills": ("AGENT_SKILLS",),
            },
        }

    RETURN_TYPES = ("AGENT_SETTINGS",)
    RETURN_NAMES = ("agent_settings",)
    FUNCTION = "configure"
    CATEGORY = "symbiotica/LLM"

    @classmethod
    def IS_CHANGED(cls, agent, **kwargs):
        """Force re-evaluation when agent files change on disk."""
        if agent != "(custom)":
            agents_dir = _get_agents_dir()
            agent_dir = os.path.join(agents_dir, agent)
            if os.path.isdir(agent_dir):
                return _latest_mtime(agent_dir)
        return float("nan")

    def configure(
        self,
        agent: str,
        soul: str,
        instructions: str,
        user_context: str = "",
        model: str = "claude-sonnet-4-6",
        api_key: str = "",
        skills: list = None,
    ):
        base = {"soul": "", "instructions": "", "user_context": ""}

        if agent != "(custom)":
            agents_dir = _get_agents_dir()
            agent_dir = os.path.join(agents_dir, agent)
            if os.path.isdir(agent_dir):
                base = _read_agent(agent_dir)
                print(f"[Symbiotica] Loaded agent: {agent}")
            else:
                print(f"[Symbiotica] Warning: agent directory not found: {agent_dir}")

        settings = {
            "soul": soul.strip() if soul.strip() else base["soul"],
            "instructions": instructions.strip() if instructions.strip() else base["instructions"],
            "user_context": user_context.strip() if user_context.strip() else base["user_context"],
            "model": model,
            "api_key": api_key.strip(),
            "skills": skills if skills is not None else [],
        }

        return (settings,)


NODE_CLASS_MAPPINGS = {
    "SymbioticaAgentSettings": SymbioticaAgentSettings,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaAgentSettings": "Symbiotica Agent Settings",
}
