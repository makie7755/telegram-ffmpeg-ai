import json
import subprocess
from pathlib import Path

ALLOWED_RESOLUTIONS = {(1280, 720), (1920, 1080), (3840, 2160)}

def run(args):
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

def probe_video(path: str) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", path
        ],
        check=True, capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    return {"duration": round(float(data["format"]["duration"]), 2)}

def validate_time(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("Time must use HH:MM:SS.")
    h, m, s = map(int, parts)
    if m > 59 or s > 59:
        raise ValueError("Invalid time.")
    return f"{h:02d}:{m:02d}:{s:02d}"

def render_video(input_path: str, output_path: str, operations: list):
    current_input = input_path
    temp_paths = []
    try:
        for index, operation in enumerate(operations):
            op = operation.get("op")
            final_step = index == len(operations) - 1
            target = output_path if final_step else str(
                Path(output_path).with_name(f"step_{index}.mp4")
            )
            temp_paths.append(target)

            if op == "trim":
                start = validate_time(str(operation["start"]))
                duration = validate_time(str(operation["duration"]))
                args = ["ffmpeg", "-y", "-i", current_input, "-ss", start,
                        "-t", duration, "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "23", "-c:a", "aac", target]
            elif op == "resize":
                width, height = int(operation["width"]), int(operation["height"])
                if (width, height) not in ALLOWED_RESOLUTIONS:
                    raise ValueError("Unsupported resolution.")
                args = ["ffmpeg", "-y", "-i", current_input, "-vf",
                        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-c:a", "aac", target]
            elif op == "compress":
                crf = int(operation.get("crf", 23))
                if not 18 <= crf <= 30:
                    raise ValueError("CRF must be between 18 and 30.")
                args = ["ffmpeg", "-y", "-i", current_input, "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", str(crf), "-c:a", "aac",
                        "-b:a", "128k", target]
            elif op == "convert":
                fmt = operation.get("format")
                if fmt not in {"mp4", "mkv"}:
                    raise ValueError("Unsupported output format.")
                target = str(Path(output_path).with_suffix("." + fmt)) if final_step else target
                if final_step:
                    temp_paths[-1] = target
                args = ["ffmpeg", "-y", "-i", current_input, "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "23", "-c:a", "aac", target]
            else:
                raise ValueError(f"Unsupported operation: {op}")

            run(args)
            current_input = target

        if not operations:
            raise ValueError("No editing operations supplied.")
        return current_input
    finally:
        for path in temp_paths:
            if path != output_path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
