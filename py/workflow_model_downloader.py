# ABOUTME: Custom node that parses a ComfyUI workflow JSON to find all referenced
# ABOUTME: safetensor/model files, checks which are missing locally, and downloads them.

import json
import os
import re

import folder_paths


# Node types that load models and the widget keys + target directories they use.
# Format: { node_type: [(widget_key_or_index, comfyui_folder), ...] }
LOADER_NODE_MAP = {
    # Checkpoints
    "CheckpointLoader": [("ckpt_name", "checkpoints")],
    "CheckpointLoaderSimple": [("ckpt_name", "checkpoints")],
    # UNET / Diffusion models
    "UNETLoader": [("unet_name", "diffusion_models")],
    # VAE
    "VAELoader": [("vae_name", "vae")],
    "VAELoaderKJ": [("vae_name", "vae")],
    # CLIP / Text encoders
    "CLIPLoader": [("clip_name", "text_encoders")],
    "DualCLIPLoader": [
        ("clip_name1", "text_encoders"),
        ("clip_name2", "text_encoders"),
    ],
    "TripleCLIPLoader": [
        ("clip_name1", "text_encoders"),
        ("clip_name2", "text_encoders"),
        ("clip_name3", "text_encoders"),
    ],
    # LoRA
    "LoraLoader": [("lora_name", "loras")],
    "LoraLoaderModelOnly": [("lora_name", "loras")],
    # Upscale models
    "UpscaleModelLoader": [("model_name", "upscale_models")],
    "LatentUpscaleModelLoader": [("model_name", "latent_upscale_models")],
    # ControlNet
    "ControlNetLoader": [("control_net_name", "controlnet")],
    # GLIGEN
    "GLIGENLoader": [("gligen_name", "gligen")],
    # Style models
    "StyleModelLoader": [("style_model_name", "style_models")],
    # CLIPVision
    "CLIPVisionLoader": [("clip_name", "clip_vision")],
    # Hypernetwork
    "HypernetworkLoader": [("hypernetwork_name", "hypernetworks")],
    # LTX-specific loaders
    "LTXVGemmaCLIPModelLoader": [
        ("gemma_path", "text_encoders"),
        ("ltxv_path", "checkpoints"),
    ],
    "LTXVAudioVAELoader": [("ckpt_name", "checkpoints")],
    # Audio separation
    "MelBandRoFormerModelLoader": [("model_name", "mel_band_roformer")],
}

# Known widget value index positions for common loaders (fallback for nodes
# section where values are stored as arrays, not dicts).
LOADER_WIDGET_INDICES = {
    "CheckpointLoaderSimple": [(0, "checkpoints")],
    "UNETLoader": [(0, "diffusion_models")],
    "VAELoader": [(0, "vae")],
    "VAELoaderKJ": [(0, "vae")],
    "CLIPLoader": [(0, "text_encoders")],
    "DualCLIPLoader": [(0, "text_encoders"), (1, "text_encoders")],
    "TripleCLIPLoader": [
        (0, "text_encoders"),
        (1, "text_encoders"),
        (2, "text_encoders"),
    ],
    "LoraLoader": [(0, "loras")],
    "LoraLoaderModelOnly": [(0, "loras")],
    "UpscaleModelLoader": [(0, "upscale_models")],
    "LatentUpscaleModelLoader": [(0, "latent_upscale_models")],
    "ControlNetLoader": [(0, "controlnet")],
    "GLIGENLoader": [(0, "gligen")],
    "StyleModelLoader": [(0, "style_models")],
    "CLIPVisionLoader": [(0, "clip_vision")],
    "HypernetworkLoader": [(0, "hypernetworks")],
    "MelBandRoFormerModelLoader": [(0, "mel_band_roformer")],
}

# File extensions that indicate model files
MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pth", ".pt", ".bin", ".gguf"}


