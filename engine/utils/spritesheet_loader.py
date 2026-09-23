"""Loads a sprite sheet image plus its accompanying JSON atlas (e.g.
exported by TexturePacker or similar tools) directly into the
`{name: [surface, ...]}` shape `Animator` expects:

    from engine.utils.spritesheet_loader import load_spritesheet_animations
    from engine.components.animator import Animator

    animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
    hero.add_component(Animator(animations=animations, default_animation="idle"))

Supports both common JSON atlas shapes:
  - "hash": `{"frames": {"walk_00.png": {"frame": {"x":.., "y":.., "w":.., "h":..}}, ...}}`
  - "array": `{"frames": [{"filename": "walk_00.png", "frame": {...}}, ...]}`

Frames are grouped into animations by name and re-ordered by their frame
number - not by whatever order they happen to appear in the JSON, since a
plain alphabetical/insertion order sorts "walk_10" before "walk_2" and
would silently scramble the animation. See `_animation_name_and_index`
for exactly how a filename like "walk_01.png" splits into
`("walk", 1)`.
"""
import json
import os
import re

import pygame

from engine.core.debug_manager import DebugManager

_TRAILING_FRAME_NUMBER = re.compile(r"[\s_-]*(\d+)$")


def _animation_name_and_index(frame_name):
    """"walk_01.png" -> ("walk", 1). Strips the extension, then treats a
    trailing run of digits (with an optional separator before it) as the
    frame index - the remainder, lowercased, is the animation name. A
    name with no trailing number (e.g. a single-frame "idle.png") gets
    index 0, so it still works and sorts first.
    """
    stem = os.path.splitext(frame_name)[0]
    match = _TRAILING_FRAME_NUMBER.search(stem)
    if match:
        name = stem[:match.start()]
        index = int(match.group(1))
    else:
        name = stem
        index = 0
    return name.lower(), index


def _iter_frames(data):
    """Yields (frame_name, frame_rect_dict) for either JSON atlas shape."""
    frames = data.get("frames")
    if frames is None:
        raise ValueError("Spritesheet JSON has no top-level 'frames' key.")

    if isinstance(frames, dict):
        for frame_name, frame_info in frames.items():
            yield frame_name, frame_info["frame"]
    elif isinstance(frames, list):
        for frame_info in frames:
            yield frame_info["filename"], frame_info["frame"]
    else:
        raise ValueError("Spritesheet JSON's 'frames' must be a JSON object or array.")


def load_spritesheet_animations(json_path, image_path, generate_flipped=True):
    """Returns `{animation_name: [pygame.Surface, ...]}`?, each list
    ordered by frame number, ready to hand straight to
    `Animator(animations=...)`.

    If `generate_flipped=True`, also generates horizontally flipped versions of all
    animations prefixed with an underscore (e.g. 'idle' -> '_idle').

    Paths are used exactly as given (relative to the current working
    directory, or absolute) - the same convention `pygame.image.load`
    itself uses, and the rest of this engine's asset loading. Unrecoverable
    problems (missing file, malformed JSON, unrecognized atlas shape) are
    logged via DebugManager with which path/step failed, then re-raised -
    a missing asset is a setup mistake worth seeing immediately, not
    something to silently continue past with half a spritesheet loaded.
    """
    try:
        sheet = pygame.image.load(image_path).convert_alpha()
    except (pygame.error, FileNotFoundError) as exc:
        DebugManager.log_error(f"load_spritesheet_animations: couldn't load image '{image_path}': {exc!r}")
        raise

    try:
        with open(json_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        DebugManager.log_error(f"load_spritesheet_animations: couldn't read JSON '{json_path}': {exc!r}")
        raise

    # Collect (index, surface) per animation name first, so each
    # animation's frame list can be sorted by number afterward regardless
    # of the JSON's own frame order.
    pending = {}
    try:
        for frame_name, rect in _iter_frames(data):
            anim_name, index = _animation_name_and_index(frame_name)
            x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
            surface = sheet.subsurface(pygame.Rect(x, y, w, h))
            pending.setdefault(anim_name, []).append((index, surface))

            if generate_flipped:
                flipped_anim_name = f"_{anim_name}"
                flipped_surface = pygame.transform.flip(surface, True, False)
                pending.setdefault(flipped_anim_name, []).append((index, flipped_surface))
    except (KeyError, TypeError) as exc:
        DebugManager.log_error(f"load_spritesheet_animations: unexpected frame shape in '{json_path}': {exc!r}")
        raise ValueError(f"Malformed frame entry in '{json_path}'") from exc

    animations = {}
    for anim_name, frames in pending.items():
        frames.sort(key=lambda pair: pair[0])
        animations[anim_name] = [surface for _, surface in frames]

    return animations