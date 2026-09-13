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