def _is_model_filename(value):
    """Check if a string value looks like a model filename."""
    if not isinstance(value, str):
        return False
    return any(value.lower().endswith(ext) for ext in MODEL_EXTENSIONS)


def _normalize_path(filepath):
    """Normalize backslashes and strip leading path separators."""
    return filepath.replace("\\", "/").strip("/")


def _find_model_in_comfyui(filename, folder_type):
    """Check if a model file exists in ComfyUI's known directories."""
    normalized = _normalize_path(filename)
    basename = os.path.basename(normalized)

    try:
        folder_paths_list = folder_paths.get_folder_paths(folder_type)
    except Exception:
        return False, None

    for folder in folder_paths_list:
        # Check exact relative path
        full_path = os.path.join(folder, normalized)
        if os.path.isfile(full_path):
            return True, full_path
        # Check just the basename in case subfolder structure differs
        for root, _dirs, files in os.walk(folder):
            if basename in files:
                return True, os.path.join(root, basename)

    return False, None


def _extract_models_from_nodes(workflow_data):
    """Extract model references from the nodes array in a workflow."""
    models = {}  # {filename: {folder, node_type, node_id, url, directory}}

    nodes = workflow_data.get("nodes", [])
    # Also check inside subgraphs
    for node in _iter_all_nodes(nodes):
        node_type = node.get("type", "")
        node_id = node.get("id", "?")
        widgets = node.get("widgets_values", [])
        properties = node.get("properties", {})

        # Extract from known loader types via widget index
        if node_type in LOADER_WIDGET_INDICES and isinstance(widgets, list):
            for idx, folder in LOADER_WIDGET_INDICES[node_type]:
                if idx < len(widgets) and _is_model_filename(widgets[idx]):
                    fname = _normalize_path(widgets[idx])
                    models[fname] = {
                        "folder": folder,
                        "node_type": node_type,
                        "node_id": node_id,
                        "url": None,
                        "directory": None,
                    }

        # Extract from Power Lora Loader (rgthree) — stores lora paths in
        # widget dicts with "lora" key
        if "lora" in node_type.lower() and "power" in node_type.lower():
            for w in widgets:
                if isinstance(w, dict) and "lora" in w:
                    lora_val = w.get("lora", "")
                    if _is_model_filename(lora_val) and lora_val != "None":
                        fname = _normalize_path(lora_val)
                        models[fname] = {
                            "folder": "loras",
                            "node_type": node_type,
                            "node_id": node_id,
                            "url": None,
                            "directory": None,
                        }

        # Check properties.models[] for embedded download URLs
        prop_models = properties.get("models", [])
        if isinstance(prop_models, list):
            for pm in prop_models:
                if isinstance(pm, dict) and pm.get("url"):
                    name = pm.get("name", "")
                    url = pm.get("url", "")
                    directory = pm.get("directory", "")
                    if name:
                        fname = _normalize_path(name)
                        # Update existing entry or create new one
                        if fname in models:
                            models[fname]["url"] = url
                            models[fname]["directory"] = directory
                        else:
                            models[fname] = {
                                "folder": directory or _guess_folder(node_type),
                                "node_type": node_type,
                                "node_id": node_id,
                                "url": url,
                                "directory": directory,
                            }

    return models


def _extract_models_from_prompt(workflow_data):
    """Extract model references from the extra.prompt section (API format)."""
    models = {}
    prompt = workflow_data.get("extra", {}).get("prompt", {})

    for node_id, node_data in prompt.items():
        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        if class_type in LOADER_NODE_MAP:
            for key, folder in LOADER_NODE_MAP[class_type]:
                value = inputs.get(key, "")
                if _is_model_filename(value):
                    fname = _normalize_path(value)
                    models[fname] = {
                        "folder": folder,
                        "node_type": class_type,
                        "node_id": node_id,
                        "url": None,
                        "directory": None,
                    }

    return models


