"""Publish/subscribe events - one global bus plus per-entity buses.

    EventBus.subscribe("game_over", on_game_over)
    EventBus.emit("game_over", score=120)          # -> on_game_over(score=120)

    player.events.subscribe("jumps_changed", hud.update_jumps)   # entity-scoped
    player.events.emit("jumps_changed", remaining=1)

`EventBus` is the global, static-style facade; `EventDispatcher` is the
instance type behind it and behind every `GameObject.events`. Entity-scoped
events never reach global listeners and vice versa, so two enemies can both
emit "died" without their listeners hearing each other.

Leak protection (the classic pub/sub bug): a global subscription keeps its
callback - and everything the callback references - alive forever. Three tools:

  - `owner=`: tag subscriptions with a Scene/GameObject/Component;
    `unsubscribe_owner(owner)` drops them all at once (Scene.destroy() and
    GameObject destruction do this for you).
  - `weak=True`: hold bound methods weakly, so a destroyed listener is
    collected and pruned automatically.
  - `once=True`: fire once, then unsubscribe.

A handler that raises is logged through DebugManager and the remaining
handlers still run - one bad listener can't break the emitter.
"""
import weakref

from engine.core.debug_manager import DebugManager


class Subscription:
    """Handle returned by subscribe(); call `cancel()` to unsubscribe."""

    __slots__ = ("event", "_ref", "_weak", "owner_id", "once", "priority", "active", "_dispatcher")

    def __init__(self, dispatcher, event, callback, owner, once, priority, weak):
        self._dispatcher = dispatcher
        self.event = event
        self.owner_id = id(owner) if owner is not None else None
        self.once = once
        self.priority = priority
        self.active = True
        self._weak = weak
        if weak:
            if getattr(callback, "__self__", None) is not None:
                self._ref = weakref.WeakMethod(callback)
            else:
                self._ref = weakref.ref(callback)
        else:
            self._ref = callback

    @property
    def callback(self):
        return self._ref() if self._weak else self._ref

    def cancel(self):
        self._dispatcher._remove(self)


class EventDispatcher:
    """A self-contained event bus. `EventBus` wraps one of these globally."""

    def __init__(self, name="events"):
        self.name = name
        self._listeners = {}   # event -> [Subscription], highest priority first

    # -- subscribing ---------------------------------------------------------------

    def subscribe(self, event, callback, *, owner=None, once=False, priority=0, weak=False):
        if not callable(callback):
            raise TypeError(f"EventBus.subscribe: callback for {event!r} is not callable")
        sub = Subscription(self, event, callback, owner, once, priority, weak)
        subs = self._listeners.setdefault(event, [])
        # Keep the list ordered by priority (high first); equal priorities stay
        # in subscription order, so emit order is deterministic.
        index = len(subs)
        while index > 0 and subs[index - 1].priority < priority:
            index -= 1
        subs.insert(index, sub)
        return sub

    def once(self, event, callback, **kwargs):
        return self.subscribe(event, callback, once=True, **kwargs)

    def unsubscribe(self, event, callback):
        """Remove every subscription of `callback` to `event`. Returns how many."""
        removed = 0
        for sub in list(self._listeners.get(event, ())):
            cb = sub.callback
            if cb == callback:
                self._remove(sub)
                removed += 1
        return removed

    def unsubscribe_owner(self, owner):
        """Remove every subscription that was registered with `owner=owner`."""
        owner_id = id(owner)
        removed = 0
        for subs in list(self._listeners.values()):
            for sub in list(subs):
                if sub.owner_id == owner_id:
                    self._remove(sub)
                    removed += 1
        return removed

    def _remove(self, sub):
        sub.active = False
        subs = self._listeners.get(sub.event)
        if subs is None:
            return
        try:
            subs.remove(sub)
        except ValueError:
            pass
        if not subs:
            self._listeners.pop(sub.event, None)

    def clear(self, event=None):
        if event is None:
            for subs in self._listeners.values():
                for sub in subs:
                    sub.active = False
            self._listeners.clear()
        else:
            for sub in self._listeners.pop(event, ()):
                sub.active = False

    # -- emitting ---------------------------------------------------------------

    def emit(self, event, *args, **kwargs):
        """Call every handler of `event`; returns how many handlers ran."""
        subs = self._listeners.get(event)
        if not subs:
            return 0
        called = 0
        for sub in tuple(subs):          # snapshot: handlers may (un)subscribe
            if not sub.active:
                continue
            callback = sub.callback
            if callback is None:         # weakly-held listener was collected
                self._remove(sub)
                continue
            if sub.once:
                self._remove(sub)
            try:
                callback(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - one bad listener must not break the emitter
                DebugManager.log_error(f"EventBus '{self.name}': handler for {event!r} raised {exc!r}")
            called += 1
        return called

    # -- introspection ----------------------------------------------------------

    def has_listeners(self, event):
        return bool(self._listeners.get(event))

    def listener_count(self, event=None):
        if event is not None:
            return len(self._listeners.get(event, ()))
        return sum(len(s) for s in self._listeners.values())


class EventBus:
    """The global bus - static-style access from anywhere (no reference needed)."""

    _dispatcher = EventDispatcher("global")

    @classmethod
    def subscribe(cls, event, callback, **kwargs):
        return cls._dispatcher.subscribe(event, callback, **kwargs)

    @classmethod
    def once(cls, event, callback, **kwargs):
        return cls._dispatcher.once(event, callback, **kwargs)

    @classmethod
    def unsubscribe(cls, event, callback):
        return cls._dispatcher.unsubscribe(event, callback)

    @classmethod
    def unsubscribe_owner(cls, owner):
        return cls._dispatcher.unsubscribe_owner(owner)

    @classmethod
    def emit(cls, event, *args, **kwargs):
        return cls._dispatcher.emit(event, *args, **kwargs)

    @classmethod
    def has_listeners(cls, event):
        return cls._dispatcher.has_listeners(event)

    @classmethod
    def listener_count(cls, event=None):
        return cls._dispatcher.listener_count(event)

    @classmethod
    def clear(cls, event=None):
        cls._dispatcher.clear(event)
