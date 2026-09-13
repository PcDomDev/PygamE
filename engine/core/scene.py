import pygame

from engine.components.collider2d import Collider2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.spatial_hash import SpatialHash
from engine.ui.ui_element import UIElement
from engine.utils.vector2 import Vector2


class Scene:
    """A collection of GameObjects, plus the logic to update, collide, and
    render them. This is engine machinery - what a scene *contains* (a
    controllable character, a platform, a menu, ...) is not engine code.

    Performance: Scene keeps two indexes so hot-path lookups don't degrade
    as object count grows - see docs/README's Performance section:

      - A component-type cache (`_component_cache`), so `get_components()`
        doesn't re-scan every GameObject on every call. Invalidated
        (cheaply - just a dirty flag) whenever a component or GameObject
        is added/removed, or a GameObject's `active` flag changes.
      - `spatial_hash`, a uniform grid colliders register themselves into
        as they move, so collision/trigger broad-phase only has to look at
        nearby colliders instead of the whole scene.
    """

    def __init__(self, name="Scene"):
        self.name = name
        self.game_objects = []
        self.active_camera = None
        self.spatial_hash = SpatialHash()

        self._component_cache = {}   # exact type -> list[Component]
        self._cache_dirty = True

    # -- object management --------------------------------------------------------

    def add_game_object(self, game_object):
        game_object.scene = self
        self.game_objects.append(game_object)
        game_object.start()
        self._invalidate_component_cache()
        return game_object

    def remove_game_object(self, game_object):
        if game_object not in self.game_objects:
            return
        self.game_objects.remove(game_object)
        for collider in game_object.get_components(Collider2D):
            self.spatial_hash.remove(collider)
        self._invalidate_component_cache()

    def find_game_object(self, name):
        """First GameObject with a matching `.name`, or None."""
        for go in self.game_objects:
            if go.name == name:
                return go
        return None

    def set_active_camera(self, camera):
        self.active_camera = camera

    # -- component cache ------------------------------------------------------------

    def _invalidate_component_cache(self):
        self._cache_dirty = True

    def _on_active_changed(self, game_object):
        """Called by GameObject.active's setter. Keeps the component cache
        and spatial hash consistent with which objects currently count as
        active, without polling every object every frame to notice."""
        self._invalidate_component_cache()
        for collider in game_object.get_components(Collider2D):
            if game_object.active:
                self.spatial_hash.update(collider)
            else:
                self.spatial_hash.remove(collider)

    def _rebuild_component_cache(self):
        cache = {}
        for go in self.game_objects:
            if go.active:
                for component in go.components:
                    cache.setdefault(type(component), []).append(component)
        self._component_cache = cache
        self._cache_dirty = False

    def get_components(self, component_type):
        """Every component of `component_type` (or a subclass of it) on
        every *active* GameObject.

        Indexed by each component's exact class, so this costs roughly
        O(distinct component classes in the scene) rather than O(total
        GameObjects) - a scene with a thousand objects that all use the
        same handful of component classes is just as fast to query as one
        with ten.
        """
        if self._cache_dirty:
            self._rebuild_component_cache()

        result = []
        for cls, components in self._component_cache.items():
            if issubclass(cls, component_type):
                result.extend(components)
        return result

    # -- lifecycle --------------------------------------------------------------

    def start(self):
        for go in self.game_objects:
            go.start()

    def update(self, delta_time):
        for go in list(self.game_objects):
            if go.active:
                go.update(delta_time)

        self._process_triggers()

    def _process_triggers(self):
        for trigger in self.get_components(Collider2D):
            if not trigger.is_trigger:
                continue

            # Broad-phase candidates near the trigger right now, PLUS
            # anything it was already overlapping as of last frame - the
            # union guarantees on_trigger_exit still fires even if an
            # object moved far enough in one frame to leave the trigger's
            # spatial-hash neighborhood entirely (e.g. a teleport), which
            # a broad-phase-only query could otherwise miss.
            candidates = self.spatial_hash.query(trigger.rect) | trigger.overlapping_colliders
            for other in candidates:
                if trigger is not other and other.game_object.active:
                    trigger.check_trigger_events(other)

    # -- rendering --------------------------------------------------------------

    def render(self, screen):
        self._render_world(screen)
        self._render_ui(screen)

    def _render_world(self, screen):
        offset = Vector2(0.0, 0.0)
        if self.active_camera is not None:
            offset = self.active_camera.get_offset(screen.get_width(), screen.get_height())

        screen_rect = screen.get_rect()

        renderers = [r for r in self.get_components(SpriteRenderer) if r.enabled and r.sprite]
        renderers.sort(key=lambda r: (r.z_index, r.game_object.transform.position.y + r.offset_y))

        for r in renderers:
            transform = r.game_object.transform
            original_w, original_h = r.sprite.get_size()
            anchor_dx, anchor_dy = r.get_anchor_offset()

            # Center of the ORIGINAL (pre-rotation/scale) sprite, honoring
            # its anchor - this is the fixed point rotation/scaling
            # pivots around, and (with the default anchor="topleft") is
            # exactly where the old, anchor-less renderer always drew from.
            center = Vector2(
                transform.position.x + anchor_dx + original_w / 2.0,
                transform.position.y + anchor_dy + original_h / 2.0,
            ) - offset

            half_w, half_h = original_w / 2.0, original_h / 2.0
            # Viewport culling: skip anything whose (un-rotated) bounding
            # box doesn't reach the screen at all. Uses the pre-transform
            # half-extents, which slightly over-covers a rotated sprite's
            # true (larger) bounding box - a deliberately generous margin,
            # since culling a sprite that's actually still partially
            # visible would be a visible bug, while drawing a few extra
            # pixels of margin costs nothing.
            if (center.x + half_w < screen_rect.left or center.x - half_w > screen_rect.right or
                    center.y + half_h < screen_rect.top or center.y - half_h > screen_rect.bottom):
                continue

            sprite = r.get_transformed_sprite(transform.rotation, transform.scale.x, transform.scale.y)
            if sprite is None:
                continue

            new_w, new_h = sprite.get_size()
            draw_pos = Vector2(center.x - new_w / 2.0, center.y - new_h / 2.0)
            screen.blit(sprite, (round(draw_pos.x), round(draw_pos.y)))

    def _render_ui(self, screen):
        """UI draws last, directly in screen space - never offset by the
        camera, always on top of the world."""
        elements = [e for e in self.get_components(UIElement) if e.visible]
        elements.sort(key=lambda e: e.draw_order)
        for element in elements:
            element.draw(screen)