def _iter_all_nodes(nodes):
    """Recursively iterate all nodes including those inside subgraphs."""
    for node in nodes:
        yield node
        # Subgraph nodes have a nested "nodes" array
        sub_nodes = node.get("nodes", [])
        if isinstance(sub_nodes, list):
            yield from _iter_all_nodes(sub_nodes)


def _guess_folder(node_type):
    """Guess the target folder based on node type name."""
    nt = node_type.lower()
    if "vae" in nt:
        return "vae"
    if "clip" in nt:
        return "text_encoders"
    if "lora" in nt:
        return "loras"
    if "unet" in nt:
        return "diffusion_models"
    if "checkpoint" in nt:
        return "checkpoints"
    if "controlnet" in nt:
        return "controlnet"
    if "upscale" in nt:
        return "upscale_models"
    return "checkpoints"


def _deep_scan_model_strings(obj):
    """Brute-force scan the entire workflow JSON for model filenames.

    Returns a set of model filenames found anywhere in the data structure.
    This catches models that structured parsing might miss.
    """
    results = set()
    if isinstance(obj, str):
        val = obj.strip()
        if _is_model_filename(val):
            # Skip full URLs — they're download links, not filenames
            if not val.startswith("http"):
                results.add(val)
    elif isinstance(obj, list):
        for item in obj:
            results.update(_deep_scan_model_strings(item))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.update(_deep_scan_model_strings(v))
    return results


def _extract_embedded_urls(obj):
    """Scan the entire workflow for properties.models[] download URLs.

    Returns a dict mapping model filename -> download URL.
    """
    urls = {}
    if isinstance(obj, dict):
        # Check if this dict has a "models" key with URL entries
        models_list = obj.get("models", [])
        if isinstance(models_list, list):
            for pm in models_list:
                if isinstance(pm, dict) and pm.get("url") and pm.get("name"):
                    name = _normalize_path(pm["name"])
                    urls[name] = {
                        "url": pm["url"],
                        "directory": pm.get("directory", ""),
                    }
        for v in obj.values():
            urls.update(_extract_embedded_urls(v))
    elif isinstance(obj, list):
        for item in obj:
            urls.update(_extract_embedded_urls(item))
    return urls


def _guess_folder_from_filename(filename):
    """Guess the ComfyUI folder from the filename or path context."""
    fn_lower = filename.lower()
    path_parts = fn_lower.replace("\\", "/").split("/")

    # Check path components for hints
    for part in path_parts:
        if "lora" in part:
            return "loras"
        if "vae" in part:
            return "vae"
        if "clip" in part or "text_encoder" in part or "gemma" in part:
            return "text_encoders"
        if "controlnet" in part:
            return "controlnet"
        if "upscale" in part:
            return "upscale_models"

    # Check filename itself
    basename = path_parts[-1]
    if "vae" in basename:
        return "vae"
    if "lora" in basename:
        return "loras"
    if "clip" in basename or "text_projection" in basename or "gemma" in basename:
        return "text_encoders"
    if "upscale" in basename:
        return "upscale_models"
    if "melband" in basename or "roformer" in basename:
        return "mel_band_roformer"

    return "checkpoints"


