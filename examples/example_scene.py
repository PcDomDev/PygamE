from engine.components.player_controller import PlayerController
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.primitives import create_circle, create_rectangle, create_square
from engine.core.scene import Scene
from engine.ui.ui_button import UIButton
from engine.ui.ui_panel import UIPanel
from engine.ui.ui_text import UIText
from examples.scripts.jumps_hud import JumpsHUD
from examples.scripts.reset_on_click import ResetOnClick


def build_example_scene():
    """Builds the demo scene: a controllable character (double-jump
    enabled), a platform to stand on, a purely decorative circle, and a
    small UI HUD (a jump counter + a reset button).

    This is ordinary game content, not engine code - it's built entirely
    from engine.primitives rather than external image assets, so there
    are no sprite files this project depends on. Add more functions like
    this one for more levels; main.py just calls whichever one it wants.
    """
    scene = Scene()

    # The controllable character - a colored square from a primitive
    # rather than an external sprite. The collider size matches the
    # square exactly (create_square passes it through explicitly), which
    # is the recommended pattern - see the docs on why an explicit
    # collider size matters once anything else (an Animator, a scale
    # change) might otherwise cause it to drift.
    character = create_square(x=100, y=100, size=48, color=(90, 160, 230), name="Character")
    character.add_component(Rigidbody2D(gravity=900, use_gravity=True, drag=3.0))
    controller = character.add_component(PlayerController(
        speed=200, jump_force=500, movement_type="platformer", max_jumps=2,
    ))
    character.add_component(ResetOnClick())
    scene.add_game_object(character)

    # A solid platform to stand on.
    platform = create_rectangle(x=50, y=450, width=400, height=40,
                                 color=(90, 90, 100), name="Platform")
    scene.add_game_object(platform)

    # A purely decorative, non-colliding circle - demonstrates
    # create_circle(); it has no gameplay role.
    decoration = create_circle(x=520, y=380, radius=20, color=(230, 190, 90),
                                name="Decoration", add_collider=False)
    scene.add_game_object(decoration)

    # --- HUD: a panel, a jump-counter label, and a reset button ---------

    hud_panel = GameObject(x=10, y=10, name="HUD")
    hud_panel.add_component(UIPanel(width=190, height=74))
    scene.add_game_object(hud_panel)

    jumps_label_go = GameObject(x=20, y=20, name="JumpsLabel")
    jumps_label = jumps_label_go.add_component(UIText(text=f"Jumps: {controller.jumps_remaining}/{controller.max_jumps}"))
    jumps_label_go.add_component(JumpsHUD(controller=controller, label=jumps_label))
    scene.add_game_object(jumps_label_go)

    reset_button_go = GameObject(x=20, y=50, name="ResetButton")
    reset_button = reset_button_go.add_component(UIButton(text="Reset position", width=170, height=26))
    scene.add_game_object(reset_button_go)

    reset_button.on_click.append(character.get_component(ResetOnClick).reset_position)

    return scene
