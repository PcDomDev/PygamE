"""Scene: a collection of GameObjects plus the systems that run them.

Lifecycle hooks - override any of them (call `super()` unless you mean to
replace the default behaviour):

    start()             once, when the scene is loaded by the SceneManager
    update(dt)          every rendered frame (variable dt)
    fixed_update(dt)    every physics step (fixed dt, 60 Hz by default)
    draw(screen)        render the world, then the UI, onto `screen`
    destroy()           when the scene is left: tears down every object

The default `update`/`fixed_update`/`draw` are what run your components, so a
subclass that overrides them and forgets `super()` stops the world.

One frame (`tick(frame_dt)`, called by SceneManager.update):

    accumulate real time -> run 0..N x fixed_update(fixed_dt)  [physics, deterministic]
                         -> update(dt)                          [gameplay, animation, camera]
    then draw(screen) interpolates between the last two physics states.

Scheduling: components run in *global* `update_order` across the whole scene
(see Component), and only components that actually override a hook are
scheduled for it. The scene keeps incremental indexes - by component type, and
by hook/order - updated in O(components of that object) whenever an object is
added, removed, (de)activated or its static flag changes, so spawning a bullet
never rebuilds anything scene-wide.

Adding/removing during a frame is safe: `remove_game_object` and
`GameObject.destroy()` called while the scene is iterating (from an update, a
collision callback, a button click) are applied when that phase ends.
"""
from time import perf_counter

import pygame

from engine.components.component import Component
from engine.core.debug_manager import DebugManager
from engine.core.event_bus import EventBus
from engine.core.game_time import Time
from engine.input.input_manager import Input
from engine.physics.physics_world import PhysicsWorld
from engine.rendering.render_system import RenderSystem
from engine.ui.ui_element import UIElement
from engine.utils.vector2 import Vector2

_HOOK_FLAGS = {}


def _hook_flags(cls):
    """(overrides update, overrides fixed_update, overrides draw_world) - cached per class."""
    flags = _HOOK_FLAGS.get(cls)
    if flags is None:
        flags = (cls.update is not Component.update,
                 cls.fixed_update is not Component.fixed_update,
                 cls.draw_world is not Component.draw_world)
        _HOOK_FLAGS[cls] = flags
    return flags


