# PygamE — 2D Engine (ECS Framework)

> **PygamE** ist eine kompakte 2D-Engine und ein Framework auf Basis von **Pygame** mit einer komponentenbasierten Architektur im Unity-Stil (ECS: `GameObject` + `Component`) zur Entwicklung von 2D-Spielen und interaktiven Anwendungen. Direkt einsatzbereit: deterministische Physik mit festem Zeitschritt (Swept-AABB, Kollisionsebenen und -masken, Kollisions-/Trigger-Callbacks), eine Transform-Hierarchie mit Interpolation beim Rendern, Screen-Space-UI mit Ankern, ein poolbasiertes Partikelsystem, Tilemap-Baking, eine Kamera, Animationen, Audio mit Crossfade und Positionsklang sowie statische Dienste (`Input`, `EventBus`, `PlayerPrefs`, `Debug`). Architektonische Vorteile: Die Physik hängt nie von der Bildwiederholrate ab, Rendering und Simulation kosten nur das, was tatsächlich sichtbar ist und sich bewegt, Szenenwechsel sind auch mitten in einem Frame sicher, und die einzige Abhängigkeit ist Pygame.

## Inhaltsverzeichnis

1. [Überblick und Architekturprinzipien](#1-überblick-und-architekturprinzipien)
2. [Voraussetzungen und Installation](#2-voraussetzungen-und-installation)
3. [Schnellstart (Quick Start)](#3-schnellstart-quick-start)
4. [Engine-Grundgerüst und Lebenszyklus](#4-engine-grundgerüst-und-lebenszyklus)
   - 4.1. [Engine und die Hauptschleife](#41-engine-und-die-hauptschleife)
   - 4.2. [Szenenverwaltung (Scene und SceneManager)](#42-szenenverwaltung-scene-und-scenemanager)
   - 4.3. [GameObject und das Komponentenmodell](#43-gameobject-und-das-komponentenmodell)
   - 4.4. [Die Transform-Hierarchie](#44-die-transform-hierarchie)
5. [Physiksystem (Physics)](#5-physiksystem-physics)
   - 5.1. [Rigidbody2D](#51-rigidbody2d)
   - 5.2. [Collider (BoxCollider2D, CircleCollider2D)](#52-collider-boxcollider2d-circlecollider2d)
   - 5.3. [Kollisionsebenen und Masken (Collision Layers)](#53-kollisionsebenen-und-masken-collision-layers)
6. [Eingabesystem (Input)](#6-eingabesystem-input)
7. [Benutzeroberflächen-System (UI)](#7-benutzeroberflächen-system-ui)
   - 7.1. [Canvas und Screen-Space-UI](#71-canvas-und-screen-space-ui)
   - 7.2. [UI-Elemente (UIText, UIButton, UIPanel, UIHealthBar)](#72-ui-elemente-uitext-uibutton-uipanel-uihealthbar)
   - 7.3. [UI-Anker und Pivots](#73-ui-anker-und-pivots)
8. [Partikelsystem (Particle System)](#8-partikelsystem-particle-system)
9. [Grafik, Animation und Rendering](#9-grafik-animation-und-rendering)
   - 9.1. [SpriteRenderer und Sprite-Anker](#91-spriterenderer-und-sprite-anker)
   - 9.2. [Kamera (Camera)](#92-kamera-camera)
   - 9.3. [Animation und Spritesheets (Animator)](#93-animation-und-spritesheets-animator)
   - 9.4. [Tilemap-Optimierung (Baking)](#94-tilemap-optimierung-baking)
10. [Statische Dienste und Hilfsfunktionen](#10-statische-dienste-und-hilfsfunktionen)

## 1. Überblick und Architekturprinzipien

PygamE basiert auf einer zentralen Idee: **Die Welt besteht aus Objekten, und das Verhalten eines Objekts besteht aus den Komponenten, die man ihm anheftet.** Ein `GameObject` kann sich weder selbst zeichnen noch fallen noch auf Tastendrücke reagieren — all das übernehmen die Komponenten, die man ihm hinzufügt.

| ECS-Rolle | Entsprechung in PygamE | Aufgabe |
| :--- | :--- | :--- |
| **Entity (Entität)** | `GameObject` | Ein benannter Container: ein `Transform`, eine Liste von Komponenten, die Flags `active` / `is_static` / `layer` und eine Eltern-Kind-Hierarchie. |
| **Component (Komponente)** | `Component` und ihre Unterklassen: `SpriteRenderer`, `Rigidbody2D`, `BoxCollider2D`, `Animator`, `PlayerController`, `Camera`, `ParticleSystem`, `UIText` usw. | Daten und Verhalten. Auch der eigene Spiel-Code ist eine Komponente (`class Enemy(Component)`). |
| **System** | `PhysicsWorld` und `RenderSystem` (von jeder `Scene` erzeugt), dazu die statischen Dienste `Input`, `AudioManager`, `EventBus` usw. | Übergreifende Logik über viele Komponenten hinweg: Physik, Rendering, Audio, Events. |
| **Scene (Szene)** | `Scene` | Besitzt die Objekte und die Systeme. Ihre Indizes (nach Komponententyp, nach Update-Reihenfolge) werden inkrementell gepflegt. |
| **Engine** | `Engine` | Das Fenster, die Uhr und die Hauptschleife. |

> **Zur Terminologie.** „ECS" bedeutet in PygamE ein komponentenbasiertes Modell im Unity-Stil (eine Komponente enthält sowohl Daten als auch Verhalten), nicht ein datenorientiertes ECS mit reinen Daten und getrennten Systemen.

### Architekturprinzipien

1. **Zwei Uhren.** Die Physik läuft in `fixed_update` mit einem festen Zeitschritt (standardmäßig 60 Hz), Gameplay, Animation und Kamera laufen in `update` mit variablem `dt`. Bei einem Einbruch der Bildrate führt die Physik mehrere Schritte hintereinander aus, statt einen einzelnen zu „strecken": Das Ergebnis hängt nur von der *Anzahl der Schritte* ab, niemals von der Bildrate.
2. **Interpolation beim Rendern.** Zwischen den Physikschritten werden die Positionen der Körper interpoliert (`Time.alpha`), sodass Bewegungen auf Monitoren mit 144 Hz und mehr flüssig bleiben.
3. **Globale Update-Reihenfolge.** `Component.update_order` gilt für die gesamte Szene, nicht nur innerhalb eines Objekts: Physik (−100) → Collider (−90) → Gameplay (0) → Kamera (100). Die Kamera sieht immer die endgültigen Positionen des Frames.
4. **Nur bezahlen, was genutzt wird.** Die Szene ruft nur tatsächlich *überschriebene* Hooks auf; statische Objekte (`is_static=True`) überspringen Physik und Neuberechnung vollständig; nur für die Kamera sichtbare Sprites werden gezeichnet; Tilemaps werden zu wenigen Blits gebacken.
5. **Sicherheit mitten im Frame.** `GameObject.destroy()`, `Scene.remove_game_object()` und `SceneManager.change_scene()`, aufgerufen aus `update`, einem Kollisions-Callback oder einem Button-Klick, werden am Ende der aktuellen Phase angewendet — die Durchlaufschleife bricht nie ab.
6. **Statische Dienste.** `Input`, `Time`, `EventBus`, `AudioManager`, `PlayerPrefs`, `Debug`, `SceneManager` und `CollisionLayers` sind von überall erreichbar, ohne Referenz auf `Engine`.
7. **Vorhersehbare Koordinaten.** Einheiten sind Pixel, die Y-Achse zeigt nach unten, Winkel sind in Grad im Uhrzeigersinn angegeben.

### Der Frame der Engine

```text
Engine.run()
 └─ jeden Frame:
     ├─ pygame-Events → Input; Debug-Hotkeys (F1–F4)
     ├─ SceneManager.update(dt) → Scene.tick(dt)
     │    ├─ 0…N mal: Scene.fixed_update(1/60)
     │    │     ├─ Component.fixed_update()   (Kräfte anwenden)
     │    │     └─ PhysicsWorld.step()        (Bewegung → Kontakte → Callbacks)
     │    ├─ Scene.update(dt)                 (Component.update() in update_order)
     │    └─ aufgeschobene Zerstörungen und Szenenwechsel
     ├─ AudioManager.update(dt)               (Überblendungen, Lautstärke)
     └─ Zeichnen: Hintergrund → Scene.draw() [Welt durch die Kamera → UI obenauf] → Debug-Overlays → Flip
```

### Wichtigste Funktionen

- **Physik:** fester Zeitschritt, Swept-AABB ohne Tunneling oder Zittern, Schwerkraft / Beschleunigung / Reibung / Luftwiderstand / Masse, Kollisionsebenen und -masken, `enter`- / `stay`- / `exit`-Events für Kollisionen und Trigger. → [Abschnitt 5](#5-physiksystem-physics)
- **Szenen und Objekte:** Lebenszyklus `start` / `update` / `fixed_update` / `draw` / `destroy`, eine zwischengespeicherte Transform-Hierarchie (`is_dirty`), aufgeschobene Zerstörung. → [Abschnitt 4](#4-engine-grundgerüst-und-lebenszyklus)
- **Rendering:** kameragestütztes Culling, ein räumliches Gitter, Tilemap-Baking, ein Cache für rotierte/skalierte Sprites, das Überspringen von Animationen außerhalb des Bildschirms. → [Abschnitt 9](#9-grafik-animation-und-rendering)
- **UI:** ein Screen-Space-Canvas, `UIText` / `UIButton` / `UIPanel` / `UIHealthBar`, neun Anker und Pivots, UI im Weltraum. → [Abschnitt 7](#7-benutzeroberflächen-system-ui)
- **Partikel:** ein auf `ObjectPool` basierender Emitter, Farbverläufe, Skalierung, Ausblenden. → [Abschnitt 8](#8-partikelsystem-particle-system)
- **Dienste:** `Input` mit stringbasierten Tastennamen, `EventBus` (global und pro Objekt), `ObjectPool`, `PlayerPrefs`, `AudioManager`, `Debug`. → [Abschnitt 10](#10-statische-dienste-und-hilfsfunktionen)

---

## 2. Voraussetzungen und Installation

**Voraussetzungen**

| Komponente | Version |
| :--- | :--- |
| Python | 3.8+ (die Engine verwendet keine Syntax neuer als 3.8; getestet mit 3.12) |
| pygame | 2.x (getestet mit 2.6.1) |
| Weitere Abhängigkeiten | keine |

**Installation**

```bash
git clone <https://github.com/PcDomDev/PygamE.git> PygamE
cd PygamE

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux / macOS: source .venv/bin/activate

pip install -r requirements.txt     # oder einfach: pip install pygame
```

**Projektstruktur**

```text
engine/                    die Engine selbst — unabhängig von Ihrem Spiel
├── core/                    app.py (Engine) · scene.py · scene_manager.py · game_object.py
│                            game_time.py (Time) · event_bus.py · object_pool.py
│                            player_prefs.py · spatial_hash.py · debug_manager.py
├── components/              transform · sprite_renderer · animator · camera · rigidbody2d
│                            collider2d / box_collider2d / circle_collider2d
│                            particle_system · audio_source · player_controller · component
├── physics/                 physics_world.py · layers.py · collision.py
├── rendering/               render_system.py · surface_cache.py · tilemap.py
├── input/                   input_manager.py (Input) · key.py (Key)
├── ui/                      ui_element · canvas · ui_text · ui_button · ui_panel
│                            ui_health_bar · ui_layout · ui_style
├── audio/                   audio_manager.py
├── utils/                   vector2 · anchors · fonts · spritesheet_loader · warnings
└── primitives.py            Fabrikfunktionen create_rectangle / square / circle / triangle / line
tests/                     test_engine.py — Tests ohne Fenster · benchmark.py — Messungen
examples/                  showcase.py — eine Demo-Ebene, die alle Systeme nutzt
main.py                    der Einstiegspunkt Ihres Spiels
requirements.txt
```

Importe erfolgen immer ausgehend vom Projekt-Root: `from engine.core.app import Engine`. `engine/` weiß nichts über Ihr Spiel — der Spielcode liegt außerhalb davon.

### Installation überprüfen (Smoke Test)

Das folgende Skript öffnet kein Fenster und benötigt keine Soundkarte (es verwendet SDLs „Dummy"-Treiber): Es erstellt eine Szene, lässt einen Körper auf einen Boden fallen und prüft, ob die Physik korrekt gearbeitet hat. Speichern Sie es als `smoke_test.py` im **Projekt-Root** und führen Sie es aus.

```python
# smoke_test.py — Installation von PygamE prüfen, ohne Fenster und ohne Soundkarte
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # kein Fenster
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # kein Ton

import pygame

from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.core.scene import Scene

pygame.init()
pygame.display.set_mode((320, 240))

scene = Scene("smoke")

floor = GameObject(0, 200, name="Floor", is_static=True)
floor.add_component(BoxCollider2D(size=(320, 40)))
scene.add_game_object(floor)

ball = GameObject(100, 0, name="Ball")
ball.add_component(BoxCollider2D(size=(20, 20)))
body = ball.add_component(Rigidbody2D())
scene.add_game_object(ball)

for _ in range(180):                 # 3 Sekunden Simulation bei 60 Bildern pro Sekunde
    scene.tick(1 / 60)

assert body.is_grounded, "der Körper hätte auf dem Boden landen müssen"
assert abs(ball.transform.world_y - 180) < 1e-6, ball.transform.world_y   # Bodenoberkante 200 − Höhe 20
print("PygamE funktioniert: der Körper ist gelandet bei y =", ball.transform.world_y)
```

```bash
python smoke_test.py                     # erwartet wird die Zeile „PygamE funktioniert: ..."
python -m unittest discover tests        # die vollständige Testsuite; erwartet wird „OK"
python examples/showcase.py              # eine spielbare Demo (öffnet ein Fenster)
python examples/showcase.py --headless 300 shot.png   # dasselbe ohne Fenster, mit Screenshot
```

Endet `smoke_test.py` ohne Fehler, ist die Installation korrekt: Python, pygame und die Engine arbeiten zusammen.

---

## 3. Schnellstart (Quick Start)

Ein minimales Spiel: ein Plattformer mit Doppelsprung, Münzen, einer Kamera und einem Punktezähler. Speichern Sie es als `main.py` im Projekt-Root.

```python
# main.py
import pygame

from engine.components.camera import Camera
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.player_controller import PlayerController
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.app import Engine
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_circle, create_rectangle, create_square
from engine.ui.ui_text import UIText


class GameScene(Scene):
    def start(self):
        super().start()                       # erforderlich: startet alles bereits Hinzugefügte
        self.score = 0

        # Boden und Plattform — statisch: sie überspringen Physik und werden nie neu berechnet
        self.add_game_object(create_rectangle(-1000, 500, 3000, 60, color=(96, 72, 48),
                                              name="Ground", is_static=True))
        self.add_game_object(create_rectangle(420, 380, 180, 24, color=(120, 90, 60),
                                              name="Platform", is_static=True))

        # Der Spieler: ein Körper mit Schwerkraft + Steuerung
        player = create_square(100, 300, size=40, color=(70, 130, 230), name="Player",
                               add_rigidbody=True)
        player.get_component(Rigidbody2D).gravity = 900
        player.add_component(PlayerController(speed=240, jump_force=460,
                                              movement_type="platformer", max_jumps=2))
        self.add_game_object(player)

        # Münzen — Trigger: durchquerbar, melden aber die Berührung
        for x, y in ((300, 460), (470, 340), (540, 340), (700, 460)):
            coin = create_circle(x, y, radius=12, color=(255, 210, 60), name="Coin",
                                 precise_collider=True, is_static=True)
            collider = coin.get_component(CircleCollider2D)
            collider.is_trigger = True
            collider.on_trigger_enter.append(self.on_coin_touched)
            self.add_game_object(coin)

        # Die Kamera folgt dem Spieler
        camera_object = GameObject(name="Camera")
        camera = camera_object.add_component(Camera(target=player, follow_speed=6))
        self.add_game_object(camera_object)
        self.set_active_camera(camera)

        # HUD: ein Anker heftet den Text an eine Bildschirmecke
        hud = GameObject(12, 12, name="HUD")
        self.score_text = hud.add_component(UIText("Münzen: 0", anchor="TopLeft"))
        self.add_game_object(hud)

    def on_coin_touched(self, coin_collider, other_collider):
        if other_collider.game_object.name == "Player":
            coin_collider.game_object.destroy()     # sicher, direkt im Callback aufzurufen
            self.score += 1
            self.score_text.set_text(f"Münzen: {self.score}")


def main():
    engine = Engine(1280, 720, "PygamE — Schnellstart", fps=144,
                    background_color=(120, 172, 226))
    engine.change_scene(GameScene)            # erstellt die Szene, ruft start() auf
    engine.run()


if __name__ == "__main__":
    main()
```

```bash
python main.py
```

**Steuerung:** `A` / `D` oder `←` / `→` zum Bewegen, `Space` zum Springen (ein zweites Mal in der Luft), `Esc` schließt das Fenster, sofern Sie es selbst behandeln (siehe [Input](#6-eingabesystem-input)). **Debug:** `F1` Statistik, `F2` Collider, `F3` Weltgitter, `F4` Log-Konsole.

Was hier passiert ist:

1. `Engine` hat das Fenster geöffnet und die Hauptschleife gestartet ([4.1](#41-engine-und-die-hauptschleife)).
2. `change_scene(GameScene)` hat die Szene erstellt und `start()` aufgerufen, wo wir die Welt aus `GameObject`s aufgebaut haben ([4.2](#42-szenenverwaltung-scene-und-scenemanager), [4.3](#43-gameobject-und-das-komponentenmodell)).
3. Die Physik läuft mit festem Zeitschritt, und `PlayerController` liest jeden Frame die Eingabe ([5.1](#51-rigidbody2d), [Input](#6-eingabesystem-input)).
4. Eine Münze ist ein statischer Trigger: Der Callback feuert bei Berührung ([5.2](#52-collider-boxcollider2d-circlecollider2d)).
5. Die Kamera folgt dem Spieler, während das HUD an Ort und Stelle bleibt — UI wird in Bildschirmkoordinaten gezeichnet ([9.2](#92-kamera-camera), [7.1](#71-canvas-und-screen-space-ui)).

---

## 4. Engine-Grundgerüst und Lebenszyklus

### 4.1. Engine und die Hauptschleife

**Beschreibung:** `Engine` besitzt das Fenster, die Uhr und die Hauptschleife — die einzige Klasse, die `main.py` benötigt. Jeden Frame leitet sie Events an `Input` weiter, verarbeitet die Debug-Hotkeys, ruft `SceneManager.update()` auf (feste Physikschritte, dann das variable `update`), aktualisiert das Audio und zeichnet die Szene. Die Physik hängt nie von der Bildrate ab: `fps` begrenzt nur, wie oft der Bildschirm neu gezeichnet wird, während `fixed_fps` die Physikrate festlegt. Beim Beenden zerstört `Engine` die aktive Szene (jedes `on_destroy` wird ausgeführt), stoppt das Audio, speichert nicht gespeicherte `PlayerPrefs` und fährt pygame herunter.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Engine(...)` | `width: int = 1280, height: int = 720, title: str = "Pygame Engine", fps: int = 60, background_color: tuple = (30, 30, 35), fixed_fps: int = 60, vsync: bool = False, resizable: bool = False, debug: bool = True` | Erstellt das Fenster und die Subsysteme. `fps=0` bedeutet keine Begrenzung der Bildrate; `fixed_fps` ist die Physikrate in Hz; `vsync=True` fordert vertikale Synchronisation an (aktiviert das `SCALED`-Flag); `resizable` erlaubt das Ändern der Fenstergröße; `debug=False` deaktiviert alle Debug-Hotkeys und Overlays (Release-Build). |
| `run()` | — | Die blockierende Hauptschleife. Endet, wenn das Fenster geschlossen wird oder `quit()` aufgerufen wird. Als Letztes aufrufen: `engine.run()`. |
| `quit()` | — | Stoppt die Schleife nach dem aktuellen Frame: `engine.quit()`. |
| `load_scene(name, scene)` | `name: str, scene: Scene` | Registriert eine fertige Szeneninstanz unter einem Namen und macht sie sofort aktiv; die vorherige Szene bleibt, falls vorhanden, am Leben (siehe [4.2](#42-szenenverwaltung-scene-und-scenemanager)). |
| `change_scene(target, *args, **kwargs)` | `target: eine Scene-Klasse, -Instanz oder ein registrierter Name` | Zerstört die aktuelle Szene und startet eine neue: `engine.change_scene(Level1, difficulty=2)`. Ein Wrapper um `SceneManager.change_scene`. |
| `active_scene` | `Scene oder None` (Eigenschaft) | Die aktuell aktive Szene. |
| `screen` | `pygame.Surface` | Die Oberfläche des Fensters. |
| `clock` | `pygame.time.Clock` | Die Uhr der Hauptschleife. |
| `input` / `debug` / `audio` | `Input` / `DebugManager` / `AudioManager` | Die Subsysteme, die die Engine besitzt (dieselben Instanzen wie die statischen Dienste). |
| `scene_manager` | `SceneManager` | Der statische Szenenmanager (die Klasse selbst). |
| `width`, `height`, `fps`, `background_color`, `running` | `int`, `int`, `int`, `tuple`, `bool` | Fensterparameter und das Flag, ob die Schleife läuft. |
| `Engine.MAX_DELTA_TIME` | `float = 0.05` | Die obere Grenze für das variable `dt` in `update` (ein Schutz gegen Sprünge nach einer Debugger-Pause). Betrifft die Physik nicht — die hat ihre eigenen Grenzen: `Time.max_frame_time` und `Time.max_fixed_steps`. |

#### Anwendungsbeispiel

```python
import pygame

from engine.core.app import Engine
from engine.core.debug_manager import Debug
from engine.core.scene import Scene


class DemoScene(Scene):
    def start(self):
        super().start()
        self.elapsed = 0.0
        Debug.log("Szene gestartet")

    def update(self, delta_time):
        super().update(delta_time)          # ohne super() werden Komponenten nicht aktualisiert
        self.elapsed += delta_time
        if self.elapsed > 3.0:              # das Fenster nach 3 Sekunden schließen
            pygame.event.post(pygame.event.Event(pygame.QUIT))


def main():
    engine = Engine(
        width=1280, height=720, title="Demo",
        fps=0,                # keine Begrenzung der Bildrate (oder vsync=True)
        fixed_fps=60,         # die Physik läuft immer mit 60 Schritten pro Sekunde
        resizable=True,
        debug=True,           # F1–F4 funktionieren; False für einen Release-Build
    )
    engine.change_scene(DemoScene)
    engine.run()


if __name__ == "__main__":
    main()
```

### 4.2. Szenenverwaltung (Scene und SceneManager)

**Beschreibung:** `Scene` ist eine Sammlung von `GameObject`s plus die Systeme, die sie steuern: `physics` (`PhysicsWorld`) und `render_system` (`RenderSystem`). Lebenszyklus-Hooks: `start()` (einmal beim Laden), `update(dt)` (jeden Frame), `fixed_update(dt)` (jeden Physikschritt), `draw(screen)` und `destroy()` (beim Verlassen). Die Basisversionen von `update` / `fixed_update` / `draw` **starten Ihre Komponenten**, daher muss eine Unterklasse immer `super()` aufrufen. `SceneManager` ist ein statischer Manager: `SceneManager.change_scene(Level1Scene)` zerstört die aktuelle Szene (`destroy()` gibt Objekte, Abonnements sowie Physik- und Renderstrukturen frei — die alte Szene wird anschließend vom Garbage Collector eingesammelt) und startet die neue (`start()`). Wird ein Wechsel *während eines Frames* angefordert (ein Button-Klick, ein Kollisions-Callback), wird er auf das Ende dieses Frames verschoben; zu jedem anderen Zeitpunkt (Programmstart, Tests) geschieht er sofort.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Scene(name)` | `name: str = "Scene"` | Erstellt eine leere Szene. Der Standardname wird beim Laden über `SceneManager` durch den Klassennamen ersetzt. |
| `start()` | — | Hook: wird einmal beim Laden aufgerufen. Bauen Sie hier Ihre Welt auf und rufen Sie `super().start()` auf. |
| `update(delta_time)` | `delta_time: float` | Hook: der variable Schritt; führt `update` der Komponenten in der Reihenfolge `update_order` aus, wendet dann aufgeschobene Entfernungen an. |
| `fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Hook: ein Physikschritt — zuerst `fixed_update` der Komponenten, dann `physics.step()` und die Kollisions-Callbacks. |
| `draw(screen)` | `screen: pygame.Surface` | Hook: zeichnet die Welt durch die Kamera, dann die UI. `render(screen)` ist der alte Name und leitet hierhin weiter. |
| `destroy()` | — | Hook: zerstört alle Objekte und räumt die Systeme der Szene auf. Wird vom Manager beim Verlassen der Szene aufgerufen. |
| `add_game_object(go)` | `go: GameObject` | Fügt das Objekt **samt seiner Kinder** hinzu und startet es sofort: `scene.add_game_object(player)`. |
| `remove_game_object(go)` | `go: GameObject` | Entfernt das Objekt aus der Szene, ohne es zu zerstören. Innerhalb der Schleife wird dies bis zum Ende der Phase aufgeschoben. |
| `destroy_game_object(go)` | `go: GameObject` | Zerstört das Objekt (`on_destroy`, Kinder, Abonnements). Dasselbe bewirkt `go.destroy()`. |
| `find_game_object(name)` | `name: str` | Das erste Objekt mit diesem Namen oder `None`. |
| `find_game_objects_with_tag(tag)` | `tag: str` | Die Liste der Objekte mit diesem Tag. |
| `get_components(component_type)` | `component_type: type` | Alle lebenden Komponenten dieses Typs (Unterklassen eingeschlossen) auf aktiven Objekten — eine neue Liste, sicher zu durchlaufen: `scene.get_components(UIButton)`. |
| `get_component(component_type)` | `component_type: type` | Die erste Komponente dieses Typs oder `None`. |
| `set_active_camera(camera)` | `camera: Camera` | Legt fest, durch welche Kamera die Welt gezeichnet wird. Die Eigenschaft `active_camera` gibt sie zurück. |
| `screen_to_world(pos)` / `world_to_screen(pos)` | `pos: tuple oder Vector2` | Koordinatenumrechnung über die aktive Kamera: `scene.screen_to_world(Input.mouse_position())`. |
| `tick(frame_dt)` | `frame_dt: float` | Simuliert einen Frame ohne Fenster: sammelt Zeit an, führt 0…N `fixed_update`-Schritte aus, dann `update`. Für Tests und Werkzeuge. Gibt zurück, wie viele Physikschritte gelaufen sind. |
| `game_objects`, `physics`, `render_system` | `list`, `PhysicsWorld`, `RenderSystem` | Die Objektliste der Szene und ihre Systeme. |
| `entity_count`, `active_entity_count`, `draw_calls` | `int` | Gesamtzahl der Objekte, Anzahl aktiver Objekte und Zeichenaufrufe im letzten Frame. |
| `is_started`, `is_destroyed`, `name` | `bool`, `bool`, `str` | Lebenszyklusstatus und Name der Szene. |
| `SceneManager.change_scene(...)` | `target, *args, immediate: bool = None, destroy_previous: bool = True, **kwargs` | Wechselt die Szene: `target` ist eine `Scene`-Klasse, -Instanz oder ein registrierter Name; `*args` / `**kwargs` gehen an den Klassenkonstruktor. Gibt die neue Szene zurück, oder `None`, wenn der Wechsel auf das Frame-Ende verschoben wurde. `immediate=True/False` erzwingt das eine oder das andere Verhalten. |
| `SceneManager.register(name, scene_or_class)` | `name: str, scene_or_class: Scene oder type` | Registriert eine Szene oder Klasse: `SceneManager.register("menu", MenuScene)`, danach erzeugt `change_scene("menu")` jedes Mal eine frische Instanz. |
| `SceneManager.add_scene(name, scene)` / `set_active(name)` | `name: str, scene: Scene` | Die alte API: Registrieren und Wechseln **ohne** Zerstörung der vorherigen Szene (ihr Zustand bleibt erhalten; `start()` läuft nur bei der ersten Aktivierung). |
| `SceneManager.get_scene(name)` / `remove_scene(name)` | `name: str` | Eine registrierte Instanz abrufen / sie vergessen und zerstören. |
| `SceneManager.active_scene` | `Scene oder None` | Die aktive Szene. |
| `SceneManager.shutdown()` / `reset()` | — | Die aktive Szene zerstören (wird von `Engine` beim Beenden aufgerufen) / alles vergessen (Tests). |

#### Anwendungsbeispiel

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.core.scene_manager import SceneManager
from engine.ui.ui_button import UIButton
from engine.ui.ui_text import UIText


class MenuScene(Scene):
    def start(self):
        super().start()
        title = GameObject(0, -80, name="Title")
        title.add_component(UIText("Mein Spiel", anchor="Center"))
        self.add_game_object(title)

        play = GameObject(0, 0, name="PlayButton")
        button = play.add_component(UIButton("Spielen", 200, 48, anchor="Center"))
        # Der Klick geschieht innerhalb eines Frames — der Szenenwechsel greift an dessen Ende
        button.on_click.append(lambda _button: SceneManager.change_scene(LevelScene, level=1))
        self.add_game_object(play)


class LevelScene(Scene):
    def __init__(self, level=1):
        super().__init__(f"Level{level}")
        self.level = level

    def start(self):
        super().start()
        print(f"Level {self.level} geladen")

    def destroy(self):
        print(f"Level {self.level} entladen")
        super().destroy()


SceneManager.register("menu", MenuScene)     # per Name: jedes Mal eine frische Instanz
SceneManager.change_scene("menu")            # vor dem Start der Schleife — geschieht sofort
SceneManager.change_scene(LevelScene, level=2)   # entlädt das Menü, lädt Level 2
# Im echten Spiel treibt Engine.run() die Frames an; hier ein Frame von Hand:
SceneManager.update(1 / 60)
```

### 4.3. GameObject und das Komponentenmodell

**Beschreibung:** `GameObject` ist ein Container mit einem obligatorischen `Transform`; Verhalten wird über Komponenten hinzugefügt (`add_component`). Komponenten erben von `Component` und überschreiben nur die benötigten Hooks — die Szene ruft **nur die überschriebenen** auf, sodass ein ungenutzter Hook nichts kostet. Objekt-Flags: `active` (ein inaktives Objekt wird nicht aktualisiert, nimmt nicht an der Physik teil und wird nicht gezeichnet — ebenso wenig alle seine Kinder, siehe `active_in_hierarchy`), `is_static` (das Objekt wird sich nie bewegen: es überspringt Physik und Neuberechnung, sein Collider und Sprite werden einmalig registriert; um ein solches Objekt zu bewegen, setzen Sie zuerst `is_static = False`) und `layer` (die Kollisionsebene). `update_order` legt die Reihenfolge fest, in der Komponenten laufen, **global für die gesamte Szene**.

| Komponente | `update_order` |
| :--- | :---: |
| `Rigidbody2D` | −100 |
| `BoxCollider2D` / `CircleCollider2D` | −90 |
| Ihr Gameplay, `Animator`, `PlayerController`, UI | 0 |
| `Camera` | 100 |

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `GameObject(...)` | `x: float = 0.0, y: float = 0.0, name: str = "GameObject", layer: int oder str = 0, tag: str = None, is_static: bool = False, parent: GameObject = None` | Erstellt ein Objekt mit einem `Transform` an der Position `(x, y)`. `parent` heftet es sofort an ein Elternobjekt. |
| `add_component(component)` | `component: Component` | Heftet eine Komponente an und gibt sie zurück: `body = go.add_component(Rigidbody2D())`. Ist das Objekt bereits in einer Szene, startet die Komponente sofort. |
| `get_component(cls)` / `get_components(cls)` / `has_component(cls)` | `cls: type` | Die erste Komponente dieses Typs (oder `None`) / eine Liste aller / ob sie vorhanden ist. Suchen Sie Geschwisterkomponenten in `start()`, nicht in `__init__`. |
| `remove_component(component)` | `component: Component` | Löst eine Komponente (ihr `on_destroy` wird ausgeführt). Das `Transform` kann nicht entfernt werden. |
| `transform` | `Transform` | Immer vorhanden — eine Prüfung auf `None` ist nicht nötig. |
| `name`, `tag` | `str`, `str` | Name und Tag für die Suche (`scene.find_game_object("Player")`). |
| `active` / `active_in_hierarchy` | `bool` | Das eigene Flag / „aktiv und alle Vorfahren ebenfalls". |
| `is_static` | `bool` | Wird sich nie bewegen — siehe Beschreibung oben. |
| `layer` | `int oder str` | Die Kollisionsebene, standardmäßig von den Collidern geerbt: `go.layer = "enemy"` (siehe [5.3](#53-kollisionsebenen-und-masken-collision-layers)). |
| `parent` / `children` | `GameObject oder None` / `list` | Die Hierarchie; `children` ist die Liste der Kinder. |
| `set_parent(parent, keep_world_position=False)` | `parent: GameObject oder None, keep_world_position: bool` | Ändert das Elternobjekt (Details in [4.4](#44-die-transform-hierarchie)). `add_child(child)` und `find_child(name)` sind Abkürzungen. |
| `x`, `y` | `float` | Aliase für die lokale Position: `go.x += 5`. |
| `scene` | `Scene oder None` | Die Szene, in der sich das Objekt gerade befindet. |
| `events` | `EventDispatcher` | Der private Event-Bus des Objekts (siehe [EventBus](#eventbus)): `go.events.emit("hit", damage=5)`. `clear_events()` entfernt seine Abonnements. |
| `destroy()` | — | Zerstört das Objekt und seine Kinder. Innerhalb der Schleife wird dies bis zum Ende der Phase aufgeschoben, daher sicher aus Callbacks aufrufbar. Führt `on_destroy` auf jeder Komponente aus. |
| `despawn()` | — | Gibt das Objekt an seinen Pool zurück (falls es aus einem `GameObjectPool` stammt), sonst wird `destroy()` aufgerufen. |
| `Component.start()` | — | Hook: einmal, beim Betreten einer Szene. Suchen Sie hier Geschwisterkomponenten. |
| `Component.update(delta_time)` | `delta_time: float` | Hook: jeden Frame, variabler Schritt. Eingabe, Animation, visuelle Logik. |
| `Component.fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Hook: jeden Physikschritt, **vor** dem eigentlichen Physikschritt — der Ort für `add_force`. |
| `Component.draw_world(screen, offset_x, offset_y, alpha)` | `screen: Surface, offset_x: int, offset_y: int, alpha: float` | Hook: eigenes Zeichnen im Weltraum (Partikel, gebackene Layer). Geben Sie die Anzahl der Blits zurück (oder `None`). |
| `Component.on_destroy()` | — | Hook: wenn das Objekt zerstört oder die Komponente entfernt wird — geben Sie hier Ressourcen frei. |
| `on_collision_enter/stay/exit(collision)` | `collision: Collision2D` | Optionale Handler-Methoden für Physik, auf jeder Komponente (siehe [5.2](#52-collider-boxcollider2d-circlecollider2d)). |
| `on_trigger_enter/stay/exit(other)` | `other: Collider2D` | Dasselbe für Trigger. |
| `game_object`, `transform`, `events` | — | Das besitzende Objekt, sein `Transform` und sein Event-Bus (Abkürzungen). |
| `enabled` | `bool` | `False` — die Komponente erhält kein `update` / `fixed_update`. |
| `update_order`, `updates_when_static` | `int = 0`, `bool = True` | Ausführungsreihenfolge (Tabelle oben). `updates_when_static = False` überspringt die Komponente bei statischen Objekten. |

#### Anwendungsbeispiel

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_square


class Spinner(Component):
    """Rotation ist ein visueller Effekt und gehört daher in update (jeden Frame)."""

    def __init__(self, degrees_per_second=90):
        super().__init__()
        self.degrees_per_second = degrees_per_second

    def update(self, delta_time):
        self.game_object.transform.rotation += self.degrees_per_second * delta_time


class Thruster(Component):
    """Kräfte werden in fixed_update angewendet — direkt vor dem Physikschritt."""

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)   # Geschwister in start() suchen

    def fixed_update(self, fixed_delta_time):
        self.body.add_force(0, -1200)       # Schub nach oben, stärker als die Schwerkraft (500 px/s²)


class SelfDestruct(Component):
    def __init__(self, seconds):
        super().__init__()
        self.left = seconds

    def update(self, delta_time):
        self.left -= delta_time
        if self.left <= 0:
            self.game_object.destroy()      # aufgeschoben bis zum Ende der Phase — sicher

    def on_destroy(self):
        print(f"{self.game_object.name} zerstört")


scene = Scene("components")
rocket = create_square(200, 300, size=30, name="Rocket", add_rigidbody=True)
rocket.tag = "projectile"
rocket.add_component(Thruster())
rocket.add_component(Spinner(180))
rocket.add_component(SelfDestruct(2.0))
scene.add_game_object(rocket)

for _ in range(150):                         # 2,5 Sekunden Simulation
    scene.tick(1 / 60)
assert scene.find_game_object("Rocket") is None      # hat sich selbst zerstört
```

### 4.4. Die Transform-Hierarchie

**Beschreibung:** Jedes `GameObject` erhält automatisch ein `Transform`, das Position, Rotation und Skalierung speichert. Werte gibt es in zwei Varianten: **lokal** (relativ zum Elternobjekt — das ist der tatsächlich gespeicherte Wert) und **Welt** (das Ergebnis der Verkettung der gesamten Elternkette). `position` ist ein Alias für `local_position`; bei einem Objekt ohne Elternteil sind lokale und Weltwerte identisch, sodass Code, der vor Einführung einer Hierarchie geschrieben wurde, unverändert weiterfunktioniert. Rotation ist in Grad angegeben, im Uhrzeigersinn (Y zeigt nach unten). Weltwerte werden hinter einem `is_dirty`-Flag zwischengespeichert: Das Ändern eines Transforms markiert es und sein gesamtes Teilbaum als „dirty", und das Lesen eines Weltwerts berechnet ihn nur neu, wenn er „dirty" ist — eine unbewegte Hierarchie berechnet überhaupt nichts neu. Selbst Änderungen an Ort und Stelle (`position.x += 5`) werden erfasst. Bei physikalischen Körpern liefert `get_render_xy(alpha)` eine geglättete Position zwischen zwei Physikschritten; Kinder werden aus der *geglätteten* Position des Elternteils gebildet, sodass eine von einem Spieler gehaltene Waffe nie hinterherhinkt.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Transform(...)` | `x: float = 0.0, y: float = 0.0, rotation: float = 0.0, scale_x: float = 1.0, scale_y: float = 1.0` | Wird automatisch innerhalb von `GameObject` erstellt. |
| `position` / `local_position` | `Vector2` | Die lokale Position; unterstützt Änderungen an Ort und Stelle: `t.position.x += 10`. |
| `rotation` / `local_rotation` | `float` | Die lokale Rotation in Grad. |
| `scale` / `local_scale` | `Vector2` (eine Zahl wird ebenfalls akzeptiert) | Die lokale Skalierung: `t.scale = 2`. Collider skalieren dabei nicht mit. |
| `world_position` | `Vector2` (eine Kopie), zuweisbar | Die Weltposition. Das Bearbeiten der Kopie bewirkt nichts — weisen Sie stattdessen zu: `t.world_position = Vector2(0, 0)`. |
| `world_rotation`, `world_scale` | `float`, `Vector2` | Weltrotation und -skalierung (nur lesbar). |
| `world_x`, `world_y`, `get_world_xy()` | `float`, `float`, `tuple` | Schnelles Lesen der Weltposition ohne Kopie. |
| `set_world_position(x, y)` | `x: float, y: float` | Setzt die Weltposition (berechnet die lokale Position neu). |
| `translate(dx, dy)` | `dx: float, dy: float` | Verschiebt im Raum des Elternteils. |
| `teleport(x, y)` | `x: float, y: float` | Bewegt ohne Interpolation, sodass die Glättung den Sprung nie „verschmiert". |
| `parent` | `Transform oder None` | Das Elternobjekt (Zuweisung ruft `set_parent` auf). |
| `set_parent(parent, keep_world_position=False)` | `parent: Transform, GameObject oder None, keep_world_position: bool` | Ändert das Elternobjekt. Standardmäßig bleibt der lokale Versatz erhalten; `keep_world_position=True` lässt das Objekt an seiner Stelle in der Welt. Ein Zyklus (ein Elternteil, das zugleich ein Nachkomme ist) löst `ValueError` aus. |
| `detach(keep_world_position=True)` | `keep_world_position: bool` | Löst vom Elternobjekt. |
| `children`, `child_count`, `root`, `depth` | `tuple`, `int`, `Transform`, `int` | Navigation durch die Hierarchie. |
| `transform_point(x, y)` / `inverse_transform_point(x, y)` | `x: float, y: float` | Ein Punkt aus dem lokalen Raum in den Weltraum und zurück: `t.transform_point(30, 0)`. |
| `is_dirty`, `world_version` | `bool`, `int` | Der Cache der Weltwerte: ist er veraltet, und wie oft wurde er neu berechnet. |
| `interpolate` | `bool` | Aktiviert die Glättung zwischen Physikschritten (`Rigidbody2D` schaltet sie selbst ein). |
| `get_render_xy(alpha)` / `render_position` | `alpha: float` | Die Position zum Zeichnen, mit Interpolation; `render_position` verwendet `Time.alpha`. |
| `reset_interpolation()` | — | „Vorherige Position := aktuelle": Der nächste Frame wird genau dort gezeichnet, wo das Objekt steht. |

#### Anwendungsbeispiel

```python
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square
from engine.utils.vector2 import Vector2

scene = Scene("hierarchy")

player = create_square(200, 300, size=40, name="Player", add_rigidbody=True)
sword = create_rectangle(0, 0, 30, 8, color=(220, 220, 230), name="Sword", add_collider=False)

sword.set_parent(player)                  # das Schwert ist ein Kind des Spielers
sword.transform.position.x = 40           # 40 px rechts vom Spieler (lokaler Raum)
sword.transform.rotation = -30            # Rotation relativ zum Elternteil
scene.add_game_object(player)             # ein Kind kommt zusammen mit seinem Elternteil in die Szene

print(sword.transform.get_world_xy())     # (240.0, 300.0): Elternteil + Versatz
player.transform.position.x += 100        # der Spieler hat sich bewegt — das Schwert folgt
print(sword.transform.get_world_xy())     # (340.0, 300.0)

world = sword.transform.world_position    # eine Kopie: Bearbeiten bewirkt nichts
sword.transform.world_position = Vector2(500, 100)   # so funktioniert es (Weltkoordinaten)

sword.set_parent(None, keep_world_position=True)     # lösen, ohne es in der Welt zu bewegen
player.transform.teleport(500, 100)       # Bewegung ohne Glättung
```

---

## 5. Physiksystem (Physics)

Die Physik von PygamE besteht aus `Rigidbody2D` (Bewegung) + Collidern (Form) + `PhysicsWorld` (dem System, das jede Szene erstellt). Alles läuft in `fixed_update`, im Abstand von `Time.fixed_delta_time` (standardmäßig 1/60 s). Reihenfolge eines Schritts: `fixed_update` der Komponenten → Aktualisierung der von Skripten bewegten Collider → Simulation jedes Körpers → Kontaktsuche → Callbacks (`exit`, dann `enter`, dann `stay`). Die Breitphase ist ein gleichmäßiges Gitter (`SpatialHash`): statische Collider registrieren sich einmalig, und nur bewegte Collider lösen Abfragen aus.

### 5.1. Rigidbody2D

**Beschreibung:** Die Komponente, die ein Objekt bewegt: Geschwindigkeit, Beschleunigung, Schwerkraft, Luftwiderstand, Reibung und Masse. Die Bewegung wird **achsenweise mit einem „Sweep"-Scan (Swept AABB)** aufgelöst: Der Körper bewegt sich genau bis zum nächsten Hindernis und bleibt bündig davor stehen. Dadurch gibt es kein Tunneling bei beliebiger Geschwindigkeit, kein Zittern beim Landen, und `is_grounded` ist stabil (das Ruhen auf einer Oberfläche ist ein Kontakt mit Lücke null). Ein Körper, der einen Schritt bereits innerhalb eines festen Objekts beginnt (dort erzeugt oder dorthin teleportiert), wird entlang der Achse der geringsten Durchdringung herausgeschoben. Reihenfolge innerhalb eines Schritts: Kräfte, Beschleunigung und Schwerkraft → Luftwiderstand (`exp(-drag·dt)` auf beiden Achsen) → Bodenreibung (`friction · |gravity|` px/s² horizontal) → Begrenzung der Fallgeschwindigkeit → Entdurchdringung → Bewegung auf X → Bewegung auf Y. Einheiten sind Pixel und Sekunden.

> **Einschränkungen.** Feste Hindernisse können nur `BoxCollider2D` sein (Kreise funktionieren nur als Trigger). Körper behandeln sich gegenseitig als unbewegliche Wände (keine Impulsübertragung). Kinematische Plattformen „transportieren" keine auf ihnen stehenden Körper. Setzen Sie `Rigidbody2D` auf Wurzelobjekte: An einem Kind arbeitet es im lokalen Raum des Elternteils (die Engine protokolliert eine Warnung).

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Rigidbody2D(...)` | `gravity: float = 500, gravity_scale: float = 1.0, drag: float = 0.0, mass: float = 1.0, use_gravity: bool = True, is_kinematic: bool = False, terminal_velocity: float = 1000, friction: float = 0.0, acceleration: tuple oder Vector2 = None, interpolate: bool = True` | Erstellt einen Körper. `gravity` (px/s²) und `gravity_scale` steuern den Fall; `drag` ist der Luftwiderstand (1/s); `friction` ist der Bodenreibungskoeffizient; `mass` teilt Kräfte und Impulse; `terminal_velocity` begrenzt die Fallgeschwindigkeit; `acceleration` ist eine konstante Beschleunigung (Wind, Schub); `is_kinematic` bedeutet, dass sich der Körper nur über `velocity` bewegt, keine Kollisionen auflöst, aber weiterhin Events auslöst; `interpolate` sorgt für geglättetes Rendering zwischen den Schritten. Alle Parameter sind auch als Attribute verfügbar. |
| `velocity` | `Vector2` | Geschwindigkeit in px/s. Direkt änderbar: `body.velocity.x = 200`. `velocity_x` / `velocity_y` sind skalare Aliase. |
| `acceleration` | `Vector2` | Konstante Beschleunigung in px/s². |
| `is_grounded` | `bool` | `True`, wenn der Körper von unten getragen wird (wird bei jedem Schritt aktualisiert). |
| `collider` | `BoxCollider2D oder None` | Wird in `start()` gefunden; ohne ihn wirkt die Schwerkraft weiterhin, aber es gibt keine Kollisionen (eine Warnung wird protokolliert). |
| `add_impulse(impulse_x, impulse_y)` | `impulse_x: float, impulse_y: float` | Eine sofortige Geschwindigkeitsänderung: `Δv = Impuls / Masse`. Ein Sprung, ein Rückstoß: `body.add_impulse(0, -400)`. |
| `add_force(force_x, force_y, delta_time=None)` | `force_x: float, force_y: float, delta_time: float = None` | Die Kraft sammelt sich an und wird im **nächsten** Physikschritt angewendet, danach zurückgesetzt — rufen Sie sie in jedem `fixed_update` für einen anhaltenden Schub auf. Mit `delta_time` gilt das alte Verhalten: sofort `v += F / m · dt`. |
| `stop()` | — | Setzt Geschwindigkeit und angesammelte Kräfte auf null. |
| `teleport(x, y)` | `x: float, y: float` | Bewegt zu einem Weltpunkt ohne Glättung und stoppt den Körper. |
| `on_spawn()` / `on_despawn()` | `**kwargs` / — | Hooks für `GameObjectPool`: Der Körper stoppt sich selbst, wenn er aus dem Pool entnommen und wenn er zurückgegeben wird. |

#### Anwendungsbeispiel

```python
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square

scene = Scene("physics")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

# Eine Kiste mit Reibung: sie rutscht und kommt zum Stillstand
crate = create_square(100, 300, size=40, name="Crate", add_rigidbody=True)
crate_body = crate.get_component(Rigidbody2D)
crate_body.friction = 0.6        # verzögert am Boden um 0,6 · gravity px/s²
crate_body.mass = 2.0
scene.add_game_object(crate)

# Eine kinematische Plattform: bewegt sich per velocity, durchdringt alles, ignoriert die Schwerkraft
platform = create_rectangle(300, 250, 120, 16, name="Platform", add_rigidbody=True)
platform_body = platform.get_component(Rigidbody2D)
platform_body.is_kinematic = True
platform_body.velocity.x = 60
scene.add_game_object(platform)

for _ in range(60):                        # eine Sekunde Fallen
    scene.tick(1 / 60)
assert crate_body.is_grounded              # steht auf dem Boden

crate_body.add_impulse(400, 0)             # ein Stoß nach rechts: velocity += 400 / Masse
for _ in range(120):
    scene.tick(1 / 60)
print(crate_body.velocity.x)               # 0.0 — die Reibung hat die Kiste gestoppt

crate_body.teleport(100, 100)              # zurück nach oben, ohne über Frames „verschmiert" zu werden
```

### 5.2. Collider (BoxCollider2D, CircleCollider2D)

**Beschreibung:** Ein Collider legt die Form eines Objekts für Kollisionen (fest) oder für die Berührungserkennung (ein Trigger, `is_trigger=True`) fest. `BoxCollider2D` ist ein Rechteck, die einzige Form, die `Rigidbody2D` als fest auflöst. `CircleCollider2D` prüft die Distanz zum Mittelpunkt exakt (Kreis-Kreis und Kreis-Rechteck), funktioniert aber **nur für Überschneidungen und Trigger** — einen festen Kreis gibt es nicht. Die Geometrie wird als exakte Gleitkommawerte gespeichert (`bounds`); `rect` ist lediglich ein gerundetes `pygame.Rect` zum Zeichnen und für Altcode. **Größe:** Am besten geben Sie `size=(w, h)` explizit an; andernfalls wird sie einmalig aus dem Sprite in `start()` gemessen und dann *fixiert* — ein Wechsel des Animationsbilds ändert die Hitbox nicht (für eine bewusste Größenänderung, etwa beim Ducken, gibt es `set_size`). **Anker** (`anchor`) verwendet dieselben neun Namen wie `SpriteRenderer`: Geben Sie einem Sprite und seinem Collider denselben Anker, damit die Hitbox mit dem Bild übereinstimmt (siehe [9.1](#91-spriterenderer-und-sprite-anker)).

**Events.** Ein festes Objekt, das ein festes Objekt berührt, erzeugt Kollisions-Events, wenn mindestens eine Seite ein `Rigidbody2D` besitzt; alles, was einen Trigger durchquert, erzeugt Trigger-Events. Es gibt zwei Möglichkeiten, sie zu empfangen, beide funktionieren gleichzeitig und für beide Seiten:

- **Handler-Methoden** auf einer beliebigen Komponente eines der beiden Objekte: `on_collision_enter/stay/exit(self, collision)` und `on_trigger_enter/stay/exit(self, other)`;
- **Callback-Listen** am Collider: `collider.on_trigger_enter.append(fn)`, mit der Signatur `fn(eigener_collider, fremder_collider)`.

Wird ein Objekt deaktiviert, entfernt oder zerstört, während es ein anderes berührt, erhält die andere Seite `exit`. Ausnahmen innerhalb von Handlern werden protokolliert, nie ausgelöst; das Zerstören von Objekten innerhalb eines Handlers ist sicher.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `BoxCollider2D(...)` | `size: tuple = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int oder str = None, mask: int oder eine Liste von Ebenen = None` | Ein Rechteck. `size=None` misst aus dem Sprite (einmalig, in `start()`); `offset_x/offset_y` verschieben die Hitbox; `layer=None` verwendet die Ebene des Objekts; `mask=None` kollidiert mit allen Ebenen. |
| `CircleCollider2D(...)` | `radius: float = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int oder str = None, mask: int oder eine Liste von Ebenen = None` | Ein Kreis (nur Überschneidungen und Trigger). `radius=None` ist die halbe längere Seite des Sprites. Der Anker bezieht sich auf ein Quadrat `(Durchmesser, Durchmesser)`. |
| `is_trigger` | `bool` | `True` macht ihn zu einem Sensor ohne physische Reaktion: `collider.is_trigger = True`. |
| `layer`, `mask` | `int`, `int` | Kollisionsebene und -maske (siehe [5.3](#53-kollisionsebenen-und-masken-collision-layers)). |
| `bounds` | `tuple` (Eigenschaft) | Die exakten Weltkoordinaten `(left, top, right, bottom)`. |
| `rect` | `pygame.Rect` (Eigenschaft) | Ein gerundetes Begrenzungsrechteck — zum Zeichnen und Debuggen, nie für die Physik. |
| `is_static` | `bool` (Eigenschaft) | Ob der Collider auf einem statischen Objekt sitzt. |
| `overlaps(other)` | `other: Collider2D` | Ein exakter Formüberschneidungstest: `zone.overlaps(hero_collider)`. |
| `can_collide_with(other)` | `other: Collider2D` | Ob das Paar gemäß den Ebenen-/Maskenregeln interagiert (jede Maske muss die Ebene des anderen erlauben). |
| `contact_normal(other)` | `other: Collider2D` | Die Einheitsnormale `(nx, ny)` von `other` zu diesem Collider. |
| `overlapping_colliders` | `frozenset` (Eigenschaft) | Womit dieser Collider im letzten Physikschritt in Berührung war. |
| `on_trigger_enter/stay/exit` | `eine Liste von fn(collider, other)` | Trigger-Callbacks: Eintreten / Verweilen (jeden Schritt) / Verlassen. |
| `on_collision_enter/stay/exit` | `eine Liste von fn(collider, other)` | Kollisions-Callbacks (benötigt ein `Rigidbody2D` auf mindestens einer Seite). |
| `Collision2D` | `collider, other, normal, game_object` | Das Argument von `on_collision_*(collision)`: `collision.other` ist der andere Collider, `collision.game_object` dessen Objekt, und `collision.normal` die Kontaktnormale vom anderen Objekt zu diesem hin (`(0, −1)` bedeutet „ich wurde von unten getragen"). |
| `BoxCollider2D.size` / `set_size(width, height)` | `width: float, height: float` | Die aktuelle Größe / eine bewusste Größenänderung, die die neue Größe fixiert. |
| `BoxCollider2D.snap_left_to(x)`, `snap_right_to(x)`, `snap_top_to(y)`, `snap_bottom_to(y)` | `x: float` / `y: float` | Verschiebt das `Transform`, sodass diese Kante der Hitbox genau an dieser Weltkoordinate landet. |
| `CircleCollider2D.radius` / `set_radius(radius)` | `radius: float` | Der Radius (nur lesbar) / eine bewusste Größenänderung. `center_x`, `center_y` geben den Weltmittelpunkt des Kreises an. |
| `scene.physics.query_point(x, y, mask, include_triggers)` | `x: float, y: float, mask: int = CollisionLayers.ALL, include_triggers: bool = True` | Collider an einem Punkt: `scene.physics.query_point(210, 360)`. |
| `scene.physics.query_rect(rect, ...)` / `query_bounds(left, top, right, bottom, ...)` | `rect: pygame.Rect` / `left, top, right, bottom: float` (plus dieselben `mask`, `include_triggers`) | Collider, die einen Bereich überschneiden. |

#### Anwendungsbeispiel

```python
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square


class DamageZone(Component):
    """Handler-Methoden: auf jeder Komponente eines der beiden Objekte."""

    def on_trigger_enter(self, other):                # other — der eingetretene Collider
        print(f"{other.game_object.name} ist in die Zone eingetreten")

    def on_trigger_exit(self, other):
        print(f"{other.game_object.name} hat die Zone verlassen")


class LandingLogger(Component):
    def on_collision_enter(self, collision):          # collision — ein Collision2D
        if collision.normal.y < -0.5:                 # von unten getragen
            print("gelandet auf", collision.game_object.name)


scene = Scene("colliders")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

zone = GameObject(200, 340, name="Zone", is_static=True)
zone_collider = zone.add_component(BoxCollider2D(size=(120, 60), is_trigger=True))
zone.add_component(DamageZone())
# Die andere Möglichkeit: eine Callback-Liste, Signatur (eigener_collider, fremder_collider)
zone_collider.on_trigger_enter.append(lambda me, other: print("Callback-Liste:", other.game_object.name))
scene.add_game_object(zone)

hero = create_square(240, 100, size=40, name="Hero", add_rigidbody=True)
hero.add_component(LandingLogger())
scene.add_game_object(hero)

sensor = GameObject(600, 300, name="Sensor", is_static=True)
sensor.add_component(CircleCollider2D(radius=80, is_trigger=True))   # eine kreisförmige Erkennungszone
scene.add_game_object(sensor)

for _ in range(120):                                  # der Held fällt durch die Zone und landet
    scene.tick(1 / 60)

hero_box = hero.get_component(BoxCollider2D)
print(hero_box.bounds)                                # exakte Grenzen (240, 360, 280, 400)
print(hero_box.overlaps(zone_collider))               # True: der Held steht in der Zone
print([c.game_object.name for c in scene.physics.query_point(250, 380)])   # Zone und Hero
```

### 5.3. Kollisionsebenen und Masken (Collision Layers)

**Beschreibung:** Jeder Collider hat eine **Ebene** (`layer`, eine Zahl 0–31 oder ein Name — „was ich bin") und eine **Maske** (`mask`, eine Menge von Ebenen — „womit ich kollidiere"). Zwei Collider interagieren nur, wenn **jede** Maske die Ebene des anderen erlaubt. Nicht passende Paare werden bereits vor dem exakten Überschneidungstest verworfen, was die Ebenentrennung zur günstigsten Methode macht, die Physik zu beschleunigen. Standardmäßig liegt jedes Objekt auf Ebene 0 (`"default"`) und kollidiert mit allem. Ein Collider erbt `layer` von seinem Objekt, sofern er keine eigene besitzt. Ebenen erhalten Namen über `CollisionLayers.register`.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `CollisionLayers.register(name, index)` | `name: str, index: int` | Benennt eine Ebene (0–31; Groß-/Kleinschreibung spielt keine Rolle): `CollisionLayers.register("enemy", 2)`. |
| `CollisionLayers.index(layer)` | `layer: int oder str` | Validiert und löst einen Namen oder eine Zahl zu einem Ebenenindex auf; ein unbekannter Name löst `ValueError` aus. |
| `CollisionLayers.mask(*layers)` | `*layers: int oder str` | Eine Maske aus den angegebenen Ebenen: `CollisionLayers.mask("ground", "enemy")`. |
| `CollisionLayers.name_of(index)` | `index: int` | Der Name der Ebene (oder die Zahl als String, falls sie keinen hat). |
| `CollisionLayers.reset()` | — | Setzt die Namensregistrierung zurück (nur `"default"` bleibt übrig). |
| `CollisionLayers.ALL` / `NONE` / `MAX_LAYERS` | `int` | Die Maske „alle Ebenen" (`0xFFFFFFFF`) / „keine Ebenen" / die Anzahl der Ebenen (32). |
| `GameObject.layer` | `int oder str` | Die Ebene des Objekts: `go.layer = "player"`. |
| `Collider2D.layer` / `Collider2D.mask` | `int` / `int` | Ebene und Maske eines bestimmten Colliders (`mask` kann auch im Konstruktor gesetzt werden). |
| `Collider2D.can_collide_with(other)` | `other: Collider2D` | Prüft ein Paar anhand der Ebenen-/Maskenregeln. |
| `mask` in `scene.physics.query_*`-Aufrufen | `int` | Beschränkt eine Abfrage auf die angegebenen Ebenen. |

#### Anwendungsbeispiel

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.physics.layers import CollisionLayers

CollisionLayers.register("player", 1)
CollisionLayers.register("enemy", 2)
CollisionLayers.register("bullet", 3)
CollisionLayers.register("ground", 4)

scene = Scene("layers")

# Der Spieler kollidiert mit dem Boden und Gegnern — aber nicht mit den eigenen Kugeln
player = GameObject(100, 100, name="Player", layer="player")
player_box = player.add_component(BoxCollider2D(
    size=(32, 48), mask=CollisionLayers.mask("ground", "enemy")))

# Die Kugel des Spielers (ein Trigger): trifft Gegner und den Boden, ignoriert Spieler und andere Kugeln
bullet = GameObject(140, 110, name="Bullet", layer="bullet")
bullet_box = bullet.add_component(BoxCollider2D(
    size=(8, 8), is_trigger=True, mask=CollisionLayers.mask("enemy", "ground")))

enemy = GameObject(300, 100, name="Enemy", layer="enemy")
enemy_box = enemy.add_component(BoxCollider2D(size=(32, 32)))

for go in (player, bullet, enemy):
    scene.add_game_object(go)

print(player_box.can_collide_with(bullet_box))   # False — dieses Paar interagiert nicht
print(bullet_box.can_collide_with(enemy_box))    # True — „bullet" sieht „enemy", und die Standardmaske von „enemy" sieht alle

enemy.layer = "ground"                           # die Ebene kann zur Laufzeit geändert werden
print(CollisionLayers.name_of(enemy.layer))      # ground
```

---

## 6. Eingabesystem (Input)

**Beschreibung:** `Input` ist ein statischer Dienst, der von jeder Komponente aus erreichbar ist, ohne Referenz auf `Engine`. Tasten werden als Strings angegeben (`"space"`, `"w"`, `"left_shift"`, `"mouse_left"`), als `Key.*`-Konstanten oder als rohe `pygame.K_*`-Codes; ein Tippfehler im Tastennamen löst sofort `ValueError` aus, statt stillschweigend nichts zu tun. Das System ist ereignisgesteuert: `Engine` leitet jedes pygame-Event an `Input` weiter, sodass ein Tastendruck, der kürzer als ein Frame ist, nie verloren geht, und der Verlust des Fensterfokus alle gehaltenen Tasten löst. **Innerhalb von `fixed_update` werden die Flanken „gedrückt"/„losgelassen" aus einer separaten Menge gelesen, die nach jedem Physikschritt geleert wird** — so sieht jeder Tastendruck genau einen Physikschritt, egal ob ein Frame zwei Schritte oder gar keinen ausführt. Für gewöhnliche Gameplay-Logik ist es dennoch vorzuziehen, die Eingabe in `update()` zu lesen.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Input.is_key_down(key)` | `key: str, int oder Key` | `True`, solange die Taste gehalten wird: `Input.is_key_down("d")`. |
| `Input.is_key_pressed(key)` | `key: str, int oder Key` | `True` nur in dem Frame (oder Physikschritt), in dem die Taste gedrückt wurde. |
| `Input.is_key_up(key)` | `key: str, int oder Key` | `True` nur in dem Frame, in dem sie losgelassen wurde. |
| `Input.get_axis(negative, positive)` | `negative: str, positive: str` | `-1`, `0` oder `1` aus einem Tastenpaar: `Input.get_axis("a", "d")`. |
| `Input.mouse_position()` | — | `(x, y)` in Bildschirmpixeln. |
| `Input.mouse_world_position()` | — | Die Cursorposition in Weltkoordinaten über die aktive Kamera der Szene (oder `None`, wenn keine Szene existiert). |
| `Input.mouse_delta()` | — | Wie weit sich die Maus seit dem letzten Frame bewegt hat `(dx, dy)`. |
| `Input.mouse_scroll()` / `mouse_scroll_x()` | — | Das Mausrad-Scrollen dieses Frames (vertikal / horizontal). |
| `Input.is_mouse_pressed(button=0)` / `is_mouse_just_pressed(button)` / `is_mouse_just_released(button)` | `button: int` (0 — links, 1 — mittel, 2 — rechts) | Die alte numerische API für Maustasten. |
| `Input.is_pressed(key)` / `is_just_pressed(key)` / `is_just_released(key)` | `key: str, int oder Key` | Alte Namen: `is_pressed` = `is_key_down`, `is_just_pressed` = `is_key_pressed`, `is_just_released` = `is_key_up`. |
| `Key.*` | — | Benannte Konstanten: `Key.W`, `Key.SPACE`, `Key.LEFT`, `Key.F1` usw. — dasselbe wie die Strings, mit Autovervollständigung in der IDE. |
| `Input.inject_key(key, down=True)` / `inject_mouse_position(x, y)` / `inject_scroll(y, x=0)` | — | Simuliert Eingaben ohne echte pygame-Events — praktisch für Tests und Bots. |

#### Anwendungsbeispiel

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.input.input_manager import Input
from engine.input.key import Key


class TopDownMover(Component):
    def __init__(self, speed=220):
        super().__init__()
        self.speed = speed

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)

    def update(self, delta_time):
        x = Input.get_axis("a", "d")               # -1 / 0 / 1 aus stringbasierten Tastennamen
        y = Input.get_axis(Key.W, Key.S)            # dasselbe, aber über Key.*
        self.body.velocity.x = x * self.speed
        self.body.velocity.y = y * self.speed

        if Input.is_key_pressed("space"):           # nur in dem Frame des Tastendrucks
            print("Sprung!")

        if Input.is_mouse_just_pressed(0):           # linke Maustaste
            target = Input.mouse_world_position()
            print("Klick in der Welt:", target)
```

---

## 7. Benutzeroberflächen-System (UI)

### 7.1. Canvas und Screen-Space-UI

**Beschreibung:** UI-Elemente (`UIText`, `UIButton`, `UIPanel`, `UIHealthBar`) sind Komponenten auf einem `GameObject`, genau wie alles andere. Standardmäßig werden sie in **Bildschirmkoordinaten** gezeichnet — nach der Welt, obenauf, ohne Kameraversatz, sodass das HUD beim Scrollen der Ansicht nie „wegdriftet". `Canvas` ist ein optionales Wurzelelement: Es zeichnet selbst nichts, aber `canvas.visible = False` blendet jedes UI-Element aus, das an es als Elternteil angeheftet ist. Ein Element kann auch **weltraumbasiert** gemacht werden (`world_space=True`) — dann wird es zusammen mit der Welt durch die Kamera gezeichnet (etwa eine über einem Gegner schwebende Lebensleiste): Machen Sie dafür das Objekt des UI-Elements zu einem Kind des Objekts, dem es folgen soll.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `UIElement(...)` | `width: int = 100, height: int = 30, visible: bool = True, draw_order: int = 0, anchor: str = None, pivot: str = None, world_space: bool = False` | Die Basisklasse jedes UI-Elements; siehe die Ankerparameter in [7.3](#73-ui-anker-und-pivots). |
| `Canvas(...)` | `sort_order: int = 0, visible: bool = True` | Ein UI-Wurzelcontainer-Element; wird selbst nicht gezeichnet. `visible = False` blendet alle Kinder auf einmal aus. |
| `visible` | `bool` | Ob das Element angezeigt wird. |
| `is_visible` | `bool` (Eigenschaft) | Ob das Element angezeigt wird, **unter Berücksichtigung** der Sichtbarkeit aller UI-Vorfahren. |
| `draw_order` | `int` | Zeichenreihenfolge unter Bildschirmelementen (niedriger wird früher/dahinter gezeichnet); bei Gleichstand bleibt die Einfügereihenfolge erhalten. |
| `world_space` | `bool` | `True` zeichnet das Element in der Welt durch die Kamera, statt in Bildschirmkoordinaten. |
| `rect` | `pygame.Rect` (Eigenschaft) | Das aktuelle Rechteck des Elements in Bildschirmkoordinaten (bei einem weltraumbasierten Element unter Berücksichtigung der Kamera). |
| `contains_point(point_x, point_y)` | `point_x: float, point_y: float` | Ob ein Punkt innerhalb des Rechtecks des Elements liegt: `panel.contains_point(*Input.mouse_position())`. |
| `draw(screen)` | `screen: pygame.Surface` | Der Zeichen-Hook — konkrete Widgets überschreiben ihn. |

#### Anwendungsbeispiel

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.canvas import Canvas
from engine.ui.ui_health_bar import UIHealthBar
from engine.ui.ui_text import UIText


class HUDScene(Scene):
    def start(self):
        super().start()
        hud = GameObject(name="HUD")
        self.canvas = hud.add_component(Canvas())      # ein gemeinsamer Sichtbarkeitsschalter
        self.add_game_object(hud)

        label = GameObject(12, 12, name="ScoreLabel", parent=hud)
        self.score_text = label.add_component(UIText("Punkte: 0", anchor="TopLeft"))

        bar = GameObject(12, 42, name="HealthBar", parent=hud)
        bar.add_component(UIHealthBar(220, 20, max_value=100, anchor="TopLeft"))

    def update(self, delta_time):
        super().update(delta_time)
        from engine.input.input_manager import Input
        if Input.is_key_pressed("h"):
            self.canvas.visible = not self.canvas.visible   # das gesamte HUD auf einmal aus-/einblenden
```

### 7.2. UI-Elemente (UIText, UIButton, UIPanel, UIHealthBar)

**Beschreibung:** Vier fertige Widgets. `UIText` zeichnet einen String (die gerenderte Oberfläche wird zwischengespeichert, sodass erneutes Zeichnen unveränderten Texts kein erneutes Rendern verursacht). `UIButton` ist ein Rechteck mit Beschriftung und einer Liste von `on_click`-Callbacks, das auf Hover und Linksklick reagiert. `UIPanel` ist ein einfacher rechteckiger Hintergrund, oft als Unterlage für andere Elemente verwendet. `UIHealthBar` ist ein füllbarer Balken (Gesundheit, Ausdauer, ein Fortschrittsbalken) mit optionaler Glättung und einer „Schadensspur" (`trail_color`), die den aktuellen Wert einholt. Farben und Schriftart stammen standardmäßig aus `UIStyle.default()`.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `UIText(...)` | `text: str = "", style: UIStyle = None, align: str = "left", width: int = None, height: int = None, **kwargs` | `**kwargs` sind die gemeinsamen `UIElement`-Parameter (`anchor`, `pivot`, `world_space` usw.). `align` ist `"left"`, `"center"` oder `"right"`. Breite/Höhe werden standardmäßig aus dem Text gemessen. |
| `UIText.text` / `set_text(text)` | `text: str` | Der aktuelle Text / seine Änderung: `label.set_text("Fertig")`. |
| `UIButton(...)` | `text: str = "Button", width: int = 140, height: int = 40, style: UIStyle = None, **kwargs` | Eine Schaltfläche mit Beschriftung. |
| `UIButton.on_click` | `eine Liste von fn(button)` | Klick-Callbacks: `button.on_click.append(lambda b: print("geklickt"))`. |
| `UIButton.is_hovered` / `is_pressed` | `bool` | Ob die Maus darüber ist / ob sie gerade gedrückt ist. |
| `UIPanel(...)` | `width: int = 200, height: int = 100, style: UIStyle = None, **kwargs` | Ein rechteckiger Hintergrund. |
| `UIHealthBar(...)` | `width: int = 200, height: int = 20, max_value: float = 100.0, value: float = None, fill_color: tuple = (80,200,90), low_color: tuple = (215,65,65), low_threshold: float = 0.3, trail_color: tuple = None, smooth_speed: float = 0.0, show_text: bool = False, **kwargs` | `low_color` greift bei `ratio <= low_threshold`; `smooth_speed > 0` lässt die Füllung gleiten (Anteil pro Sekunde), statt sofort zu springen; `show_text` zeichnet `"hp/max"` über den Balken. |
| `UIHealthBar.value` / `set_value(v)` | `float` | Der aktuelle Wert. |
| `UIHealthBar.set_max_value(max_value, keep_ratio=False)` | `max_value: float, keep_ratio: bool` | Ändert das Maximum; `keep_ratio=True` behält den Füllanteil bei. |
| `UIHealthBar.bind(getter)` | `getter: ein Callable ohne Argumente` | Liest den Wert jeden Frame aus einer Funktion: `bar.bind(lambda: player_health.hp)`. |
| `UIHealthBar.ratio` / `displayed_ratio` | `float` (Eigenschaften) | Der wahre Füllanteil / der tatsächlich gezeichnete (mit Glättung). |
| `UIStyle(...)` / `UIStyle.default()` | `background_color, border_color, border_width, text_color, font_name, font_size, hover_color, pressed_color` | Der gemeinsame Farb- und Schriftsatz für Widgets; `default()` ist die Fabrik für den Standardstil. |

#### Anwendungsbeispiel

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.canvas import Canvas
from engine.ui.ui_button import UIButton
from engine.ui.ui_health_bar import UIHealthBar
from engine.ui.ui_panel import UIPanel
from engine.ui.ui_style import UIStyle
from engine.ui.ui_text import UIText


class PauseMenuScene(Scene):
    def start(self):
        super().start()
        hud = GameObject(name="PauseMenu")
        hud.add_component(Canvas())
        self.add_game_object(hud)

        panel = GameObject(0, 0, name="Panel", parent=hud)
        panel.add_component(UIPanel(320, 200, anchor="Center",
                                    style=UIStyle(background_color=(25, 25, 35, 220))))

        title = GameObject(0, -60, name="Title", parent=hud)
        title.add_component(UIText("Pause", anchor="Center", align="center"))

        health = GameObject(-140, -10, name="Health", parent=hud)
        bar = health.add_component(UIHealthBar(280, 24, max_value=100, value=65,
                                               anchor="Center", show_text=True,
                                               smooth_speed=2.0, trail_color=(220, 90, 90)))

        resume = GameObject(0, 40, name="Resume", parent=hud)
        button = resume.add_component(UIButton("Fortsetzen", 180, 44, anchor="Center"))
        button.on_click.append(lambda b: print("Spiel wird fortgesetzt"))

        bar.value = 40    # der Balken „holt" den neuen Wert dank smooth_speed sanft auf
```

### 7.3. UI-Anker und Pivots

**Beschreibung:** Neun benannte Anker — `TopLeft`, `TopCenter`, `TopRight`, `MiddleLeft`, `Center`, `MiddleRight`, `BottomLeft`, `BottomCenter`, `BottomRight` (Groß-/Kleinschreibung und Unterstriche spielen keine Rolle: `"top_left"`, `"topleft"`, `"MidTop"` werden alle verstanden). Ohne Anker (`anchor=None`, Standard) ist die Position eines `GameObject`s die obere linke Ecke des Elements in Bildschirmpixeln; bei einem UI-Element als Elternteil relativ zu dessen Rechteck. Mit einem Anker wird die Position des Objekts zu einem **Versatz vom Ankerpunkt** des Referenzrechtecks: dem nächsten UI-Vorfahren, oder dem Bildschirm, falls keiner existiert. `pivot` bestimmt, welcher Punkt *des Elements selbst* auf diesem Ankerpunkt sitzt (standardmäßig identisch mit `anchor`), sodass `anchor="BottomRight"` mit einem Versatz von `(-10, -10)` bei jeder Fenstergröße einen Abstand von 10 Pixeln zur Ecke ergibt.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `UIElement(anchor=..., pivot=...)` | `anchor: str = None, pivot: str = None` | `anchor` legt fest, an welchen Punkt des Referenzrechtecks das Element geheftet ist; `pivot` legt fest, welcher Punkt des Elements dort sitzt (Standard: identisch mit `anchor`). |
| `UIElement.anchor` / `.pivot` | `str oder None` | Kann nach der Erstellung geändert werden: `element.anchor = "BottomRight"`. |
| `normalize_anchor(name)` | `name: str` | Wandelt eine beliebige Schreibweise in den kanonischen Namen um; ein unbekannter löst `ValueError` aus. |
| `VALID_ANCHORS` | `set[str]` | Die neun kanonischen, kleingeschriebenen, leerzeichenfreien Namen: `{"topleft", "midtop", ...}`. |
| `anchor_to_topleft_offset(anchor, width, height)` | `anchor: str, width: float, height: float` | `(dx, dy)` vom Ankerpunkt zur oberen linken Ecke eines Rechtecks dieser Größe — dieselbe Mathematik, die `SpriteRenderer` und die Collider verwenden ([9.1](#91-spriterenderer-und-sprite-anker)). |

#### Anwendungsbeispiel

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.ui_button import UIButton
from engine.ui.ui_text import UIText

scene = Scene("anchors")

# An Bildschirmecken geheftet — unabhängig von der Fenstergröße
top_left = GameObject(10, 10, name="TopLeft")
top_left.add_component(UIText("Oben links", anchor="TopLeft"))
scene.add_game_object(top_left)

bottom_right = GameObject(-10, -10, name="BottomRight")   # negative Werte = Abstand von der Ecke
bottom_right.add_component(UIText("Unten rechts", anchor="BottomRight", pivot="BottomRight"))
scene.add_game_object(bottom_right)

centered = GameObject(0, 0, name="CenterButton")
centered.add_component(UIButton("Zentriert", 160, 40, anchor="Center"))   # pivot ist standardmäßig anchor
scene.add_game_object(centered)

# Verschachtelung: ein Kindelement ankert relativ zu seinem Elternteil, nicht zum Bildschirm
panel = GameObject(0, 0, name="Panel")
panel.add_component(UIButton("Platzhalter", 300, 200, anchor="Center"))
scene.add_game_object(panel)

corner_label = GameObject(-8, -8, name="PanelCorner", parent=panel)
corner_label.add_component(UIText("v1.0", anchor="BottomRight", pivot="BottomRight"))
```

---

## 8. Partikelsystem (Particle System)

**Beschreibung:** `ParticleSystem` ist ein leichtgewichtiger Emitter für Staub, Funken, Explosionen und Spuren. Partikel sind keine `GameObject`s — sie sind kompakte Strukturen, die über einen `ObjectPool` wiederverwendet werden (siehe [10](#10-statische-dienste-und-hilfsfunktionen)): Nach dem „Aufwärmen" belegt kontinuierliche Emission keinen zusätzlichen Speicher und erzeugt keinen Müll für den Garbage Collector. Partikel nehmen nicht an Kollisionen teil. Farbe, Größe und Verblassen sind reine Funktionen des Partikelalters (0…1 von der Geburt bis zum Tod), sodass das System einmalig eine kleine Menge fertiger Oberflächen vorrendert (`lut_steps` Stück) und einen Partikel zeichnet, indem es die passende auswählt plus einem gebündelten Blit — nie „Partikel für Partikel". `color_stops` ergibt einen Verlauf über mehrere Farben; `world_space=True` (Standard) lässt Partikel dort, wo sie erzeugt wurden, auch wenn sich der Emitter weiterbewegt (eine Explosion, eine Spur); `world_space=False` lässt Partikel mit dem Emitter mitfahren (die Flamme einer Fackel).

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `ParticleSystem(...)` | `emission_rate: float = 0.0, lifetime: tuple = (0.5, 1.0), speed: tuple = (50.0, 100.0), direction: float = -90.0, spread: float = 360.0, gravity: float = 0.0, drag: float = 0.0, start_size: float = 6, end_size: float = None, start_color: tuple = (255,255,255), end_color: tuple = None, color_stops: list = None, start_alpha: int = 255, end_alpha: int = 0, shape: str = "circle", sprite: pygame.Surface = None, additive: bool = False, max_particles: int = 500, world_space: bool = True, z_index: int = 10, offset: tuple = (0.0, 0.0), spawn_radius: float = 0.0, duration: float = None, loop: bool = True, play_on_start: bool = True, lut_steps: int = 24, seed: int = None` | `direction`/`spread` sind Winkel in Grad (0 = rechts, „−90" = oben, im Uhrzeigersinn); `additive=True` ergibt additives Blending (Feuer, Funken); `shape` ist `"circle"` oder `"square"`, oder übergeben Sie `sprite` für eine eigene Form; `duration`/`loop` machen die Emission endlich oder endlos. |
| `play()` / `stop(clear=False)` | — / `clear: bool` | Startet kontinuierliche Emission (`emission_rate`) / stoppt sie (`clear=True` entfernt zusätzlich sofort die lebenden Partikel). |
| `burst(count)` / `emit(count)` | `count: int` | Erzeugt `count` Partikel auf einmal (eine Explosion, ein Spritzer) — `emit` ist ein Alias für `burst`. |
| `clear()` | — | Entfernt sofort jeden aktuellen Partikel. |
| `is_playing` | `bool` (Eigenschaft) | Ob kontinuierliche Emission läuft. |
| `particle_count` | `int` (Eigenschaft) | Wie viele Partikel gerade leben. |
| `invalidate()` | — | Baut die Nachschlagetabelle für Farbe/Größe/Alpha neu auf, nachdem diese Parameter zur Laufzeit geändert wurden. |
| `pool` | `ObjectPool` (Eigenschaft) | Der Pool, aus dem die Partikelstrukturen stammen. |

#### Anwendungsbeispiel

```python
from engine.components.particle_system import ParticleSystem
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("particles")

# Ein einmaliger Funkenausbruch (additives Blending, ein Gelb → Orange → Dunkelrot-Verlauf)
sparks_go = GameObject(400, 300, name="Sparks")
sparks = sparks_go.add_component(ParticleSystem(
    play_on_start=False, lifetime=(0.3, 0.6), speed=(120, 260), direction=-90, spread=180,
    gravity=500, start_size=8, end_size=1,
    color_stops=[(255, 246, 170), (255, 150, 40), (120, 40, 20)],
    additive=True, max_particles=200, seed=1,
))
scene.add_game_object(sparks_go)
sparks.burst(24)

# Kontinuierlicher Rauch von einer Fackel: fährt mit dem Objekt mit (world_space=False)
torch_go = GameObject(200, 250, name="TorchSmoke")
smoke = torch_go.add_component(ParticleSystem(
    emission_rate=15, lifetime=(0.8, 1.4), speed=(20, 40), direction=-90, spread=30,
    gravity=-40, start_size=4, end_size=14, color_stops=[(200, 200, 200), (90, 90, 90)],
    start_alpha=160, end_alpha=0, world_space=False, play_on_start=True,
))
scene.add_game_object(torch_go)

for _ in range(60):
    scene.tick(1 / 60)
print("lebende Rauchpartikel:", smoke.particle_count)
```

---

## 9. Grafik, Animation und Rendering

### 9.1. SpriteRenderer und Sprite-Anker

**Beschreibung:** `SpriteRenderer` zeichnet ein `pygame.Surface` an der Weltposition des Objekts, unter Anwendung der Weltrotation und -skalierung des `Transform`. `anchor` verwendet dieselben neun Namen wie die Collider (siehe [7.3](#73-ui-anker-und-pivots) und [5.2](#52-collider-boxcollider2d-circlecollider2d)): Geben Sie einem Sprite und seinem Collider denselben Anker, damit Hitbox und Bild übereinstimmen. `z_index` bestimmt die Reihenfolge der Ebenen (niedriger liegt weiter hinten/früher); innerhalb desselben `z_index` werden Objekte nach `world_y + offset_y` sortiert, was einen günstigen Tiefentrick für Plattformer und Ansichten von oben ergibt. Ein Sprite wird beim ersten Zeichnen in das Anzeigeformat konvertiert (`convert()`/`convert_alpha()`), und rotierte/skalierte Varianten stammen aus einem gemeinsamen Cache (siehe [10](#10-statische-dienste-und-hilfsfunktionen)) — ein statisches Objekt wird nie pro Frame neu berechnet. Welche Objekte für die Kamera sichtbar sind, wird durch Bounds-Culling entschieden (siehe [9.4](#94-tilemap-optimierung-baking)), sodass Sprites außerhalb des Bildschirms gar nicht erst gezeichnet werden.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `SpriteRenderer(...)` | `sprite: pygame.Surface = None, z_index: int = 0, offset_y: float = 0, anchor: str = "topleft", convert: bool = True` | `convert=False` deaktiviert die automatische Konvertierung in das Anzeigeformat (falls die Oberfläche bereits von Hand vorbereitet ist). |
| `sprite` / `set_sprite(sprite)` | `pygame.Surface` | Das aktuelle Sprite / dessen Austausch (wird von `Animator` genutzt, siehe [9.3](#93-animation-und-spritesheets-animator)). |
| `anchor` | `str` | Einer der neun Ankernamen; ein ungültiger Wert protokolliert eine Warnung und fällt auf `"topleft"` zurück. |
| `z_index` | `int` | Die Ebenenreihenfolge. |
| `offset_y` | `float` | Beeinflusst nur den Tiefensortierschlüssel (`world_y + offset_y`), nicht die gezeichnete Position. |
| `is_visible` | `bool` (Eigenschaft) | Ob das Sprite in den letzten Frames gezeichnet wurde — wird von `Animator` genutzt, um Animation außerhalb des Bildschirms zu überspringen. |
| `get_anchor_offset()` | — | `(dx, dy)` von der Position des Objekts zur ursprünglichen oberen linken Ecke des Sprites, gemäß dem Anker. |
| `get_transformed_sprite(rotation, scale_x, scale_y)` | `rotation: float, scale_x: float, scale_y: float` | Das rotierte/skalierte Sprite aus dem gemeinsamen Cache. |
| `get_placement(world_x, world_y, rotation, scale_x, scale_y)` | — | Die endgültige Oberfläche und obere linke Ecke für den Blit, unter Berücksichtigung von Anker, Rotation und Skalierung — wird intern vom Render-System genutzt. |

#### Anwendungsbeispiel

```python
import pygame

from engine.components.box_collider2d import BoxCollider2D
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("sprites")

sprite = pygame.Surface((48, 64), pygame.SRCALPHA)
pygame.draw.rect(sprite, (90, 160, 230), sprite.get_rect(), border_radius=8)

enemy = GameObject(300, 200, name="Enemy")
# Derselbe Anker bei Sprite und Collider — sie stimmen immer visuell überein
enemy.add_component(SpriteRenderer(sprite=sprite, anchor="center", z_index=1))
enemy.add_component(BoxCollider2D(size=sprite.get_size(), anchor="center"))
scene.add_game_object(enemy)

enemy.transform.rotation = 15      # wird um die Mitte des Sprites gedreht gezeichnet
enemy.transform.scale = 1.5        # wird 1,5-fach vergrößert gezeichnet
```

### 9.2. Kamera (Camera)

**Beschreibung:** `Camera` folgt einem `target`, ohne dessen `Transform` zu berühren — stattdessen behält die Kamera ihren eigenen Weltpunkt, den der Render-Durchgang beim Zeichnen von der Position jedes Sprites abzieht. Das verleiht einem Sprung sein natürliches Gefühl: Die „Ansicht" bewegt sich, nicht das Objekt selbst. `smooth_follow=True` (Standard) nähert sich dem Ziel sanft mit der Rate `follow_speed` (exponentielle Glättung — unabhängig von der Bildrate und schießt nie über das Ziel hinaus); `smooth_follow=False` rastet die Kamera jeden Frame exakt auf das Ziel ein. Die Kamera liest die **geglättete** (interpolierte) Position des Ziels, sodass sich auf Monitoren mit hoher Bildwiederholrate Kamera und Sprite des Ziels im Gleichschritt bewegen, ohne Verzögerung zwischen beiden. Ohne Ziel (`target=None`) wird die Welt ganz ohne Versatz gezeichnet — als gäbe es keine Kamera.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Camera(...)` | `target: GameObject = None, follow_speed: float = 5.0, smooth_follow: bool = True, position: Vector2 = None` | `follow_speed` — je höher, desto „schärfer" die Verfolgung; `position` legt einen Startpunkt fest (spielt nur bis `start()` eine Rolle, das sofort auf das Ziel zentriert). |
| `target` | `GameObject oder None` | Das aktuelle Verfolgungsziel. |
| `set_target(target, snap=True)` | `target: GameObject, snap: bool` | Wechselt das Ziel; `snap=True` springt sofort dorthin, `False` nähert sich sanft an. |
| `snap_to_target()` | — | Bewegt sich sofort auf die aktuelle Position des Ziels (nützlich nach einer Teleportation oder einem Respawn). |
| `position` | `Vector2` | Der aktuelle Weltpunkt, der auf dem Bildschirm zentriert wird. |
| `get_offset(screen_width, screen_height)` | `screen_width: int, screen_height: int` | Der Weltpunkt, der in der oberen linken Ecke des Bildschirms landet; `(0, 0)`, falls kein Ziel vorhanden ist. |
| `get_view_bounds(screen_width, screen_height)` | `screen_width: int, screen_height: int` | `(left, top, right, bottom)` des Weltbereichs, der aktuell auf dem Bildschirm sichtbar ist. |
| `world_to_screen(world_pos, w, h)` / `screen_to_world(screen_pos, w, h)` | `Vector2, int, int` | Manuelle Koordinatenumrechnung (üblicherweise ist `Scene.world_to_screen`/`screen_to_world` bequemer, siehe [4.2](#42-szenenverwaltung-scene-und-scenemanager)). |

#### Anwendungsbeispiel

```python
from engine.components.camera import Camera
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_square

scene = Scene("camera")
player = create_square(100, 100, size=40, name="Player", add_rigidbody=True)
scene.add_game_object(player)

camera_go = GameObject(name="MainCamera")
camera = camera_go.add_component(Camera(target=player, follow_speed=6, smooth_follow=True))
scene.add_game_object(camera_go)
scene.set_active_camera(camera)          # ohne diesen Aufruf wird die Welt ohne Versatz gezeichnet

player.transform.position.x += 500       # der Spieler ist weit weg teleportiert
camera.snap_to_target()                  # die Kamera holt sofort auf, ohne Schwenk

visible_left, visible_top, visible_right, visible_bottom = camera.get_view_bounds(1280, 720)
print(f"aktuell sichtbar von x={visible_left:.0f} bis x={visible_right:.0f}")
```

### 9.3. Animation und Spritesheets (Animator)

**Beschreibung:** `Animator` wechselt die Bilder eines `SpriteRenderer` im Zeitverlauf. Die Wiedergabe ist an die reale Zeit gebunden (`dt * speed`), nicht an die Bildrate. `play(name)` ist so konzipiert, dass es sicher **in jedem einzelnen Frame** mit der „beabsichtigten" Animation aufgerufen werden kann: Ein erneuter Aufruf mit demselben Namen setzt sie nicht auf Bild 0 zurück, und eine nicht schleifende (`loop=False`) Animation, die bis zum Ende gespielt hat, bleibt auf ihrem letzten Bild stehen, selbst wenn `play()` weiterhin aufgerufen wird. `force_restart=True` erzwingt einen Neustart ab Bild 0. Wurde eine schleifende Animation in den letzten paar Frames nicht gezeichnet (das Objekt ist außerhalb des Bildschirms), **läuft sie einfach nicht weiter** — hundert Gegner außerhalb des Sichtfelds kosten nichts. Nicht schleifende Animationen und solche mit `on_finished`-Abonnenten laufen immer weiter, sodass Gameplay-Logik („die Angriffsanimation ist beendet") auch außerhalb des Bildschirms auslöst. `load_spritesheet_animations()` baut einen Satz Animationen direkt aus einem Spritesheet plus einem JSON-Atlas auf (die Formate `"hash"` und `"array"`, wie bei TexturePacker verwendet), wobei Bilder nach dem numerischen Index im Dateinamen sortiert werden statt alphabetisch (sonst würde `"walk_10"` vor `"walk_2"` einsortiert).

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Animator(...)` | `animations: dict = None, default_animation: str = None, frame_duration: float = 0.1, speed: float = 1.0, cull_offscreen: bool = True` | `animations` ist ein Dict `{"name": [surface, surface, ...]}`. |
| `play(anim_name=None, loop=True, reverse=False, force_restart=False)` | `anim_name: str, loop: bool, reverse: bool, force_restart: bool` | Sicher in jedem Frame aufrufbar — siehe Beschreibung oben. |
| `pause()` / `stop()` | — | Auf dem aktuellen Bild anhalten / anhalten und auf das erste Bild zurücksetzen. |
| `has_animation(anim_name)` | `anim_name: str` | Ob diese Animation im Dictionary existiert — nützlich, um auf eine Standardanimation zurückzufallen. |
| `set_animations(animations)` | `animations: dict` | Ersetzt den gesamten Animationssatz (Bilder werden einmalig konvertiert). |
| `is_playing`, `current_animation`, `frame_index` | `bool`, `str`, `int` | Der aktuelle Zustand des Players. |
| `on_finished` | `eine Liste von fn(animator, anim_name)` | Feuert einmal, wenn eine nicht schleifende Animation ihr letztes Bild erreicht. |
| `load_spritesheet_animations(json_path, image_path, generate_flipped=True)` | `json_path: str, image_path: str, generate_flipped: bool` | Gibt `{name: [surface, ...]}` für `Animator` zurück. `generate_flipped=True` erzeugt zusätzlich eine gespiegelte Version jeder Animation mit dem Präfix `_` (z. B. `"idle"` → `"_idle"`). |

#### Anwendungsbeispiel

```python
import pygame

from engine.components.animator import Animator
from engine.components.sprite_renderer import SpriteRenderer
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.utils.spritesheet_loader import load_spritesheet_animations


def make_frame(color):
    surface = pygame.Surface((32, 32), pygame.SRCALPHA)
    pygame.draw.rect(surface, color, surface.get_rect())
    return surface


scene = Scene("animation")
hero = GameObject(150, 150, name="Hero")
hero.add_component(SpriteRenderer(sprite=make_frame((90, 160, 230))))

# Option 1: eine Animation aus fertigen Bildern (Surfaces), von Hand erstellt
idle_frames = [make_frame((90, 160, 230)), make_frame((100, 170, 240))]
animator = hero.add_component(Animator({"idle": idle_frames}, default_animation="idle",
                                       frame_duration=0.2))
scene.add_game_object(hero)

animator.play("idle")            # sicher, dies in update() jeden Frame aufzurufen

# Option 2: eine Animation aus einem Spritesheet + JSON-Atlas (bei vorhandenen assets/hero.png/.json)
# animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
# hero.get_component(Animator).set_animations(animations)
```

### 9.4. Tilemap-Optimierung (Baking)

**Beschreibung:** Das Zeichnen tausender statischer Tiles bedeutet tausende `blit()`-Aufrufe, jeden Frame, für immer. Baking zeichnet sie **einmalig**, beim Laden der Ebene, auf eine große Oberfläche (oder mehrere „Chunk"-Oberflächen bei einer riesigen Karte); jeder folgende Frame kostet dann nur einen Blit pro sichtbarem Chunk — üblicherweise ein bis vier. `bake_tilemap()` baut ein statisches `GameObject` direkt aus einem Raster von Tile-IDs und einem `{id: surface}`-Dictionary auf. `bake_static_sprites()` bäckt die statischen, nicht animierten `SpriteRenderer`, die **bereits** zur Szene hinzugefügt wurden, und deaktiviert die ursprünglichen Komponenten (Collider und Gameplay-Skripte auf denselben Objekten funktionieren weiterhin wie gewohnt). Transluzente Sprites werden im vormultiplizierten Alpha-Raum gebacken, sodass sich überlappende Transluzenz bis auf Rundungsfehler mit dem pixelgenauen Zeichnen deckt. Gebackene Pixel sind „eingefroren" (sie bewegen oder animieren sich nie) und teilen sich eine einzige Ebene bei ihrem `z_index`.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `bake_tilemap(grid, tileset, tile_size, origin=(0,0), z_index=-100, chunk_size=None, opaque=False, background=(0,0,0), name="BakedTilemap")` | `grid: list[list[int]], tileset: dict oder list, tile_size: int oder tuple, origin: tuple, z_index: int, chunk_size: int, opaque: bool, name: str` | Baut ein statisches `GameObject` mit einer gebackenen Ebene aus einem Raster von Tile-IDs auf (`None`/`-1` ist eine leere Zelle). Gibt das Objekt zurück — fügen Sie es selbst zur Szene hinzu. |
| `bake_static_sprites(scene, chunk_size=None, z_range=None, opaque=False, name_prefix="Baked")` | `scene: Scene, chunk_size: int, z_range: tuple, opaque: bool` | Bäckt jedes geeignete statische Sprite, das bereits in der Szene ist, eine Ebene pro `z_index`. Gibt die Liste der neuen Ebenenobjekte zurück. |
| `BakedLayer(z_index=-100, chunk_size=None, opaque=False, background=(0,0,0))` | — | Die Komponente der gebackenen Ebene (normalerweise über die obigen Funktionen erstellt, nicht direkt). |
| `BakedLayer.bake(items)` | `items: eine Liste von (surface, x, y)` | Bäckt eine beliebige Menge von Bildern an gegebenen Weltkoordinaten. |
| `BakedLayer.chunk_count` | `int` (Eigenschaft) | Wie viele Chunk-Oberflächen tatsächlich erstellt wurden (nur dort, wo etwas gezeichnet ist). |
| `BakedLayer.premultiplied_supported()` | — (statische Methode) | Ob exaktes Transluzenz-Blending auf diesem pygame-Build verfügbar ist. |

#### Anwendungsbeispiel

```python
import pygame

from engine.core.scene import Scene
from engine.primitives import create_square
from engine.rendering.tilemap import BakedLayer, bake_static_sprites, bake_tilemap


def tile(color):
    surface = pygame.Surface((32, 32))
    surface.fill(color)
    return surface


scene = Scene("tilemap")

# Option 1: direkt aus einem Raster von Tile-IDs
grid = [
    [1, 1, 1, 1, 1],
    [1, None, None, None, 1],   # None ist eine leere Zelle (-1 funktioniert auch; NICHT 0 — 0 ist eine gewöhnliche id)
    [1, 1, 1, 1, 1],
]
tileset = {1: tile((110, 80, 50))}
ground = bake_tilemap(grid, tileset, tile_size=32, origin=(0, 300), z_index=-50)
scene.add_game_object(ground)
print("gebackene Tiles:", ground.get_component(BakedLayer).item_count)

# Option 2: bereits in der Szene liegende gewöhnliche statische Sprites backen
for i in range(200):
    deco = create_square(i * 34, 500, size=30, color=(70, 130, 70), name=f"Grass{i}",
                         add_collider=False, is_static=True)
    scene.add_game_object(deco)

layers = bake_static_sprites(scene)      # hunderte Gras-Blits -> eine Handvoll Chunk-Blits
print("erstellte gebackene Ebenen:", len(layers))
```

---

## 10. Statische Dienste und Hilfsfunktionen

Jeder Dienst in diesem Abschnitt ist von überall in Ihrem Code aus erreichbar — importieren Sie einfach die Klasse, keine Referenz auf `Engine` oder `Scene` nötig.

### Time

**Beschreibung:** Die globale Uhr der Engine. `fixed_delta_time` ist die Länge eines Physikschritts (standardmäßig 1/60 s, änderbar über `Engine(fixed_fps=...)` oder `Time.set_fixed_rate(hz)`); `alpha` ist der Anteil (0…1) des Fortschritts zwischen den letzten beiden Physikschritten, verwendet von der Render-Interpolation (siehe [4.4](#44-die-transform-hierarchie)); `time_scale = 0` pausiert das Spiel (Schwerkraft und Gameplay stoppen beide).

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Time.delta_time` / `unscaled_delta_time` | `float` | Der variable Frame-Schritt, mit `time_scale` skaliert und unskaliert. |
| `Time.fixed_delta_time` | `float` | Die Länge eines Physikschritts. |
| `Time.time` / `unscaled_time` / `fixed_time` | `float` | Akkumulierte Spielzeit. |
| `Time.time_scale` | `float` | Ein Multiplikator für die Geschwindigkeit des gesamten Spiels; `0` pausiert es. |
| `Time.alpha` | `float` | 0…1 zwischen Physikschritten — für die Interpolation. |
| `Time.frame_count` / `fixed_frame_count` | `int` | Zähler für Frames und Physikschritte. |
| `Time.set_fixed_rate(hz)` | `hz: float` | Ändert die Physikrate: `Time.set_fixed_rate(120)`. |
| `Time.reset()` | — | Setzt alle Werte auf ihre Standardwerte zurück (in Tests verwendet). |

#### Anwendungsbeispiel

```python
from engine.core.game_time import Time

Time.time_scale = 0.0     # Pause: Physik und update() werden weiterhin aufgerufen, aber dt = 0
Time.time_scale = 0.5     # halbe Geschwindigkeit
print(f"Frame Nr. {Time.frame_count}, Physikschritt {Time.fixed_delta_time * 1000:.2f} ms")
```

### EventBus

**Beschreibung:** Ein globaler Publish/Subscribe-Bus, dazu ein separater Bus auf jedem `GameObject` (`go.events`) — die eigenen Events eines Objekts erreichen nie globale Abonnenten, und umgekehrt. `owner=` bindet ein Abonnement an einen Besitzer (`Scene`, `GameObject`): Wird dieser zerstört, entfernen `Scene.destroy()`/`GameObject.destroy()` automatisch alle seine Abonnements, wodurch manuelles Abbestellen entfällt und Lecks verhindert werden. Eine Ausnahme innerhalb eines Handlers wird über `Debug` protokolliert, und die übrigen Handler laufen trotzdem weiter.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `EventBus.subscribe(event, callback, owner=None, once=False, priority=0, weak=False)` | `event: str, callback: callable, owner: ein beliebiges Objekt, once: bool, priority: int, weak: bool` | Abonniert ein globales Event; `weak=True` hält den Callback über eine schwache Referenz (ein zerstörter Listener bestellt sich selbst ab). |
| `EventBus.emit(event, *args, **kwargs)` | `event: str, *args, **kwargs` | Benachrichtigt Abonnenten: `EventBus.emit("game_over", score=120)`. |
| `EventBus.unsubscribe(event, callback)` / `unsubscribe_owner(owner)` | — | Bestellt einen bestimmten Callback ab / entfernt alle Abonnements eines Besitzers auf einmal. |
| `EventBus.once(event, callback, **kwargs)` | — | Feuert einmal, bestellt sich dann selbst ab. |
| `EventBus.has_listeners(event)` / `listener_count(event=None)` | — | Ob es Abonnenten gibt / wie viele. |
| `go.events` | `EventDispatcher` | Der private Bus eines Objekts: `player.events.subscribe("jumped", hud.on_jump)`. |

#### Anwendungsbeispiel

```python
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("events")
EventBus.subscribe("coin_collected", lambda amount: print(f"+{amount} Punkte"), owner=scene)

player = GameObject(name="Player")
scene.add_game_object(player)
player.events.subscribe("jumped", lambda height: print(f"{height} px hoch gesprungen"))

EventBus.emit("coin_collected", amount=10)      # der globale Abonnent hört dies
player.events.emit("jumped", height=64)         # nur der Abonnent dieses Objekts hört es

scene.destroy()          # das Abonnement der scene auf "coin_collected" wird automatisch entfernt
```

### ObjectPool und GameObjectPool

**Beschreibung:** Die Wiederverwendung von Objekten statt sie ständig neu zu erstellen und zu verwerfen — das vermeidet Ruckler des Garbage Collectors bei häufigem Spawnen (Kugeln, Partikel, fliegender Text). `ObjectPool` ist ein generischer Pool für beliebige, über eine Fabrikfunktion erstellte Objekte; `GameObjectPool` spezialisiert dies für `GameObject`s innerhalb einer bestimmten `Scene`: inaktive Objekte bleiben in der Szene, sind aber deaktiviert (`active=False`), sodass Spawnen nur das Umlegen eines Flags bedeutet, ohne die eigenen Listen der Szene zu verändern. Komponenten können `on_spawn(**kwargs)` / `on_despawn()` implementieren, um ihren eigenen Zustand zurückzusetzen (`Rigidbody2D` stoppt sich automatisch selbst).

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `ObjectPool(factory, on_spawn=None, on_despawn=None, initial_size=0, max_size=None, name="ObjectPool")` | `factory: ein Callable ohne Argumente` | Ein generischer Pool. `initial_size` legt fest, wie viele im Voraus erstellt werden („Aufwärmen"). |
| `GameObjectPool(scene, factory, initial_size=0, max_size=None, name="GameObjectPool", clear_events_on_despawn=False)` | `scene: Scene, factory: ein Callable, das ein fertiges GameObject zurückgibt` | Ein Pool von Objekten für eine Szene. |
| `spawn(*args, **kwargs)` (`ObjectPool`) / `spawn(x=None, y=None, **kwargs)` (`GameObjectPool`) | — | Gibt ein Objekt aus dem Pool heraus (oder erstellt ein neues, falls keines frei ist); `None`, wenn `max_size` erreicht ist. `**kwargs` werden an `on_spawn` der Komponenten übergeben. |
| `despawn(obj)` | `obj` | Gibt ein Objekt an den Pool zurück. Bei einem `GameObject` bewirkt `go.despawn()` dasselbe. |
| `despawn_all()` | — | Gibt jedes aktuell aktive Objekt an den Pool zurück. |
| `prewarm(count)` | `count: int` | Erstellt `count` Objekte im Voraus, ohne sie zu aktivieren. |
| `active_count` / `free_count` | `int` (Eigenschaften) | Wie viele Objekte aktuell ausgegeben / im Pool frei sind. |

#### Anwendungsbeispiel

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.core.object_pool import GameObjectPool
from engine.core.scene import Scene

scene = Scene("pooling")


def make_bullet():
    go = GameObject(name="Bullet")
    go.add_component(BoxCollider2D(size=(6, 6), is_trigger=True))
    go.add_component(Rigidbody2D(use_gravity=False, is_kinematic=True))
    return go


bullets = GameObjectPool(scene, make_bullet, initial_size=16, max_size=64)

bullet = bullets.spawn(x=100, y=200)             # verwendet ein freies Pool-Objekt wieder
if bullet is not None:
    bullet.get_component(Rigidbody2D).velocity.x = 500

for _ in range(90):
    scene.tick(1 / 60)

bullet.despawn()                                  # an den Pool zurückgeben, nicht destroy()
print("frei im Pool:", bullets.free_count, "/ ausgegeben:", bullets.active_count)
```

### PlayerPrefs

**Beschreibung:** Ein Speicher im Unity-Stil für Einstellungen und Spielstände, gestützt auf eine einzige JSON-Datei (standardmäßig `playerprefs.json` im Arbeitsverzeichnis). Werte sind typisiert: Der Aufruf von `get_int` auf einem Schlüssel, der tatsächlich einen String enthält, gibt den Standardwert zurück, keinen Fehler. `save()` schreibt atomar (über eine temporäre Datei), sodass ein Absturz mitten im Schreibvorgang nie eine beschädigte Datei hinterlassen kann; kann eine vorhandene Datei dennoch nicht geparst werden, wird sie in `*.corrupt` umbenannt, der Fehler wird protokolliert, und das Spiel läuft mit einem leeren Speicher weiter. `Engine` speichert nicht gespeicherte Änderungen beim Beenden automatisch.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `PlayerPrefs.set_path(path)` / `get_path()` | `path: str` | Eine andere Datei verwenden (verwirft nicht gespeicherte Änderungen). |
| `set_int(key, value)` / `get_int(key, default=0)` | `key: str, value: int, default: int` | Ganzzahlen: `PlayerPrefs.set_int("high_score", 4200)`. |
| `set_float(key, value)` / `get_float(key, default=0.0)` | `key: str, value: float, default: float` | Gleitkommazahlen. |
| `set_string(key, value)` / `get_string(key, default="")` | `key: str, value: str, default: str` | Strings. |
| `has_key(key)` / `delete_key(key)` / `delete_all()` | `key: str` | Prüft, ob ein Schlüssel existiert / löscht einen Wert / leert den gesamten Speicher. |
| `save()` | — | Schreibt atomar auf die Festplatte. Bis zu diesem Aufruf landet nichts auf der Festplatte. |
| `reload()` | — | Verwirft nicht gespeicherte Änderungen und liest die Datei erneut ein. |
| `is_dirty()` | — | Ob es nicht gespeicherte Änderungen gibt. |

#### Anwendungsbeispiel

```python
from engine.core.player_prefs import PlayerPrefs

PlayerPrefs.set_path("saves/profile.json")

PlayerPrefs.set_int("high_score", 4200)
PlayerPrefs.set_string("player_name", "Georgii")
PlayerPrefs.set_float("music_volume", 0.6)
PlayerPrefs.save()                              # vor dieser Zeile wird nichts auf die Festplatte geschrieben

print(PlayerPrefs.get_int("high_score"))        # 4200
print(PlayerPrefs.get_int("no_such_key", 0))    # 0 — der Standardwert
```

### AudioManager und AudioSource

**Beschreibung:** `AudioManager` verwaltet Musik, Soundeffekte, Lautstärke und Positionsklang; zwei Kanäle sind für Musik reserviert („zwei Decks"), sodass ein Crossfade die Titel wirklich überlappt und ein Soundeffekt nie den Musikkanal stehlen kann. Überblendungen laufen innerhalb von `update(dt)` und blockieren nie. Effektive Lautstärke = Master × (sfx oder music) × die eigene Lautstärke der Quelle × Distanzabschwächung, jeden Frame neu berechnet — das Verschieben eines Reglers wirkt sich also sofort auf bereits spielende Klänge aus. Positionsklänge (`position=(x, y)`) blenden linear zwischen `min_distance` und `max_distance` um den Hörer aus (standardmäßig die aktive Kamera) und werden nach horizontalem Versatz gepannt. `AudioSource` ist die Komponente für Klang, der an ein Objekt gebunden ist (`spatial=True` lässt ihn dem Objekt folgen). Ohne Audiogerät wird alles nur protokolliert und hindert das Spiel nicht am Laufen.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `AudioManager.play_music(path, loop=True, fade_in=0.0, volume=1.0)` | `path: str` | Startet einen Titel und bricht den vorherigen ab (mit einem Einblenden, falls `fade_in` gesetzt ist). |
| `AudioManager.crossfade_to(path, duration=2.0, loop=True, volume=1.0)` | `path: str, duration: float` | Wechselt sanft die Titel, wobei während des Übergangs beide gleichzeitig spielen. |
| `AudioManager.stop_music(fade_out=0.0)` / `pause_music()` / `resume_music()` | — | Musik stoppen (mit Ausblenden) / pausieren / fortsetzen. |
| `AudioManager.play_sfx(sound, volume=1.0, loop=False, position=None, min_distance=100.0, max_distance=800.0, rolloff="linear")` | `sound: str oder pygame.mixer.Sound, position: tuple` | Ein einmaliger oder schleifender Soundeffekt; `position` aktiviert Distanzabschwächung und Panning. |
| `AudioManager.set_master_volume(v)` / `set_sfx_volume(v)` / `set_music_volume(v)` | `v: float, 0..1` | Drei unabhängige Lautstärkeregler. |
| `AudioManager.mute()` / `unmute()` / `toggle_mute()` / `is_muted()` | — | Globale Stummschaltung. |
| `AudioManager.load_sound(path, cache=True)` | `path: str` | Lädt und cacht einen Klang im Voraus, um eine Pause bei der ersten Wiedergabe zu vermeiden. |
| `AudioManager.save_settings(prefix="audio.")` / `load_settings(prefix="audio.")` | `prefix: str` | Speichert/lädt die drei Lautstärkeregler über `PlayerPrefs`. |
| `AudioSource(path=None, volume=1.0, loop=False, play_on_start=False, spatial=False, min_distance=100.0, max_distance=800.0)` | — | Ein Komponenten-Wrapper um `AudioManager` für ein bestimmtes Objekt. |
| `AudioSource.play()` / `stop()` / `pause()` / `resume()` | — | Wiedergabesteuerung. |
| `AudioSource.load(path)` / `set_volume(v)` | `path: str` / `v: float` | Klang ändern / Lautstärke ändern. |

#### Anwendungsbeispiel

```python
from engine.audio.audio_manager import AudioManager
from engine.components.audio_source import AudioSource
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("audio")

AudioManager.play_music("assets/theme.ogg", fade_in=1.5, volume=0.5)
AudioManager.set_sfx_volume(0.8)

torch = GameObject(400, 300, name="Torch")
source = torch.add_component(AudioSource("assets/fire_loop.ogg", loop=True,
                                         play_on_start=True, spatial=True, max_distance=500))
scene.add_game_object(torch)

AudioManager.play_sfx("assets/coin.wav", volume=0.7, position=(420, 280))   # ein einmaliger Positionsklang
AudioManager.crossfade_to("assets/battle.ogg", duration=2.0)                # ein sanfter Titelwechsel
```

### Debug

**Beschreibung:** Ein zentraler Ort für Protokollierung und Debug-Overlays. `Debug` ist ein Alias für `DebugManager` (`Debug.log(...)`, im Stil von Unitys `Debug.Log`). Die eingebauten Overlays werden mit Funktionstasten umgeschaltet (über `debug.keys` neu zuweisbar): **F1** — Statistik (FPS, Frame-Zeit, Anzahl der Entitäten, Zeichenaufrufe, Physikzähler), **F2** — Collider-Umrisse und Geschwindigkeitsvektoren, **F3** — ein Weltkoordinatengitter, **F4** — eine scrollbare Konsole mit den letzten Protokolleinträgen. `Engine(debug=False)` deaktiviert alle Hotkeys und Overlays auf einmal — für einen Release-Build.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Debug.log(message, source=None)` | `message: beliebig, source: str` | Ein gewöhnlicher Protokolleintrag: `Debug.log("Level geladen")`. |
| `Debug.log_warning(message, source=None)` / `log_error(message, source=None)` | — | Eine Warnung / ein Fehler (unterschiedliche Farben in der F4-Konsole). |
| `Debug.log_exception(exc, source=None)` | `exc: Exception` | Protokolliert eine Ausnahme als Fehler. |
| `Debug.clear_logs()` | — | Löscht die Protokollhistorie. |
| `debug.set_stat(name, value)` | `name: str, value: beliebig oder None` | Fügt dem F1-Overlay eine eigene Zeile hinzu (`None` entfernt sie). |
| `debug.toggle_overlay()` / `toggle_colliders()` / `toggle_grid()` / `toggle_console()` | — | Schaltet eines der vier Overlays programmatisch um. |
| `debug.keys` | `dict` | Weist Hotkeys neu zu: `debug.keys["console"] = "grave"`. |

#### Anwendungsbeispiel

```python
from engine.core.debug_manager import Debug

Debug.log("Spiel gestartet")
Debug.log_warning("Textur nicht gefunden, Platzhalter wird verwendet")
try:
    1 / 0
except ZeroDivisionError as exc:
    Debug.log_exception(exc, source="Start")
```

### Vector2 und Hilfsfunktionen

**Beschreibung:** `Vector2` ist ein minimaler 2D-Vektor, der überall dort verwendet wird, wo man sonst ein `x`/`y`-Paar mitführen müsste (Position, Geschwindigkeit, ein Kameraversatz). `engine.primitives` bietet schnelle Fabrikfunktionen für fertige `GameObject`s (Rechteck, Quadrat, Kreis, Dreieck, Linie) mit einem Sprite und optional einem Collider und einem `Rigidbody2D` — praktisch für Prototyping, ohne eigene Bilder vorbereiten zu müssen.

#### API und Methoden

| Methode / Eigenschaft | Signatur / Parameter | Beschreibung und Anwendungsbeispiel |
| :--- | :--- | :--- |
| `Vector2(x=0.0, y=0.0)` | `x: float, y: float` | Unterstützt `+`, `-`, unäres `-`, `*`/`/` mit einer Zahl, `+=`, `-=`, `==`. |
| `copy()` | — | Eine unabhängige Kopie. |
| `length()` | — | Die Länge des Vektors (`math.hypot`). |
| `normalized()` | — | Ein Vektor derselben Richtung, Länge 1 (ein Nullvektor bleibt `(0, 0)`, keine Division durch null). |
| `lerp(other, t)` | `other: Vector2, t: float` | Lineare Interpolation; `t` wird auf `[0, 1]` begrenzt. |
| `as_tuple()` / `as_int_tuple()` | — | Ein einfaches `(x, y)`, oder auf Ganzzahlen gerundet. |
| `Vector2.zero()` / `Vector2.one()` | — (statisch) | Schnelle `(0, 0)` und `(1, 1)`. |
| `create_rectangle(x=0, y=0, width=50, height=50, color=(200,200,200), name="Rectangle", add_collider=True, add_rigidbody=False, border_radius=0, is_static=False, layer=0)` | — | Ein fertiges rechteckiges `GameObject`. |
| `create_square(x=0, y=0, size=50, ..., is_static=False, layer=0)` | — | Dasselbe für ein Quadrat (Seitenlänge `size`). |
| `create_circle(x=0, y=0, radius=25, ..., precise_collider=False, is_static=False, layer=0)` | — | Ein Kreis; `precise_collider=True` gibt ihm einen `CircleCollider2D` statt einer quadratischen Näherungs-Hitbox. |
| `create_triangle(x=0, y=0, size=50, ..., is_static=False, layer=0)` / `create_line(x=0, y=0, length=100, thickness=4, ..., vertical=False, is_static=False, layer=0)` | — | Ein Dreieck, das in ein Quadrat `size×size` eingeschrieben ist, und ein Linienabschnitt (horizontal oder vertikal). |

#### Anwendungsbeispiel

```python
from engine.core.scene import Scene
from engine.primitives import create_circle, create_rectangle
from engine.utils.vector2 import Vector2

start = Vector2(0, 0)
end = Vector2(300, 150)
midpoint = start.lerp(end, 0.5)          # Vector2(150.0, 75.0)
direction = (end - start).normalized()

scene = Scene("primitives")
platform = create_rectangle(0, 400, 300, 30, color=(90, 70, 50), is_static=True)
ball = create_circle(150, 100, radius=20, color=(230, 90, 90), add_rigidbody=True)
scene.add_game_object(platform)
scene.add_game_object(ball)
```
