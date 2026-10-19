"""NetworkIdentity: marks a GameObject as networked. Every peer holding a
copy of this object agrees on its `network_id`, and exactly one player -
`owner_id` - is authoritative for it (see NetworkTransform for what
"authoritative" means in practice: who runs real physics, who just glides
toward received updates).

Never construct this directly - it's attached automatically by
NetworkManager.spawn() (and by NetworkManager when a "spawn" message arrives
from the host), which is also what assigns `network_id` a value every peer
agrees on. Building one yourself would give it a network_id nobody else
recognizes.
"""
from engine.components.component import Component


class NetworkIdentity(Component):
    updates_when_static = False

    def __init__(self, network_id, owner_id, prefab_name, spawn_kwargs=None):
        super().__init__()
        self.network_id = network_id
        self.owner_id = owner_id
        self.prefab_name = prefab_name
        # The keyword arguments this object was spawned with. Kept so the host can
        # rebuild an identical copy for a player who joins later (see NetworkManager).
        self.spawn_kwargs = spawn_kwargs if spawn_kwargs is not None else {}
        self._scene_teardown = False

    @property
    def is_owner(self):
        """True if the local player is the one authoritative for this
        object - the one whose NetworkTransform runs real physics and
        broadcasts position, rather than receiving and smoothing it."""
        from engine.networking.network_manager import NetworkManager
        return NetworkManager.local_player_id == self.owner_id

    # Some people think in terms of "do I own this" rather than "am I the
    # owner" - both read naturally depending on the call site, so both exist.
    is_mine = is_owner

    def _on_scene_exit(self, scene):
        # Remember whether this object left its scene because the whole scene was
        # torn down (a level change) rather than because someone destroyed it
        # directly - NetworkManager treats the two differently on a client.
        self._scene_teardown = bool(scene.is_destroyed)

    def on_destroy(self):
        from engine.networking.network_manager import NetworkManager
        NetworkManager._on_networked_object_destroyed(self)

    def __repr__(self):
        return (f"NetworkIdentity(network_id={self.network_id}, owner_id={self.owner_id}, "
               f"prefab={self.prefab_name!r})")
