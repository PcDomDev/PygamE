"""Shared anchor math, used by SpriteRenderer and BoxCollider2D so both
interpret an anchor name (e.g. "center", "bottomleft") identically. This
used to be duplicated logic living only inside BoxCollider2D - which meant
a sprite and its own collider could disagree about where "center" or
"bottomleft" actually is, since the sprite renderer had no anchor concept
at all and always drew from the raw transform position as a top-left
corner. Having one function both call eliminates that class of mismatch
entirely, rather than requiring two independent implementations to agree.
"""
import pygame

VALID_ANCHORS = {
    "topleft", "midtop", "topright",
    "midleft", "center", "midright",
    "bottomleft", "midbottom", "bottomright",
}


def anchor_to_topleft_offset(anchor, width, height):
    """(dx, dy) such that top_left = anchor_point + (dx, dy), for the given
    anchor name and size.

    Computed via a throwaway pygame.Rect at the origin. Since width/height
    are always integers, this is exact for the 4 corner anchors and for
    the 4 edge-midpoint anchors, and correct to within pygame's own
    integer-division rounding for "center" on an odd-sized dimension -
    the same precision pygame's anchors have everywhere else, no worse.
    """
    probe = pygame.Rect(0, 0, width, height)
    setattr(probe, anchor, (0, 0))
    return probe.left, probe.top


# --- Screen-space anchors (UI) ---------------------------------------------------
# The same nine names, as (x, y) fractions of a rectangle - what the UI system
# needs to place an element relative to the screen or to its parent panel.

ANCHOR_FRACTIONS = {
    "topleft": (0.0, 0.0), "midtop": (0.5, 0.0), "topright": (1.0, 0.0),
    "midleft": (0.0, 0.5), "center": (0.5, 0.5), "midright": (1.0, 0.5),
    "bottomleft": (0.0, 1.0), "midbottom": (0.5, 1.0), "bottomright": (1.0, 1.0),
}

_ANCHOR_ALIASES = {
    "topcenter": "midtop", "top": "midtop", "centertop": "midtop",
    "middleleft": "midleft", "left": "midleft", "centerleft": "midleft", "leftcenter": "midleft",
    "middle": "center", "middlecenter": "center", "centermiddle": "center",
    "middleright": "midright", "right": "midright", "centerright": "midright", "rightcenter": "midright",
    "bottomcenter": "midbottom", "bottom": "midbottom", "centerbottom": "midbottom",
}


def normalize_anchor(name):
    """Accepts "TopLeft", "top_left", "topleft", "Center", "BottomRight", ... and
    returns the canonical name used by ANCHOR_FRACTIONS (raises ValueError if unknown)."""
    key = str(name).lower().replace("_", "").replace("-", "").replace(" ", "")
    key = _ANCHOR_ALIASES.get(key, key)
    if key not in ANCHOR_FRACTIONS:
        raise ValueError(f"Unknown anchor {name!r}. Use one of: TopLeft, TopCenter, TopRight, "
                         f"MiddleLeft, Center, MiddleRight, BottomLeft, BottomCenter, BottomRight.")
    return key
