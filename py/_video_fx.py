# ABOUTME: Shared video-effect harness — ffprobe geometry, raw RGB decode/encode pipes
# ABOUTME: and a per-frame driver. No ComfyUI imports, so effects test flat and fast.

import json
import subprocess

import numpy as np

try:
    from ._bins import FFMPEG, FFPROBE
except ImportError:  # flat import under pytest (conftest puts py/ itself on sys.path)
    from _bins import FFMPEG, FFPROBE

# x264 quality of the re-encode. Fixed rather than exposed: 17 is visually
# transparent on generated footage and there is no reason to make the operator
# think about it.
DEFAULT_CRF = 17

# Colour metadata read off the source and written back onto the output. Decoding
# to RGB and re-encoding without re-tagging is how a clip comes back with a
# colour shift, and it is the kind of shift nobody notices until grading.
_COLOR_FLAGS = (
    ("-color_range", "color_range"),
    ("-colorspace", "color_space"),
    ("-color_primaries", "color_primaries"),
    ("-color_trc", "color_transfer"),
)


def probe(path):
    """Read the geometry, frame rate, frame count, audio presence and colour tags."""
    result = subprocess.run(
        [FFPROBE, "-v", "error",
         "-show_entries",
         "stream=index,codec_type,width,height,r_frame_rate,nb_frames,"
         "color_range,color_space,color_primaries,color_transfer",
         "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr[-800:]}")
    data = json.loads(result.stdout)

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("input has no video stream")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    num, den = video["r_frame_rate"].split("/")
    # ffprobe reports 0/0 for a stream whose rate it cannot work out; dividing
    # straight through turns that into a ZeroDivisionError three frames later
    # instead of the message that says which file is unusable.
    fps = float(num) / float(den) if float(den) else 0.0
    if fps <= 0:
        raise RuntimeError(f"invalid frame rate: {video['r_frame_rate']}")

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    try:
        n_frames = int(video.get("nb_frames") or 0)
    except (TypeError, ValueError):
        n_frames = 0
    if n_frames <= 0:
        n_frames = int(round(duration * fps))

    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "fps_str": video["r_frame_rate"],
        # An estimate for some containers — treat it as a hint for planning,
        # never as the loop bound. process() runs until the decoder stops.
        "n_frames": max(n_frames, 1),
        "has_audio": has_audio,
        "color_range": video.get("color_range"),
        "color_space": video.get("color_space"),
        "color_primaries": video.get("color_primaries"),
        "color_transfer": video.get("color_transfer"),
    }


def decoder_cmd(path):
    """Argument list for the decode pipe. Split out so it can be asserted on."""
    return [FFMPEG, "-v", "error", "-nostdin", "-i", path,
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def decoder(path):
    """ffmpeg decoding `path` to raw rgb24 frames on stdout."""
    return subprocess.Popen(
        decoder_cmd(path), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def encoder_cmd(info, source_path, output_path, crf):
    """Argument list for the encode pipe. Split out so it can be asserted on."""
    cmd = [
        FFMPEG, "-y", "-v", "error", "-nostdin",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{info['width']}x{info['height']}",
        "-r", info["fps_str"],
        "-i", "pipe:0",
    ]
    # Second input supplies the original audio; the effect is video-only.
    cmd += ["-i", source_path]
    cmd += ["-map", "0:v:0"]
    if info["has_audio"]:
        # No -shortest: the audio track can round a hair under the video
        # length, and -shortest would drop the final frame to match it.
        cmd += ["-map", "1:a:0", "-c:a", "copy"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
    ]
    for flag, key in _COLOR_FLAGS:
        value = info.get(key)
        if value and value != "unknown":
            cmd += [flag, value]
    cmd += ["-movflags", "+faststart", output_path]
    return cmd


def encoder(info, source_path, output_path, crf=DEFAULT_CRF):
    """ffmpeg taking raw rgb24 frames on stdin, writing `output_path`."""
    return subprocess.Popen(
        encoder_cmd(info, source_path, output_path, crf),
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def process(source_path, output_path, fn, crf=DEFAULT_CRF):
    """Run `fn` over every frame of the video and write the result.

    `fn(frame, index, info)` receives a writable (H, W, 3) uint8 RGB array, the
    0-based frame index and the probe dict, and returns an array of the same
    shape and dtype. Returns the number of frames written.

    One frame is in flight at a time, so a long 4K clip costs no more memory
    than a thumbnail.
    """
    info = probe(source_path)
    width, height = info["width"], info["height"]
    frame_bytes = width * height * 3

    dec = decoder(source_path)
    enc = encoder(info, source_path, output_path, crf)

    n = 0
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            # Copied because a frombuffer view over immutable bytes is
            # read-only, and writing into the frame in place is the obvious
            # thing for an effect to do.
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3).copy()
            out = fn(frame, n, info)
            if (not isinstance(out, np.ndarray) or out.shape != frame.shape
                    or out.dtype != np.uint8):
                # Caught here rather than let through: a wrong dtype writes the
                # wrong number of bytes, which silently shears every frame from
                # this one on instead of failing.
                raise ValueError(
                    f"effect returned {type(out).__name__} "
                    f"{getattr(out, 'shape', '')}{getattr(out, 'dtype', '')} "
                    f"for frame {n}; expected a uint8 {frame.shape} array")
            enc.stdin.write(out.tobytes())
            n += 1
    except BrokenPipeError:
        enc_err = enc.stderr.read().decode("utf-8", "replace")
        raise RuntimeError(f"ffmpeg encoder died:\n{enc_err[-1000:]}")
    finally:
        # Both pipes close before either stderr is read. Leaving the clip early
        # — a refused frame, an encoder that died — leaves the decoder blocked
        # writing frames nobody is draining, and reading its stderr first would
        # then wait forever on a process that is itself waiting on us.
        for pipe in (enc.stdin, dec.stdout):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass
        dec_err = dec.stderr.read().decode("utf-8", "replace")
        dec.wait()
        enc_err = enc.stderr.read().decode("utf-8", "replace")
        enc.wait()

    if dec.returncode not in (0, None):
        raise RuntimeError(f"ffmpeg decode failed:\n{dec_err[-1000:]}")
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed:\n{enc_err[-1000:]}")
    if n == 0:
        raise RuntimeError("no frames were decoded from the input video")
    return n