class Scene:
    def __init__(self, name="Scene"):
        self.name = name
        self.game_objects = []
        self.active_camera = None

        self.physics = PhysicsWorld(self)
        self.render_system = RenderSystem(self)
        # Kept for backwards compatibility: the collider broad-phase.
        self.spatial_hash = self.physics.spatial_hash

        self.draw_calls = 0
        self.view_offset = (0, 0)
        self.is_started = False
        self.is_destroyed = False

        self._by_type = {}          # exact class -> {component: None}   (live components only)
        self._match_cache = {}      # requested type -> [matching exact classes]
        self._update_buckets = {}   # update_order -> {component: None}
        self._fixed_buckets = {}
        self._orders = None         # cached (update_orders, fixed_orders) sorted lists
        self._dispatch_depth = 0
        self._pending_destroy = []
        self._pending_removal = []
        self._accumulator = 0.0

    # -- adding / removing objects ----------------------------------------------------

    def add_game_object(self, game_object):
        """Add `game_object` (and its children) to the scene. Starts it right
        away, so anything you do with it afterwards sees a started object."""
        if game_object.scene is self:
            return game_object
        if game_object._destroyed:
            raise ValueError(f"{game_object!r} was destroyed and can't be added to a scene.")
        if game_object.scene is not None:
            game_object.scene.remove_game_object(game_object)
        self._adopt(game_object)
        return game_object

    def _adopt(self, go):
        go.scene = self
        self.game_objects.append(go)
        go.start()
        if go._effective_active:
            self._register_game_object(go)
        for child in go.transform.children:
            if child.game_object.scene is None:
                self._adopt(child.game_object)

    def remove_game_object(self, game_object):
        """Take the object (and its children) out of the scene without
        destroying it. Deferred to the end of the current phase if called
        mid-update."""
        if game_object.scene is not self:
            return
        if self._dispatch_depth > 0:
            if game_object not in self._pending_removal:
                self._pending_removal.append(game_object)
            return
        self._remove_now(game_object)

    def _remove_now(self, go):
        if go.scene is not self:
            return
        for child in go.transform.children:
            if child.game_object.scene is self:
                self._remove_now(child.game_object)
        self._unregister_game_object(go)
        try:
            self.game_objects.remove(go)
        except ValueError:
            pass
        go.scene = None

    def destroy_game_object(self, game_object):
        """Destroy the object (`on_destroy`, children, event cleanup); deferred
        to the end of the current phase if called mid-update."""
        if game_object._destroyed or game_object._pending_destroy:
            return
        if self._dispatch_depth > 0:
            game_object._pending_destroy = True
            self._pending_destroy.append(game_object)
        else:
            game_object._destroy_now()

    def _flush_pending(self):
        if self._pending_destroy:
            pending, self._pending_destroy = self._pending_destroy, []
            for go in pending:
                go._destroy_now()
        if self._pending_removal:
            pending, self._pending_removal = self._pending_removal, []
            for go in pending:
                self._remove_now(go)

    def find_game_object(self, name):
        for game_object in self.game_objects:
            if game_object.name == name:
                return game_object
        return None

    def find_game_objects_with_tag(self, tag):
        return [go for go in self.game_objects if go.tag == tag]

    @property
    def entity_count(self):
        return len(self.game_objects)

    @property
    def active_entity_count(self):
        return sum(1 for go in self.game_objects if go._effective_active)

    def set_active_camera(self, camera):
        self.active_camera = camera

    # -- component indexes ---------------------------------------------------------------

    def _register_game_object(self, go):
        for component in go.components:
            self._register_component(component)

    def _unregister_game_object(self, go):
        for component in go.components:
            self._unregister_component(component)

    def _register_component(self, component):
        if component._live:
            return
        cls = type(component)
        by_type = self._by_type.get(cls)
        if by_type is None:
            by_type = self._by_type[cls] = {}
            self._match_cache.clear()
        by_type[component] = None

        has_update, has_fixed, has_draw = _hook_flags(cls)
        if (has_update or has_fixed) and component.game_object._effective_static \
                and not component.updates_when_static:
            has_update = has_fixed = False        # static objects skip physics-type components
        order = component.update_order
        if has_update:
            self._bucket_add(self._update_buckets, order, component)
        if has_fixed:
            self._bucket_add(self._fixed_buckets, order, component)
        if has_draw:
            self.render_system.add_drawable(component)

        component._reg = (order, has_update, has_fixed, has_draw)
        component._live = True
        component._on_scene_enter(self)

    def _unregister_component(self, component):
        if not component._live:
            return
        component._on_scene_exit(self)
        component._live = False
        by_type = self._by_type.get(type(component))
        if by_type is not None:
            by_type.pop(component, None)
        order, has_update, has_fixed, has_draw = component._reg
        if has_update:
            self._bucket_remove(self._update_buckets, order, component)
        if has_fixed:
            self._bucket_remove(self._fixed_buckets, order, component)
        if has_draw:
            self.render_system.remove_drawable(component)
        component._reg = None

    def _register_component_if_active(self, component):
        # Called via GameObject.add_component -> scene._register_component directly.
        self._register_component(component)

    def _bucket_add(self, buckets, order, component):
        bucket = buckets.get(order)
        if bucket is None:
            buckets[order] = {component: None}
            self._orders = None
        else:
            bucket[component] = None

    def _bucket_remove(self, buckets, order, component):
        bucket = buckets.get(order)
        if bucket is None:
            return
        bucket.pop(component, None)
        if not bucket:
            del buckets[order]
            self._orders = None

    def _sorted_orders(self):
        if self._orders is None:
            self._orders = (sorted(self._update_buckets), sorted(self._fixed_buckets))
        return self._orders

    def _on_flags_changed(self, go, active_changed, static_changed):
        """A GameObject's effective active/static state changed (its own flag or an ancestor's)."""
        if go._effective_active:
            if active_changed:
                self._register_game_object(go)
            elif static_changed:
                self._unregister_game_object(go)
                self._register_game_object(go)
        elif active_changed:
            self._unregister_game_object(go)

    def get_components(self, component_type):
        """Every live component of `component_type` (subclasses included) on
        an active GameObject - a fresh list, safe to iterate while adding or
        removing objects."""
        classes = self._match_cache.get(component_type)
        if classes is None:
            classes = [cls for cls in self._by_type if issubclass(cls, component_type)]
            self._match_cache[component_type] = classes
        result = []
        for cls in classes:
            result.extend(self._by_type[cls])
        return result

    def get_component(self, component_type):
        """The first live component of that type, or None."""
        for cls in self._match_cache.get(component_type) or [c for c in self._by_type if issubclass(c, component_type)]:
            for component in self._by_type.get(cls, ()):
                return component
        return None

    # -- lifecycle ---------------------------------------------------------------------

    def start(self):
        """Called once when the scene is loaded. Override to build the scene
        (call `super().start()` afterwards, or before - either order works)."""
        self.is_started = True
        for game_object in list(self.game_objects):
            game_object.start()

    def tick(self, frame_dt):
        """Advance one rendered frame of `frame_dt` real seconds: catch physics
        up in fixed steps, then run the variable update. This is what
        `SceneManager.update()` calls - use it directly to simulate a scene
        without a window (tests, tools). Returns how many fixed steps ran."""
        frame_dt = max(0.0, frame_dt)
        scale = Time.time_scale
        physics_dt = min(frame_dt, Time.max_frame_time) * scale
        update_dt = min(frame_dt, Time.max_delta_time) * scale
        Time.unscaled_delta_time = frame_dt
        Time.delta_time = update_dt
        Time.unscaled_time += frame_dt
        Time.time += update_dt

        step = Time.fixed_delta_time
        self._accumulator += physics_dt
        steps = 0
        start = perf_counter()
        while self._accumulator >= step and steps < Time.max_fixed_steps:
            self.fixed_update(step)
            Input.instance().end_fixed_step()
            self._accumulator -= step
            steps += 1
            Time.fixed_time += step
            Time.fixed_frame_count += 1
        if steps >= Time.max_fixed_steps and self._accumulator >= step:
            self._accumulator = 0.0        # we can't catch up: drop the backlog instead of spiralling
        Time.alpha = min(1.0, self._accumulator / step)
        mid = perf_counter()

        self.update(update_dt)
        Time.frame_count += 1

        debug = DebugManager._instance
        if debug is not None:
            debug.record("fixed", (mid - start) * 1000.0)
            debug.record("update", (perf_counter() - mid) * 1000.0)
        return steps

    def update(self, delta_time):
        """Variable-rate update: runs every component's `update`, in global
        `update_order`, then applies deferred destroys/removals."""
        update_orders = self._sorted_orders()[0]
        self._dispatch_depth += 1
        try:
            for order in update_orders:
                bucket = self._update_buckets.get(order)
                if not bucket:
                    continue
                for component in list(bucket):
                    if component._live and component.enabled:
                        component.update(delta_time)
        finally:
            self._dispatch_depth -= 1
        if self._dispatch_depth == 0:
            self._flush_pending()

    def fixed_update(self, fixed_delta_time):
        """One physics step: every component's `fixed_update` (apply forces
        here), then the physics world simulates and dispatches collision/trigger
        callbacks, then deferred destroys/removals are applied."""
        fixed_orders = self._sorted_orders()[1]
        was_fixed = Time.in_fixed_step
        Time.in_fixed_step = True
        self._dispatch_depth += 1
        try:
            for order in fixed_orders:
                bucket = self._fixed_buckets.get(order)
                if not bucket:
                    continue
                for component in list(bucket):
                    if component._live and component.enabled:
                        component.fixed_update(fixed_delta_time)
            self.physics.step(fixed_delta_time)
        finally:
            self._dispatch_depth -= 1
            Time.in_fixed_step = was_fixed
        if self._dispatch_depth == 0:
            self._flush_pending()

    def render(self, screen):
        """Legacy entry point; Engine calls this and it forwards to `draw`."""
        self.draw(screen)

    def draw(self, screen):
        """Draw the world through the camera, then the screen-space UI on top."""
        ox, oy = self._compute_view_offset(screen)
        self.view_offset = (ox, oy)
        self.render_system.draw_world(screen, ox, oy, Time.alpha)
        ui_calls = self._draw_ui(screen)
        self.draw_calls = self.render_system.stats.draw_calls + ui_calls

    def _compute_view_offset(self, screen):
        camera = self.active_camera
        if camera is None:
            return 0, 0
        offset = camera.get_offset(screen.get_width(), screen.get_height())
        return round(offset.x), round(offset.y)

    def _draw_ui(self, screen):
        """UI pass: drawn *after* the world, no camera offset - it's screen-space.
        World-space elements are drawn by the world pass instead."""
        elements = [e for e in self.get_components(UIElement)
                    if e.enabled and e.visible and not e.world_space and e.is_visible]
        if not elements:
            return 0
        elements.sort(key=lambda e: (e.draw_order, e.game_object.transform.depth, e._seq))
        for element in elements:
            element.draw(screen)
        return len(elements)

    def screen_to_world(self, screen_pos):
        """A screen-pixel position (tuple or Vector2) in world coordinates."""
        surface = pygame.display.get_surface()
        ox, oy = self._compute_view_offset(surface) if surface is not None else self.view_offset
        return Vector2(screen_pos[0] + ox, screen_pos[1] + oy) if not hasattr(screen_pos, "x") \
            else Vector2(screen_pos.x + ox, screen_pos.y + oy)

    def world_to_screen(self, world_pos):
        surface = pygame.display.get_surface()
        ox, oy = self._compute_view_offset(surface) if surface is not None else self.view_offset
        wx, wy = (world_pos.x, world_pos.y) if hasattr(world_pos, "x") else world_pos
        return Vector2(wx - ox, wy - oy)

    def destroy(self):
        """Tear the scene down: destroys every object (running `on_destroy`),
        drops event subscriptions made with `owner=scene`, and clears the
        physics/render structures so nothing keeps the scene alive."""
        if self.is_destroyed:
            return
        self.is_destroyed = True
        self._dispatch_depth = 0
        for game_object in list(self.game_objects):
            if game_object.scene is self:
                game_object._destroy_now()
        self.game_objects.clear()
        self._pending_destroy.clear()
        self._pending_removal.clear()
        self.physics.clear()
        self.render_system.clear()
        self._by_type.clear()
        self._match_cache.clear()
        self._update_buckets.clear()
        self._fixed_buckets.clear()
        self._orders = None
        self.active_camera = None
        EventBus.unsubscribe_owner(self)