def _download_model(url, target_dir, filename):
    """Download a model file from a URL to the target directory."""
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, os.path.basename(filename))

    if os.path.isfile(target_path):
        return True, f"Already exists: {target_path}"

    # Try huggingface_hub first for HF URLs
    if "huggingface.co" in url:
        try:
            from huggingface_hub import hf_hub_download

            # Parse HF URL: https://huggingface.co/{repo_id}/resolve/main/{filepath}
            match = re.match(
                r"https://huggingface\.co/([^/]+/[^/]+)/resolve/[^/]+/(.*)", url
            )
            if match:
                repo_id = match.group(1)
                repo_filename = match.group(2)
                hf_hub_download(
                    repo_id=repo_id,
                    filename=repo_filename,
                    local_dir=target_dir,
                    local_dir_use_symlinks=False,
                )
                # hf_hub_download may place the file in a subfolder matching
                # the repo structure — move it if needed
                downloaded = os.path.join(target_dir, repo_filename)
                if os.path.isfile(downloaded) and downloaded != target_path:
                    os.rename(downloaded, target_path)
                return True, f"Downloaded via HF Hub: {target_path}"
        except Exception as e:
            print(f"[ModelDownloader] HF Hub download failed, falling back to requests: {e}")

    # Fallback to direct HTTP download
    try:
        import requests

        print(f"[ModelDownloader] Downloading {filename} from {url}...")
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded_size = 0

        with open(target_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192 * 1024):
                f.write(chunk)
                downloaded_size += len(chunk)
                if total_size > 0:
                    pct = (downloaded_size / total_size) * 100
                    print(f"[ModelDownloader] {filename}: {pct:.1f}%")

        return True, f"Downloaded: {target_path}"
    except Exception as e:
        # Clean up partial download
        if os.path.isfile(target_path):
            os.remove(target_path)
        return False, f"Download failed: {e}"


