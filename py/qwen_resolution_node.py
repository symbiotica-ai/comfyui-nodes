import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont


def pil2tensor(image):
    """Convert PIL image to tensor in the correct format"""
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)


class NSQwenResolution:
    """
    A node for selecting Qwen model resolutions with visual preview.

    Class methods
    -------------
    INPUT_TYPES (dict):
        Defines the resolution selection input.

    Attributes
    ----------
    RETURN_TYPES (`tuple`):
        Returns width (INT), height (INT), resolution string (STRING), and preview image (IMAGE).
    RETURN_NAMES (`tuple`):
        Names for the outputs: width, height, resolution, preview.
    FUNCTION (`str`):
        Entry-point method name: "get_dimensions".
    OUTPUT_NODE (`bool`):
        True - this node outputs a preview image.
    CATEGORY (`str`):
        UI category: "ControlAltAI Nodes/Qwen".

    get_dimensions(resolution) -> tuple:
        Returns the width, height, resolution string, and preview image for the selected resolution.
    """

    @classmethod
    def INPUT_TYPES(cls):
        """
        Return a dictionary which contains config for all input fields.

        Returns: `dict`:
            - Key "required": Contains required input fields config
            - Value "resolution": A list selection of available resolutions
        """
        return {
            "required": {
                "resolution": (
                    [
                        "1:1 (Square)",
                        "16:9 (Widescreen Landscape)",
                        "9:16 (Widescreen Portrait)",
                        "4:3 (Standard Landscape)",
                        "3:4 (Standard Portrait)",
                        "3:2 (Classic Landscape)",
                        "2:3 (Classic Portrait)",
                    ],
                    {"default": "1:1 (Square)"},
                ),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING", "IMAGE")
    RETURN_NAMES = ("width", "height", "resolution", "preview")
    FUNCTION = "get_dimensions"
    CATEGORY = "neuralsins/Utils"
    OUTPUT_NODE = True

    def create_preview_image(self, width, height, resolution):
        # 1024x1024 preview size
        preview_size = (1024, 1024)
        image = Image.new("RGB", preview_size, (0, 0, 0))  # Black background
        draw = ImageDraw.Draw(image)

        # Draw grid with grey lines
        grid_color = "#333333"  # Dark grey for grid
        grid_spacing = 50  # Adjusted grid spacing
        for x in range(0, preview_size[0], grid_spacing):
            draw.line([(x, 0), (x, preview_size[1])], fill=grid_color)
        for y in range(0, preview_size[1], grid_spacing):
            draw.line([(0, y), (preview_size[0], y)], fill=grid_color)

        # Calculate preview box dimensions
        preview_width = 800  # Increased size
        preview_height = int(preview_width * (height / width))

        # Adjust if height is too tall
        if preview_height > 800:  # Adjusted for larger preview
            preview_height = 800
            preview_width = int(preview_height * (width / height))

        # Calculate center position
        x_offset = (preview_size[0] - preview_width) // 2
        y_offset = (preview_size[1] - preview_height) // 2

        # Draw the aspect ratio box with thicker outline
        draw.rectangle(
            [
                (x_offset, y_offset),
                (x_offset + preview_width, y_offset + preview_height),
            ],
            outline="red",
            width=4,  # Thicker outline
        )

        # Add text with larger font sizes
        try:
            # Draw text (centered)
            text_y = y_offset + preview_height // 2

            # Resolution text in red
            draw.text(
                (preview_size[0] // 2, text_y),
                f"{width}x{height}",
                fill="red",
                anchor="mm",
                font=ImageFont.truetype("arial.ttf", 48),
            )

        except:
            # Fallback if font loading fails
            draw.text(
                (preview_size[0] // 2, text_y),
                f"{width}x{height}",
                fill="red",
                anchor="mm",
            )

        # Convert to tensor using the helper function
        return pil2tensor(image)

    def get_dimensions(self, resolution):
        # Map from aspect ratio to actual dimensions
        resolution_map = {
            "1:1 (Square)": (1328, 1328),
            "16:9 (Widescreen Landscape)": (1664, 928),
            "9:16 (Widescreen Portrait)": (928, 1664),
            "4:3 (Standard Landscape)": (1472, 1104),
            "3:4 (Standard Portrait)": (1104, 1472),
            "3:2 (Classic Landscape)": (1584, 1056),
            "2:3 (Classic Portrait)": (1056, 1584),
        }

        # Get dimensions from the map
        width, height = resolution_map[resolution]

        # Resolution as string
        resolution_str = f"{width} x {height}"

        # Generate preview image
        preview = self.create_preview_image(width, height, resolution_str)

        return width, height, resolution_str, preview


def gcd(a, b):
    """Calculate the Greatest Common Divisor of a and b."""
    while b:
        a, b = b, a % b
    return a


NODE_CLASS_MAPPINGS = {
    "NSQwenResolution": NSQwenResolution,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSQwenResolution": "NS Qwen Resolution",
}
