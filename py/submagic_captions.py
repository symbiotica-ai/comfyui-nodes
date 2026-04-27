# ABOUTME: Submagic API node that adds AI-powered animated captions to videos
# ABOUTME: Uploads video to Submagic, applies styled captions, downloads the result

import configparser
import os
import tempfile
import time

import requests
import folder_paths

API_BASE = "https://api.submagic.co/v1"

SUBMAGIC_TEMPLATES = [
    "Sara", "Daniel", "Dan 2", "Hormozi 4", "Dan", "Devin", "Tayo",
    "Ella", "Tracy", "Luke", "Hormozi 1", "Hormozi 2", "Hormozi 3",
    "Hormozi 5", "Leila", "Jason", "William", "Leon", "Ali", "Beast",
    "Maya", "Karl", "Iman", "Umi", "David", "Noah", "Gstaad", "Malta",
    "Nema", "seth",
]

SUBMAGIC_LANGUAGES = [
    "en", "el", "es", "fr", "de", "it", "pt", "nl", "ru",
    "zh", "ja", "ko", "ar", "hi",
]


class NSSubmagicCaptions:
    """
    Adds AI-powered animated captions to a video using the Submagic API.
    Supports 30+ caption templates and 100+ languages.
    Connect a VIDEO, pick a style, and get back a captioned video.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "language": (SUBMAGIC_LANGUAGES, {"default": "en"}),
                "template": (SUBMAGIC_TEMPLATES, {"default": "Hormozi 2"}),
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "tooltip": "Submagic API key (or set in config.ini / SUBMAGIC_API_KEY env var)"}),
                "magic_zooms": ("BOOLEAN", {"default": False, "tooltip": "Auto zoom effects on key moments"}),
                "magic_brolls": ("BOOLEAN", {"default": False, "tooltip": "Auto B-roll insertion"}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _resolve_api_key(self, api_key):
        """Resolve API key from widget, config.ini, or environment variable."""
        if api_key:
            return api_key

        parent_dir = os.path.join(os.path.dirname(__file__), "..")
        config_path = os.path.join(parent_dir, "config.ini")
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path)
            key = config.get("API", "submagic_api_key", fallback="")
            if key:
                return key

        key = os.environ.get("SUBMAGIC_API_KEY", "")
        if key:
            return key

        raise ValueError(
            "Submagic API key not found. Provide via the api_key input, "
            "config.ini [API] submagic_api_key, or SUBMAGIC_API_KEY env var."
        )

    def _upload(self, api_key, file_path, language, template, magic_zooms, magic_brolls):
        """Upload video to Submagic and return project ID."""
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{API_BASE}/projects/upload",
                headers={"x-api-key": api_key},
                files={"file": (os.path.basename(file_path), f, "video/mp4")},
                data={
                    "title": f"ComfyUI_{int(time.time())}",
                    "language": language,
                    "templateName": template,
                    "magicZooms": str(magic_zooms).lower(),
                    "magicBrolls": str(magic_brolls).lower(),
                },
            )

        if resp.status_code != 201:
            raise RuntimeError(f"Submagic upload failed ({resp.status_code}): {resp.text[:500]}")

        return resp.json()["id"]

    def _poll(self, api_key, project_id, field, target, timeout=600):
        """Poll project until a field reaches the target value."""
        headers = {"x-api-key": api_key}
        start = time.time()

        while time.time() - start < timeout:
            resp = requests.get(f"{API_BASE}/projects/{project_id}", headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Submagic poll failed ({resp.status_code}): {resp.text[:500]}")

            data = resp.json()
            current = data.get(field, "")
            status = data.get("status", "")

            if status == "failed":
                reason = data.get("failureReason", "Unknown")
                raise RuntimeError(f"Submagic processing failed: {reason}")

            print(f"[NSSubmagicCaptions] {field}={current} status={status}")

            if current.lower() == target.lower():
                return data

            time.sleep(5)

        raise RuntimeError(f"Submagic timeout ({timeout}s) waiting for {field}={target}")

    def _export(self, api_key, project_id):
        """Trigger export/render of the project."""
        resp = requests.post(
            f"{API_BASE}/projects/{project_id}/export",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Submagic export failed ({resp.status_code}): {resp.text[:500]}")

    def _download(self, url, output_path):
        """Download video from URL to local file."""
        resp = requests.get(url, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

    def execute(self, video, language, template, api_key="", magic_zooms=False, magic_brolls=False):
        from comfy_api.latest import InputImpl

        resolved_key = self._resolve_api_key(api_key)
        temp_files = []

        try:
            # Save input video to temp file
            temp_in = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_files.append(temp_in.name)
            temp_in.close()
            video.save_to(temp_in.name, format="mp4", codec="h264")

            # Upload to Submagic
            print("[NSSubmagicCaptions] Uploading...")
            project_id = self._upload(
                resolved_key, temp_in.name, language, template, magic_zooms, magic_brolls
            )
            print(f"[NSSubmagicCaptions] Project: {project_id}")

            # Wait for transcription
            print("[NSSubmagicCaptions] Transcribing...")
            self._poll(resolved_key, project_id, "transcriptionStatus", "COMPLETED", timeout=300)

            # Trigger export
            print("[NSSubmagicCaptions] Exporting...")
            self._export(resolved_key, project_id)

            # Wait for export
            data = self._poll(resolved_key, project_id, "status", "completed", timeout=600)

            # Download result
            download_url = data.get("directUrl") or data.get("downloadUrl")
            if not download_url:
                raise RuntimeError("Submagic did not return a download URL")

            output_dir = folder_paths.get_output_directory()
            output_file = os.path.join(output_dir, f"submagic_{int(time.time())}.mp4")

            print("[NSSubmagicCaptions] Downloading...")
            self._download(download_url, output_file)

            print(f"[NSSubmagicCaptions] Done → {output_file}")
            return (InputImpl.VideoFromFile(output_file),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSSubmagicCaptions": NSSubmagicCaptions
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSSubmagicCaptions": "NS Submagic Captions"
}
