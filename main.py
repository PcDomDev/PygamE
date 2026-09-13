from engine.core.app import Engine
from engine.components.camera import Camera
from engine.core.game_object import GameObject
from examples.example_scene import build_example_scene


def main():
    engine = Engine(width=1920, height=1080, title="PygamE", fps=60)

    scene = build_example_scene()
    engine.load_scene("main", scene)

    # Camera setup: a Camera is a Component like any other, living on its
    # own GameObject, so it participates in the normal update-order/scene
    # lifecycle instead of being special-cased by the engine. Target it at
    # the controllable character and turn on smooth-follow; drop `target`
    # entirely (or pass target=None) and the world renders exactly as if
    # there were no camera.
    character = scene.find_game_object("Character")
    camera_object = GameObject(name="Main Camera")
    camera = camera_object.add_component(Camera(target=character, follow_speed=6.0, smooth_follow=True))
    scene.add_game_object(camera_object)
    scene.set_active_camera(camera)

    engine.run()


if __name__ == "__main__":
    main()