class NSWorkflowModelDownloader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "workflow_json_path": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "Absolute path to the workflow .json file",
                }),
                "auto_download": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Automatically download models that have known URLs. "
                               "When off, only scans and reports.",
                }),
            },
            "optional": {
                "llm_model_lookup": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional: paste LLM response with download URLs "
                               "as JSON (see report output for format)",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report",)
    FUNCTION = "scan_and_download"
    CATEGORY = "neuralsins/utils"
    OUTPUT_NODE = True

    def scan_and_download(
        self, workflow_json_path, auto_download, llm_model_lookup=""
    ):
        # Load workflow JSON
        wf_path = workflow_json_path.strip()
        if not wf_path:
            return ("Error: No workflow JSON path provided.",)

        if not os.path.isfile(wf_path):
            return (f"Error: File not found: {wf_path}",)

        try:
            with open(wf_path, "r", encoding="utf-8") as f:
                workflow = json.load(f)
        except Exception as e:
            return (f"Error loading JSON: {e}",)

        # Extract model references from both formats
        models_from_nodes = _extract_models_from_nodes(workflow)
        models_from_prompt = _extract_models_from_prompt(workflow)

        # Merge (nodes take priority since they have more metadata)
        all_models = {**models_from_prompt, **models_from_nodes}

        # Deep scan to catch anything the structured parsing missed
        deep_scan_files = _deep_scan_model_strings(workflow)
        for fname in deep_scan_files:
            normalized = _normalize_path(fname)
            if normalized not in all_models:
                all_models[normalized] = {
                    "folder": _guess_folder_from_filename(normalized),
                    "node_type": "unknown",
                    "node_id": "?",
                    "url": None,
                    "directory": None,
                }

        # Collect all embedded download URLs from the entire workflow
        embedded_urls = _extract_embedded_urls(workflow)
        for fname, url_info in embedded_urls.items():
            if fname in all_models and not all_models[fname].get("url"):
                all_models[fname]["url"] = url_info["url"]
                if url_info.get("directory"):
                    all_models[fname]["folder"] = url_info["directory"]

        if not all_models:
            return ("No model references found in this workflow.",)

        # Parse optional LLM lookup URLs
        llm_urls = {}
        if llm_model_lookup and llm_model_lookup.strip():
            try:
                llm_urls = json.loads(llm_model_lookup.strip())
                if not isinstance(llm_urls, dict):
                    llm_urls = {}
            except json.JSONDecodeError:
                pass

        # Check each model
        found = []
        missing_with_url = []
        missing_no_url = []

        for filename, info in sorted(all_models.items()):
            folder = info["folder"]
            exists, local_path = _find_model_in_comfyui(filename, folder)

            # Also check with just basename in common alternative folders
            if not exists:
                for alt_folder in ["checkpoints", "diffusion_models", "loras",
                                   "vae", "text_encoders", "clip_vision",
                                   "upscale_models", "controlnet"]:
                    if alt_folder != folder:
                        exists, local_path = _find_model_in_comfyui(filename, alt_folder)
                        if exists:
                            break

            if exists:
                found.append((filename, folder, local_path))
            else:
                url = info.get("url") or llm_urls.get(filename) or llm_urls.get(os.path.basename(filename))
                if url:
                    missing_with_url.append((filename, folder, url, info))
                else:
                    missing_no_url.append((filename, folder, info))

        # Build report
        lines = []
        lines.append(f"=== Workflow Model Scan ===")
        lines.append(f"Total models referenced: {len(all_models)}")
        lines.append(f"Found locally: {len(found)}")
        lines.append(f"Missing (URL known): {len(missing_with_url)}")
        lines.append(f"Missing (URL unknown): {len(missing_no_url)}")
        lines.append("")

        if found:
            lines.append("--- FOUND ---")
            for fname, folder, path in found:
                lines.append(f"  [OK] {fname} ({folder})")
            lines.append("")

        # Download if auto_download is on
        downloaded = []
        download_failed = []
        if auto_download and missing_with_url:
            lines.append("--- DOWNLOADING ---")
            for fname, folder, url, info in missing_with_url:
                try:
                    folder_paths_list = folder_paths.get_folder_paths(folder)
                    target_dir = folder_paths_list[0] if folder_paths_list else None
                except Exception:
                    target_dir = None

                if not target_dir:
                    download_failed.append((fname, f"Unknown folder path for: {folder}"))
                    lines.append(f"  [SKIP] {fname} - unknown folder: {folder}")
                    continue

                success, msg = _download_model(url, target_dir, fname)
                if success:
                    downloaded.append((fname, msg))
                    lines.append(f"  [DONE] {fname} -> {msg}")
                else:
                    download_failed.append((fname, msg))
                    lines.append(f"  [FAIL] {fname} - {msg}")
            lines.append("")

        if missing_with_url and not auto_download:
            lines.append("--- MISSING (URL available - enable auto_download) ---")
            for fname, folder, url, info in missing_with_url:
                lines.append(f"  {fname}")
                lines.append(f"    folder: {folder}")
                lines.append(f"    url: {url}")
            lines.append("")

        if missing_no_url:
            lines.append("--- MISSING (no URL - need manual lookup) ---")
            for fname, folder, info in missing_no_url:
                lines.append(f"  {fname}")
                lines.append(f"    folder: {folder}")
                lines.append(f"    node: {info['node_type']} (id: {info['node_id']})")
            lines.append("")

            # Generate LLM prompt helper
            missing_names = [fname for fname, _, _ in missing_no_url]
            lines.append("--- LLM LOOKUP PROMPT ---")
            lines.append("Connect an LLM Chat node and ask it:")
            lines.append("")
            lines.append(
                "Find HuggingFace download URLs for these ComfyUI model files. "
                "Return ONLY a JSON object mapping filename to full download URL. "
                "Example format: {\"model.safetensors\": \"https://huggingface.co/org/repo/resolve/main/model.safetensors\"}"
            )
            lines.append("")
            lines.append("Models to find:")
            for name in missing_names:
                lines.append(f"  - {name}")
            lines.append("")
            lines.append(
                "Then paste the LLM response into the 'llm_model_lookup' input "
                "and run again with auto_download enabled."
            )

        if auto_download:
            lines.append(f"--- SUMMARY ---")
            lines.append(f"Downloaded: {len(downloaded)}")
            lines.append(f"Failed: {len(download_failed)}")

        report = "\n".join(lines)
        print(f"[ModelDownloader]\n{report}")
        return (report,)


NODE_CLASS_MAPPINGS = {
    "NSWorkflowModelDownloader": NSWorkflowModelDownloader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWorkflowModelDownloader": "NS Workflow Model Downloader",
}
