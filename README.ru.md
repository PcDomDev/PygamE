# PygamE — 2D Engine (ECS Framework)

> **PygamE** — компактный 2D-движок и фреймворк на базе **Pygame** с компонентной архитектурой (ECS в стиле Unity: `GameObject` + `Component`) для разработки 2D-игр и интерактивных приложений. Из коробки: детерминированная физика с фиксированным шагом (swept-AABB, слои и маски, колбэки столкновений и триггеров), иерархия трансформаций с интерполяцией отрисовки, Screen-Space UI с якорями, частицы на пулах объектов, тайлмапы с запеканием, камера, анимации, звук с кроссфейдом и позиционированием, а также статические сервисы (`Input`, `EventBus`, `PlayerPrefs`, `Debug`). Архитектурные преимущества: физика не зависит от FPS, отрисовка и симуляция платят только за то, что видно и что движется, сцену безопасно менять прямо во время кадра, единственная зависимость — Pygame.

## Оглавление

1. [Обзор и архитектурные принципы](#1-обзор-и-архитектурные-принципы)
2. [Требования и установка](#2-требования-и-установка)
3. [Быстрый старт (Quick Start)](#3-быстрый-старт-quick-start)
4. [Каркас движка и жизненный цикл](#4-каркас-движка-и-жизненный-цикл)
   - 4.1. [Engine и главный цикл](#41-engine-и-главный-цикл)
   - 4.2. [Управление сценами (Scene и SceneManager)](#42-управление-сценами-scene-и-scenemanager)
   - 4.3. [GameObject и компонентная модель](#43-gameobject-и-компонентная-модель)
   - 4.4. [Иерархия трансформаций (Transform)](#44-иерархия-трансформаций-transform)
5. [Физическая система (Physics)](#5-физическая-система-physics)
   - 5.1. [Rigidbody2D](#51-rigidbody2d)
   - 5.2. [Коллайдеры (BoxCollider2D, CircleCollider2D)](#52-коллайдеры-boxcollider2d-circlecollider2d)
   - 5.3. [Слои и маски столкновений (Collision Layers)](#53-слои-и-маски-столкновений-collision-layers)
6. [Система ввода (Input)](#6-система-ввода-input)
7. [Система пользовательского интерфейса (UI)](#7-система-пользовательского-интерфейса-ui)
   - 7.1. [Canvas и Screen-Space UI](#71-canvas-и-screen-space-ui)
   - 7.2. [UI-элементы (UIText, UIButton, UIPanel, UIHealthBar)](#72-ui-элементы-uitext-uibutton-uipanel-uihealthbar)
   - 7.3. [Сетка якорей (UI Anchors & Pivots)](#73-сетка-якорей-ui-anchors-pivots)
8. [Система частиц (Particle System)](#8-система-частиц-particle-system)
9. [Графика, анимация и рендеринг](#9-графика-анимация-и-рендеринг)
   - 9.1. [SpriteRenderer и якоря спрайтов](#91-spriterenderer-и-якоря-спрайтов)
   - 9.2. [Камера (Camera)](#92-камера-camera)
   - 9.3. [Анимации и спрайтшиты (Animator)](#93-анимации-и-спрайтшиты-animator)
   - 9.4. [Оптимизация тайлмапов (Baking)](#94-оптимизация-тайлмапов-baking)
10. [Статические сервисы и утилиты](#10-статические-сервисы-и-утилиты)

## 1. Обзор и архитектурные принципы

PygamE построен вокруг одной идеи: **мир состоит из объектов, а поведение объектов — из подключаемых компонентов**. `GameObject` не умеет ни рисоваться, ни падать, ни реагировать на клавиши — всё это делают компоненты, которые вы к нему прикрепляете.

| Роль в ECS | Что это в PygamE | Ответственность |
| :--- | :--- | :--- |
| **Entity (сущность)** | `GameObject` | Именованный контейнер: `Transform`, список компонентов, флаги `active` / `is_static` / `layer`, иерархия «родитель — потомок». |
| **Component (компонент)** | `Component` и его наследники: `SpriteRenderer`, `Rigidbody2D`, `BoxCollider2D`, `Animator`, `PlayerController`, `Camera`, `ParticleSystem`, `UIText`… | Данные и поведение. Ваш игровой код — тоже компоненты (`class Enemy(Component)`). |
| **System (система)** | `PhysicsWorld` и `RenderSystem` (создаются каждой `Scene`), статические сервисы `Input`, `AudioManager`, `EventBus`… | Сквозная логика над множеством компонентов: физика, отрисовка, звук, события. |
| **Scene (сцена)** | `Scene` | Владеет объектами и системами. Индексы (по типам компонентов, по порядку обновления) поддерживаются инкрементально. |
| **Engine (движок)** | `Engine` | Окно, часы и главный цикл. |

> **О терминах.** «ECS» в PygamE — это компонентная модель в стиле Unity (компонент хранит и данные, и поведение), а не data-oriented ECS с «голыми» данными и отдельными системами.

### Архитектурные принципы

1. **Два ритма времени.** Физика идёт в `fixed_update` с фиксированным шагом (по умолчанию 60 Гц), геймплей, анимации и камера — в `update` с переменным `dt`. При просадке FPS физика делает несколько шагов подряд, а не «растягивает» один: результат зависит только от *числа шагов*, а не от частоты кадров.
2. **Интерполяция отрисовки.** Между физическими шагами позиции тел интерполируются (`Time.alpha`), поэтому движение остаётся плавным на мониторах 144 Гц и выше.
3. **Глобальный порядок обновления.** `Component.update_order` действует на всю сцену, а не внутри одного объекта: физика (−100) → коллайдеры (−90) → геймплей (0) → камера (100). Камера всегда видит окончательные позиции кадра.
4. **Платите только за используемое.** Сцена вызывает только *переопределённые* хуки; статические объекты (`is_static=True`) не участвуют в физике и пересчётах; отрисовываются только видимые камере спрайты; тайлмапы запекаются в несколько блитов.
5. **Безопасность во время кадра.** `GameObject.destroy()`, `Scene.remove_game_object()` и `SceneManager.change_scene()`, вызванные из `update`, колбэка столкновения или клика по кнопке, применяются в конце текущей фазы — цикл обхода никогда не ломается.
6. **Статические сервисы.** `Input`, `Time`, `EventBus`, `AudioManager`, `PlayerPrefs`, `Debug`, `SceneManager`, `CollisionLayers` доступны из любого места без ссылки на `Engine`.
7. **Предсказуемые координаты.** Единицы — пиксели, ось Y направлена вниз, углы — в градусах по часовой стрелке.

### Кадр движка

```text
Engine.run()
 └─ каждый кадр:
     ├─ события pygame → Input; горячие клавиши отладки (F1–F4)
     ├─ SceneManager.update(dt) → Scene.tick(dt)
     │    ├─ 0…N раз: Scene.fixed_update(1/60)
     │    │     ├─ Component.fixed_update()   (приложить силы)
     │    │     └─ PhysicsWorld.step()        (движение → контакты → колбэки)
     │    ├─ Scene.update(dt)                 (Component.update() по update_order)
     │    └─ отложенные удаления и смена сцены
     ├─ AudioManager.update(dt)               (затухания, громкость)
     └─ отрисовка: фон → Scene.draw() [мир через камеру → UI поверх] → оверлеи отладки → flip
```

### Ключевые возможности

- **Физика:** fixed timestep, swept-AABB без туннелирования и дрожания, гравитация / ускорение / трение / сопротивление / масса, слои и маски, события `enter` / `stay` / `exit` для столкновений и триггеров. → [раздел 5](#5-физическая-система-physics)
- **Сцены и объекты:** жизненный цикл `start` / `update` / `fixed_update` / `draw` / `destroy`, иерархия трансформаций с кэшем (`is_dirty`), отложенное удаление. → [раздел 4](#4-каркас-движка-и-жизненный-цикл)
- **Рендеринг:** отсечение по камере, пространственная сетка, запекание тайлмапов, кэш повёрнутых и масштабированных спрайтов, пропуск анимаций вне экрана. → [раздел 9](#9-графика-анимация-и-рендеринг)
- **UI:** Screen-Space Canvas, `UIText` / `UIButton` / `UIPanel` / `UIHealthBar`, девять якорей и опорные точки, UI в мировых координатах. → [раздел 7](#7-система-пользовательского-интерфейса-ui)
- **Частицы:** эмиттер на `ObjectPool`, градиенты цвета, масштаб, затухание. → [раздел 8](#8-система-частиц-particle-system)
- **Сервисы:** `Input` со строковыми именами клавиш, `EventBus` (глобальный и на уровне объекта), `ObjectPool`, `PlayerPrefs`, `AudioManager`, `Debug`. → [раздел 10](#10-статические-сервисы-и-утилиты)

---

## 2. Требования и установка

**Требования**

| Компонент | Версия |
| :--- | :--- |
| Python | 3.8+ (движок не использует синтаксис новее 3.8; тестировался на 3.12) |
| pygame | 2.x (тестировался на 2.6.1) |
| Прочие зависимости | нет |

**Установка**

```bash
git clone https://github.com/PcDomDev/PygamE.git PygamE
cd PygamE

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux / macOS: source .venv/bin/activate

pip install -r requirements.txt     # или просто: pip install pygame
```

**Структура проекта**

```text
engine/                    сам движок — не зависит от игры
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
└── primitives.py            фабрики create_rectangle / square / circle / triangle / line
tests/                     test_engine.py — тесты без окна · benchmark.py — замеры
examples/                  showcase.py — демо-уровень, использующий все системы
main.py                    точка входа вашей игры
requirements.txt
```

Импорты всегда идут от корня проекта: `from engine.core.app import Engine`. `engine/` ничего не знает о вашей игре — код игры живёт снаружи.

### Проверка установки (Smoke Test)

Скрипт ниже не открывает окно и не требует звуковой карты (используются «пустые» драйверы SDL): он создаёт сцену, роняет тело на пол и проверяет, что физика отработала. Сохраните его как `smoke_test.py` в **корне проекта** и запустите.

```python
# smoke_test.py — проверка установки PygamE без окна и звуковой карты
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # без окна
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # без звука

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

for _ in range(180):                 # 3 секунды симуляции при 60 кадрах в секунду
    scene.tick(1 / 60)

assert body.is_grounded, "тело должно приземлиться на пол"
assert abs(ball.transform.world_y - 180) < 1e-6, ball.transform.world_y   # верх пола 200 − высота 20
print("PygamE работает: тело приземлилось на y =", ball.transform.world_y)
```

```bash
python smoke_test.py                     # ожидается строка «PygamE работает: ...»
python -m unittest discover tests        # полный набор тестов; ожидается «OK»
python examples/showcase.py              # играбельное демо (окно)
python examples/showcase.py --headless 300 shot.png   # то же без окна, со скриншотом
```

Если `smoke_test.py` завершился без ошибки, установка корректна: Python, pygame и движок работают вместе.

---

## 3. Быстрый старт (Quick Start)

Минимальная игра: платформер с двойным прыжком, монетами, камерой и счётчиком. Сохраните как `main.py` в корне проекта.

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
        super().start()                       # обязательно: запускает всё, что уже добавлено
        self.score = 0

        # Земля и платформа — статичные: не участвуют в физике и пересчётах
        self.add_game_object(create_rectangle(-1000, 500, 3000, 60, color=(96, 72, 48),
                                              name="Ground", is_static=True))
        self.add_game_object(create_rectangle(420, 380, 180, 24, color=(120, 90, 60),
                                              name="Platform", is_static=True))

        # Игрок: тело с гравитацией + управление
        player = create_square(100, 300, size=40, color=(70, 130, 230), name="Player",
                               add_rigidbody=True)
        player.get_component(Rigidbody2D).gravity = 900
        player.add_component(PlayerController(speed=240, jump_force=460,
                                              movement_type="platformer", max_jumps=2))
        self.add_game_object(player)

        # Монеты — триггеры: проходимы, но сообщают о касании
        for x, y in ((300, 460), (470, 340), (540, 340), (700, 460)):
            coin = create_circle(x, y, radius=12, color=(255, 210, 60), name="Coin",
                                 precise_collider=True, is_static=True)
            collider = coin.get_component(CircleCollider2D)
            collider.is_trigger = True
            collider.on_trigger_enter.append(self.on_coin_touched)
            self.add_game_object(coin)

        # Камера следует за игроком
        camera_object = GameObject(name="Camera")
        camera = camera_object.add_component(Camera(target=player, follow_speed=6))
        self.add_game_object(camera_object)
        self.set_active_camera(camera)

        # HUD: якорь привязывает текст к углу экрана
        hud = GameObject(12, 12, name="HUD")
        self.score_text = hud.add_component(UIText("Монеты: 0", anchor="TopLeft"))
        self.add_game_object(hud)

    def on_coin_touched(self, coin_collider, other_collider):
        if other_collider.game_object.name == "Player":
            coin_collider.game_object.destroy()     # безопасно прямо внутри колбэка
            self.score += 1
            self.score_text.set_text(f"Монеты: {self.score}")


def main():
    engine = Engine(1280, 720, "PygamE — быстрый старт", fps=144,
                    background_color=(120, 172, 226))
    engine.change_scene(GameScene)            # создаёт сцену, вызывает start()
    engine.run()


if __name__ == "__main__":
    main()
```

```bash
python main.py
```

**Управление:** `A` / `D` или `←` / `→` — движение, `Space` — прыжок (второй раз — в воздухе), `Esc` закрывает окно, если вы обработаете его сами (см. [Input](#6-система-ввода-input)). **Отладка:** `F1` — статистика, `F2` — коллайдеры, `F3` — сетка мира, `F4` — консоль логов.

Что здесь произошло:

1. `Engine` открыл окно и запустил главный цикл ([4.1](#41-engine-и-главный-цикл)).
2. `change_scene(GameScene)` создал сцену и вызвал `start()`, где мы собрали мир из `GameObject` ([4.2](#42-управление-сценами-scene-и-scenemanager), [4.3](#43-gameobject-и-компонентная-модель)).
3. Физика идёт фиксированным шагом, `PlayerController` читает ввод каждый кадр ([5.1](#51-rigidbody2d), [Input](#6-система-ввода-input)).
4. Монета — статичный триггер: колбэк вызывается при касании ([5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)).
5. Камера следует за игроком, а HUD остаётся на месте — UI рисуется в экранных координатах ([9.2](#92-камера-camera), [7.1](#71-canvas-и-screen-space-ui)).

---

## 4. Каркас движка и жизненный цикл

### 4.1. Engine и главный цикл

**Описание:** `Engine` владеет окном, часами и главным циклом — единственный класс, который нужен `main.py`. Каждый кадр он передаёт события в `Input`, обрабатывает горячие клавиши отладки, вызывает `SceneManager.update()` (фиксированные шаги физики, затем переменный `update`), обновляет звук и рисует сцену. Физика от FPS не зависит: `fps` ограничивает только частоту отрисовки, а `fixed_fps` задаёт частоту физики. При выходе `Engine` уничтожает активную сцену (вызываются `on_destroy`), останавливает звук, сохраняет несохранённые `PlayerPrefs` и завершает pygame.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Engine(...)` | `width: int = 1280, height: int = 720, title: str = "Pygame Engine", fps: int = 60, background_color: tuple = (30, 30, 35), fixed_fps: int = 60, vsync: bool = False, resizable: bool = False, debug: bool = True` | Создаёт окно и подсистемы. `fps=0` — без ограничения кадров; `fixed_fps` — частота физики в Гц; `vsync=True` просит вертикальную синхронизацию (включает флаг `SCALED`); `resizable` разрешает менять размер окна; `debug=False` отключает горячие клавиши и оверлеи отладки (релизная сборка). |
| `run()` | — | Блокирующий главный цикл. Завершается при закрытии окна или `quit()`. Вызывайте последним: `engine.run()`. |
| `quit()` | — | Останавливает цикл после текущего кадра: `engine.quit()`. |
| `load_scene(name, scene)` | `name: str, scene: Scene` | Регистрирует готовый экземпляр сцены под именем и сразу делает его активной; предыдущая сцена остаётся жить (см. [4.2](#42-управление-сценами-scene-и-scenemanager)). |
| `change_scene(target, *args, **kwargs)` | `target: класс Scene, экземпляр Scene или имя сцены` | Уничтожает текущую сцену и запускает новую: `engine.change_scene(Level1, difficulty=2)`. Обёртка над `SceneManager.change_scene`. |
| `active_scene` | `Scene или None` (свойство) | Текущая активная сцена. |
| `screen` | `pygame.Surface` | Поверхность окна. |
| `clock` | `pygame.time.Clock` | Часы главного цикла. |
| `input` / `debug` / `audio` | `Input` / `DebugManager` / `AudioManager` | Подсистемы, которыми владеет движок (те же экземпляры, что и статические сервисы). |
| `scene_manager` | `SceneManager` | Статический менеджер сцен (сам класс). |
| `width`, `height`, `fps`, `background_color`, `running` | `int`, `int`, `int`, `tuple`, `bool` | Параметры окна и флаг работы цикла. |
| `Engine.MAX_DELTA_TIME` | `float = 0.05` | Верхняя граница переменного `dt` в `update` (защита от скачка после паузы отладчика). На физику не влияет: у неё свой предел — `Time.max_frame_time` и `Time.max_fixed_steps`. |

#### Пример использования

```python
import pygame

from engine.core.app import Engine
from engine.core.debug_manager import Debug
from engine.core.scene import Scene


class DemoScene(Scene):
    def start(self):
        super().start()
        self.elapsed = 0.0
        Debug.log("Сцена запущена")

    def update(self, delta_time):
        super().update(delta_time)          # без super() компоненты не обновятся
        self.elapsed += delta_time
        if self.elapsed > 3.0:              # закрыть окно через 3 секунды
            pygame.event.post(pygame.event.Event(pygame.QUIT))


def main():
    engine = Engine(
        width=1280, height=720, title="Демо",
        fps=0,                # без лимита кадров (или vsync=True)
        fixed_fps=60,         # физика всегда 60 шагов в секунду
        resizable=True,
        debug=True,           # F1–F4 работают; False — для релиза
    )
    engine.change_scene(DemoScene)
    engine.run()


if __name__ == "__main__":
    main()
```

### 4.2. Управление сценами (Scene и SceneManager)

**Описание:** `Scene` — коллекция `GameObject` плюс системы, которые ими управляют: `physics` (`PhysicsWorld`) и `render_system` (`RenderSystem`). Хуки жизненного цикла: `start()` (один раз при загрузке), `update(dt)` (каждый кадр), `fixed_update(dt)` (каждый физический шаг), `draw(screen)` и `destroy()` (при выходе). Базовые `update` / `fixed_update` / `draw` **и запускают ваши компоненты**, поэтому в наследнике всегда вызывайте `super()`. `SceneManager` — статический менеджер: `SceneManager.change_scene(Level1Scene)` уничтожает текущую сцену (`destroy()` освобождает объекты, подписки и структуры физики и рендеринга — старая сцена собирается сборщиком мусора) и запускает новую (`start()`). Если смена запрошена *во время кадра* (клик по кнопке, колбэк столкновения), она откладывается до конца кадра; в остальное время (старт программы, тесты) выполняется сразу.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Scene(name)` | `name: str = "Scene"` | Создаёт пустую сцену. Имя по умолчанию заменяется именем класса при загрузке через `SceneManager`. |
| `start()` | — | Хук: вызывается один раз при загрузке. Стройте мир здесь и вызывайте `super().start()`. |
| `update(delta_time)` | `delta_time: float` | Хук: переменный шаг; запускает `update` компонентов в порядке `update_order`, затем применяет отложенные удаления. |
| `fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Хук: один физический шаг — сначала `fixed_update` компонентов, затем `physics.step()` и колбэки столкновений. |
| `draw(screen)` | `screen: pygame.Surface` | Хук: рисует мир через камеру, затем UI. `render(screen)` — прежнее имя, перенаправляет сюда. |
| `destroy()` | — | Хук: уничтожает все объекты и очищает системы сцены. Вызывается менеджером при выходе из сцены. |
| `add_game_object(go)` | `go: GameObject` | Добавляет объект **вместе с потомками** и сразу запускает его: `scene.add_game_object(player)`. |
| `remove_game_object(go)` | `go: GameObject` | Убирает объект из сцены, не уничтожая его. Внутри цикла — откладывается до конца фазы. |
| `destroy_game_object(go)` | `go: GameObject` | Уничтожает объект (`on_destroy`, потомки, подписки). То же делает `go.destroy()`. |
| `find_game_object(name)` | `name: str` | Первый объект с таким именем или `None`. |
| `find_game_objects_with_tag(tag)` | `tag: str` | Список объектов с тегом. |
| `get_components(component_type)` | `component_type: type` | Все живые компоненты типа (включая наследников) на активных объектах — новый список, безопасный для обхода: `scene.get_components(UIButton)`. |
| `get_component(component_type)` | `component_type: type` | Первый компонент типа или `None`. |
| `set_active_camera(camera)` | `camera: Camera` | Назначает камеру, через которую рисуется мир. Свойство `active_camera` возвращает её. |
| `screen_to_world(pos)` / `world_to_screen(pos)` | `pos: tuple или Vector2` | Перевод координат через активную камеру: `scene.screen_to_world(Input.mouse_position())`. |
| `tick(frame_dt)` | `frame_dt: float` | Один кадр симуляции без окна: накопление времени, 0…N шагов `fixed_update`, затем `update`. Для тестов и инструментов. Возвращает число выполненных физических шагов. |
| `game_objects`, `physics`, `render_system` | `list`, `PhysicsWorld`, `RenderSystem` | Список объектов сцены и её системы. |
| `entity_count`, `active_entity_count`, `draw_calls` | `int` | Всего объектов, активных объектов, вызовов отрисовки в последнем кадре. |
| `is_started`, `is_destroyed`, `name` | `bool`, `bool`, `str` | Состояние жизненного цикла и имя. |
| `SceneManager.change_scene(...)` | `target, *args, immediate: bool = None, destroy_previous: bool = True, **kwargs` | Смена сцены: `target` — класс `Scene`, экземпляр или зарегистрированное имя; `*args` / `**kwargs` идут в конструктор класса. Возвращает новую сцену, а если смена отложена до конца кадра — `None`. `immediate=True/False` принудительно задаёт способ. |
| `SceneManager.register(name, scene_or_class)` | `name: str, scene_or_class: Scene или type` | Регистрирует сцену или класс: `SceneManager.register("menu", MenuScene)`, затем `change_scene("menu")` создаёт свежий экземпляр каждый раз. |
| `SceneManager.add_scene(name, scene)` / `set_active(name)` | `name: str, scene: Scene` | Прежний API: регистрация и переключение **без** уничтожения предыдущей сцены (её состояние сохраняется, `start()` вызывается только при первой активации). |
| `SceneManager.get_scene(name)` / `remove_scene(name)` | `name: str` | Получить зарегистрированный экземпляр / забыть его и уничтожить. |
| `SceneManager.active_scene` | `Scene или None` | Активная сцена. |
| `SceneManager.shutdown()` / `reset()` | — | Уничтожить активную сцену (вызывает `Engine` при выходе) / забыть всё (тесты). |

#### Пример использования

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
        title.add_component(UIText("Моя игра", anchor="Center"))
        self.add_game_object(title)

        play = GameObject(0, 0, name="PlayButton")
        button = play.add_component(UIButton("Играть", 200, 48, anchor="Center"))
        # Клик происходит внутри кадра — смена сцены применится в его конце
        button.on_click.append(lambda _button: SceneManager.change_scene(LevelScene, level=1))
        self.add_game_object(play)


class LevelScene(Scene):
    def __init__(self, level=1):
        super().__init__(f"Level{level}")
        self.level = level

    def start(self):
        super().start()
        print(f"Уровень {self.level} загружен")

    def destroy(self):
        print(f"Уровень {self.level} выгружен")
        super().destroy()


SceneManager.register("menu", MenuScene)     # по имени: каждый раз новый экземпляр
SceneManager.change_scene("menu")            # до запуска цикла — выполняется сразу
SceneManager.change_scene(LevelScene, level=2)   # выгрузит меню, загрузит уровень 2
# В игре кадры прокручивает Engine.run(); здесь — один кадр вручную:
SceneManager.update(1 / 60)
```

### 4.3. GameObject и компонентная модель

**Описание:** `GameObject` — контейнер с обязательным `Transform`; поведение добавляется компонентами (`add_component`). Компоненты наследуют `Component` и переопределяют только нужные хуки — сцена вызывает **лишь переопределённые**, поэтому неиспользуемый хук ничего не стоит. Флаги объекта: `active` (неактивный не обновляется, не участвует в физике и рисовании — как и все его потомки, см. `active_in_hierarchy`), `is_static` (объект не будет двигаться: пропускает физику и пересчёты, коллайдер и спрайт регистрируются один раз; чтобы сдвинуть такой объект, сначала выставьте `is_static = False`) и `layer` (слой столкновений). `update_order` задаёт порядок запуска компонентов **глобально по всей сцене**.

| Компонент | `update_order` |
| :--- | :---: |
| `Rigidbody2D` | −100 |
| `BoxCollider2D` / `CircleCollider2D` | −90 |
| ваш геймплей, `Animator`, `PlayerController`, UI | 0 |
| `Camera` | 100 |

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `GameObject(...)` | `x: float = 0.0, y: float = 0.0, name: str = "GameObject", layer: int или str = 0, tag: str = None, is_static: bool = False, parent: GameObject = None` | Создаёт объект с `Transform` в точке `(x, y)`. `parent` сразу подцепляет его к родителю. |
| `add_component(component)` | `component: Component` | Прикрепляет компонент и возвращает его: `body = go.add_component(Rigidbody2D())`. Если объект уже в сцене, компонент запускается сразу. |
| `get_component(cls)` / `get_components(cls)` / `has_component(cls)` | `cls: type` | Первый компонент типа (или `None`) / список всех / проверка наличия. Ищите соседей в `start()`, а не в `__init__`. |
| `remove_component(component)` | `component: Component` | Отсоединяет компонент (вызывается его `on_destroy`). `Transform` удалить нельзя. |
| `transform` | `Transform` | Всегда доступен, проверять на `None` не нужно. |
| `name`, `tag` | `str`, `str` | Имя и тег для поиска (`scene.find_game_object("Player")`). |
| `active` / `active_in_hierarchy` | `bool` | Свой флаг / «активен сам и все предки». |
| `is_static` | `bool` | Не будет двигаться — см. описание выше. |
| `layer` | `int или str` | Слой столкновений, по умолчанию наследуется коллайдерами: `go.layer = "enemy"` (см. [5.3](#53-слои-и-маски-столкновений-collision-layers)). |
| `parent` / `children` | `GameObject или None` / `list` | Иерархия; `children` — список потомков. |
| `set_parent(parent, keep_world_position=False)` | `parent: GameObject или None, keep_world_position: bool` | Меняет родителя (подробнее в [4.4](#44-иерархия-трансформаций-transform)). `add_child(child)` и `find_child(name)` — сокращения. |
| `x`, `y` | `float` | Псевдонимы локальной позиции: `go.x += 5`. |
| `scene` | `Scene или None` | Сцена, в которой объект сейчас находится. |
| `events` | `EventDispatcher` | Личная шина событий объекта (см. [EventBus](#eventbus)): `go.events.emit("hit", damage=5)`. `clear_events()` снимает подписки. |
| `destroy()` | — | Уничтожает объект и потомков. Внутри цикла отложено до конца фазы, поэтому безопасно из колбэков. Вызывается `on_destroy` всех компонентов. |
| `despawn()` | — | Вернуть в пул (если объект из `GameObjectPool`), иначе `destroy()`. |
| `Component.start()` | — | Хук: один раз при входе в сцену. Ищите здесь соседние компоненты. |
| `Component.update(delta_time)` | `delta_time: float` | Хук: каждый кадр, переменный шаг. Ввод, анимация, визуальная логика. |
| `Component.fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Хук: каждый физический шаг, **до** шага физики — место для `add_force`. |
| `Component.draw_world(screen, offset_x, offset_y, alpha)` | `screen: Surface, offset_x: int, offset_y: int, alpha: float` | Хук: собственная отрисовка в мировых координатах (частицы, запечённые слои). Верните число блитов (или `None`). |
| `Component.on_destroy()` | — | Хук: при уничтожении объекта или удалении компонента — освободите ресурсы. |
| `on_collision_enter/stay/exit(collision)` | `collision: Collision2D` | Необязательные методы-обработчики физики на любом компоненте (см. [5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)). |
| `on_trigger_enter/stay/exit(other)` | `other: Collider2D` | То же для триггеров. |
| `game_object`, `transform`, `events` | — | Владелец компонента и его `Transform` / шина событий (ярлыки). |
| `enabled` | `bool` | `False` — компонент не получает `update` / `fixed_update`. |
| `update_order`, `updates_when_static` | `int = 0`, `bool = True` | Порядок запуска (таблица выше). `updates_when_static = False` пропускает компонент на статичных объектах. |

#### Пример использования

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_square


class Spinner(Component):
    """Вращение — визуальный эффект, поэтому update (каждый кадр)."""

    def __init__(self, degrees_per_second=90):
        super().__init__()
        self.degrees_per_second = degrees_per_second

    def update(self, delta_time):
        self.game_object.transform.rotation += self.degrees_per_second * delta_time


class Thruster(Component):
    """Силы прикладывают в fixed_update — прямо перед шагом физики."""

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)   # соседей ищем в start()

    def fixed_update(self, fixed_delta_time):
        self.body.add_force(0, -1200)       # тяга вверх сильнее гравитации (500 px/s²)


class SelfDestruct(Component):
    def __init__(self, seconds):
        super().__init__()
        self.left = seconds

    def update(self, delta_time):
        self.left -= delta_time
        if self.left <= 0:
            self.game_object.destroy()      # отложено до конца фазы — безопасно

    def on_destroy(self):
        print(f"{self.game_object.name} уничтожен")


scene = Scene("components")
rocket = create_square(200, 300, size=30, name="Rocket", add_rigidbody=True)
rocket.tag = "projectile"
rocket.add_component(Thruster())
rocket.add_component(Spinner(180))
rocket.add_component(SelfDestruct(2.0))
scene.add_game_object(rocket)

for _ in range(150):                         # 2.5 секунды симуляции
    scene.tick(1 / 60)
assert scene.find_game_object("Rocket") is None      # самоуничтожился
```

### 4.4. Иерархия трансформаций (Transform)

**Описание:** `Transform` создаётся автоматически для каждого `GameObject` и хранит позицию, поворот и масштаб. Значения бывают **локальными** (относительно родителя — это то, что хранится) и **мировыми** (результат композиции всей цепочки родителей). `position` — псевдоним `local_position`; у объекта без родителя локальные и мировые значения совпадают, поэтому код без иерархии работает как раньше. Поворот в градусах по часовой стрелке (Y вниз). Мировые значения кэшируются за флагом `is_dirty`: изменение помечает грязными сам transform и его поддерево, а чтение мирового значения пересчитывает его только если оно грязное — неподвижная иерархия ничего не пересчитывает. Отслеживаются и правки «на месте» (`position.x += 5`). Для физических тел `get_render_xy(alpha)` даёт сглаженную позицию между двумя шагами; потомки строятся от сглаженной позиции родителя, поэтому оружие в руках игрока не «отстаёт».

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Transform(...)` | `x: float = 0.0, y: float = 0.0, rotation: float = 0.0, scale_x: float = 1.0, scale_y: float = 1.0` | Создаётся автоматически внутри `GameObject`. |
| `position` / `local_position` | `Vector2` | Локальная позиция; допускает правку на месте: `t.position.x += 10`. |
| `rotation` / `local_rotation` | `float` | Локальный поворот в градусах. |
| `scale` / `local_scale` | `Vector2` (можно присвоить число) | Локальный масштаб: `t.scale = 2`. Коллайдер масштаб не меняет. |
| `world_position` | `Vector2` (копия), присваивается | Мировая позиция. Копию править бесполезно — присваивайте: `t.world_position = Vector2(0, 0)`. |
| `world_rotation`, `world_scale` | `float`, `Vector2` | Мировые поворот и масштаб (только чтение). |
| `world_x`, `world_y`, `get_world_xy()` | `float`, `float`, `tuple` | Быстрые чтения мировой позиции без копирования. |
| `set_world_position(x, y)` | `x: float, y: float` | Ставит мировую позицию (пересчитывает локальную). |
| `translate(dx, dy)` | `dx: float, dy: float` | Сдвиг в пространстве родителя. |
| `teleport(x, y)` | `x: float, y: float` | Перенос без интерполяции: сглаживание не «растягивает» прыжок между кадрами. |
| `parent` | `Transform или None` | Родитель (присваивание вызывает `set_parent`). |
| `set_parent(parent, keep_world_position=False)` | `parent: Transform, GameObject или None, keep_world_position: bool` | Меняет родителя. По умолчанию сохраняется локальное смещение; `keep_world_position=True` оставляет объект на месте в мире. Цикл (родитель ← потомок) отвергается с `ValueError`. |
| `detach(keep_world_position=True)` | `keep_world_position: bool` | Отцепляет от родителя. |
| `children`, `child_count`, `root`, `depth` | `tuple`, `int`, `Transform`, `int` | Навигация по иерархии. |
| `transform_point(x, y)` / `inverse_transform_point(x, y)` | `x: float, y: float` | Точка из локального пространства в мировое и обратно: `t.transform_point(30, 0)`. |
| `is_dirty`, `world_version` | `bool`, `int` | Кэш мировых значений: устарел ли он и сколько раз пересчитывался. |
| `interpolate` | `bool` | Включает сглаживание между физическими шагами (`Rigidbody2D` включает его сам). |
| `get_render_xy(alpha)` / `render_position` | `alpha: float` | Позиция для отрисовки с интерполяцией; `render_position` берёт `Time.alpha`. |
| `reset_interpolation()` | — | «Предыдущая позиция := текущая»: следующий кадр рисуется точно там, где объект стоит. |

#### Пример использования

```python
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square
from engine.utils.vector2 import Vector2

scene = Scene("hierarchy")

player = create_square(200, 300, size=40, name="Player", add_rigidbody=True)
sword = create_rectangle(0, 0, 30, 8, color=(220, 220, 230), name="Sword", add_collider=False)

sword.set_parent(player)                  # меч — потомок игрока
sword.transform.position.x = 40           # 40 px справа от игрока (локально)
sword.transform.rotation = -30            # поворот относительно родителя
scene.add_game_object(player)             # потомок попадает в сцену вместе с родителем

print(sword.transform.get_world_xy())     # (240.0, 300.0): родитель + смещение
player.transform.position.x += 100        # игрок сдвинулся — меч поехал следом
print(sword.transform.get_world_xy())     # (340.0, 300.0)

world = sword.transform.world_position    # копия: править её бесполезно
sword.transform.world_position = Vector2(500, 100)   # а так — можно (мировые координаты)

sword.set_parent(None, keep_world_position=True)     # отцепить, не сдвигая в мире
player.transform.teleport(500, 100)       # перенос без сглаживания
```

---

## 5. Физическая система (Physics)

Физика PygamE — это `Rigidbody2D` (движение) + коллайдеры (форма) + `PhysicsWorld` (система, которую создаёт каждая сцена). Всё идёт в `fixed_update` с шагом `Time.fixed_delta_time` (по умолчанию 1/60 с). Порядок одного шага: `fixed_update` компонентов → обновление коллайдеров, сдвинутых скриптами → симуляция каждого тела → поиск контактов → колбэки (`exit`, затем `enter`, затем `stay`). Широкая фаза — равномерная сетка (`SpatialHash`): статичные коллайдеры регистрируются один раз, а запросы порождают только подвижные.

### 5.1. Rigidbody2D

**Описание:** Компонент, который двигает объект: скорость, ускорение, гравитация, сопротивление, трение и масса. Движение разрешается **по одной оси за раз со «сканированием» пути (swept AABB)**: тело проходит ровно до ближайшего препятствия и останавливается вплотную. Поэтому нет туннелирования на любых скоростях, нет дрожания при приземлении, а `is_grounded` стабилен (покой на поверхности — контакт с нулевым зазором). Тело, начавшее шаг внутри твёрдого объекта (появилось или было телепортировано), выталкивается по оси наименьшего проникновения. Порядок внутри шага: силы, ускорение и гравитация → сопротивление (`exp(-drag·dt)` по обеим осям) → трение на земле (`friction · |gravity|` px/с² по горизонтали) → предел скорости падения → выталкивание → движение по X → движение по Y. Единицы: пиксели и секунды.

> **Ограничения.** Твёрдые препятствия — только `BoxCollider2D` (круги работают лишь как триггеры). Тела воспринимают друг друга как неподвижные стены (без передачи импульса). Кинематические платформы не «перевозят» стоящие на них тела. Размещайте `Rigidbody2D` на корневых объектах: у потомка он работает в локальном пространстве родителя (движengine предупредит в логе).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Rigidbody2D(...)` | `gravity: float = 500, gravity_scale: float = 1.0, drag: float = 0.0, mass: float = 1.0, use_gravity: bool = True, is_kinematic: bool = False, terminal_velocity: float = 1000, friction: float = 0.0, acceleration: tuple или Vector2 = None, interpolate: bool = True` | Создаёт тело. `gravity` (px/с²) и `gravity_scale` задают падение; `drag` — сопротивление среды (1/с); `friction` — коэффициент трения об землю; `mass` делит силы и импульсы; `terminal_velocity` ограничивает скорость падения; `acceleration` — постоянное ускорение (ветер, тяга); `is_kinematic` — двигается только по `velocity`, столкновения не разрешает, но события шлёт; `interpolate` — плавная отрисовка между шагами. Все параметры доступны и как атрибуты. |
| `velocity` | `Vector2` | Скорость в px/с. Правится напрямую: `body.velocity.x = 200`. `velocity_x` / `velocity_y` — скалярные псевдонимы. |
| `acceleration` | `Vector2` | Постоянное ускорение в px/с². |
| `is_grounded` | `bool` | `True`, если тело опирается на поверхность снизу (обновляется каждый шаг). |
| `collider` | `BoxCollider2D или None` | Коллайдер, найденный в `start()`; без него гравитация работает, но столкновений нет (будет предупреждение в логе). |
| `add_impulse(impulse_x, impulse_y)` | `impulse_x: float, impulse_y: float` | Мгновенное изменение скорости: `Δv = импульс / масса`. Прыжок, отдача: `body.add_impulse(0, -400)`. |
| `add_force(force_x, force_y, delta_time=None)` | `force_x: float, force_y: float, delta_time: float = None` | Сила копится и применяется **следующим шагом** физики, затем обнуляется — для постоянного толчка вызывайте каждый `fixed_update`. С `delta_time` — прежнее поведение: сразу `v += F / m · dt`. |
| `stop()` | — | Обнуляет скорость и накопленные силы. |
| `teleport(x, y)` | `x: float, y: float` | Переносит в мировую точку без сглаживания и останавливает тело. |
| `on_spawn()` / `on_despawn()` | `**kwargs` / — | Хуки для `GameObjectPool`: тело останавливается при выдаче из пула и возврате в него. |

#### Пример использования

```python
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square

scene = Scene("physics")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

# Ящик с трением: скользит и останавливается
crate = create_square(100, 300, size=40, name="Crate", add_rigidbody=True)
crate_body = crate.get_component(Rigidbody2D)
crate_body.friction = 0.6        # на земле тормозит на 0.6 · gravity px/с²
crate_body.mass = 2.0
scene.add_game_object(crate)

# Кинематическая платформа: едет по velocity, сквозь всё, без гравитации
platform = create_rectangle(300, 250, 120, 16, name="Platform", add_rigidbody=True)
platform_body = platform.get_component(Rigidbody2D)
platform_body.is_kinematic = True
platform_body.velocity.x = 60
scene.add_game_object(platform)

for _ in range(60):                        # секунда падения
    scene.tick(1 / 60)
assert crate_body.is_grounded              # стоит на полу

crate_body.add_impulse(400, 0)             # толчок вправо: скорость += 400 / масса
for _ in range(120):
    scene.tick(1 / 60)
print(crate_body.velocity.x)               # 0.0 — трение остановило ящик

crate_body.teleport(100, 100)              # вернуть наверх без «размазывания» по кадрам
```

### 5.2. Коллайдеры (BoxCollider2D, CircleCollider2D)

**Описание:** Коллайдер задаёт форму объекта для столкновений (твёрдый) или для обнаружения касаний (триггер, `is_trigger=True`). `BoxCollider2D` — прямоугольник, единственная форма, которую `Rigidbody2D` разрешает как твёрдую. `CircleCollider2D` точно проверяет расстояние до центра (круг–круг и круг–прямоугольник), но работает **только на пересечение и триггеры** — твёрдого круга нет. Геометрия хранится точными числами с плавающей точкой (`bounds`); `rect` — лишь округлённый `pygame.Rect` для отрисовки и старого кода. **Размер:** лучше задавать `size=(w, h)` явно; иначе он один раз измеряется по спрайту в `start()` и *фиксируется* — смена кадра анимации хитбокс не меняет (для осознанного изменения, например приседания, есть `set_size`). **Якорь** (`anchor`) — те же девять имён, что у `SpriteRenderer`: чтобы хитбокс совпал со спрайтом, задайте им один и тот же якорь (см. [9.1](#91-spriterenderer-и-якоря-спрайтов)).

**События.** Твёрдое с твёрдым порождает события столкновений, если хотя бы у одной стороны есть `Rigidbody2D`; всё, что пересекает триггер, порождает события триггера. Получить их можно двумя способами, оба работают одновременно и для обеих сторон:

- **Методы-обработчики** на любом компоненте любого из двух объектов: `on_collision_enter/stay/exit(self, collision)` и `on_trigger_enter/stay/exit(self, other)`;
- **Списки колбэков** на коллайдере: `collider.on_trigger_enter.append(fn)`, сигнатура `fn(свой_коллайдер, чужой_коллайдер)`.

Если объект деактивирован, удалён или уничтожен, пока касался другого, вторая сторона получает `exit`. Исключения в обработчиках логируются, а не выбрасываются; уничтожать объекты внутри обработчиков безопасно.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `BoxCollider2D(...)` | `size: tuple = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int или str = None, mask: int или список слоёв = None` | Прямоугольник. `size=None` — по спрайту (один раз, в `start()`); `offset_x/offset_y` смещают хитбокс; `layer=None` берёт слой объекта; `mask=None` — сталкивается со всеми слоями. |
| `CircleCollider2D(...)` | `radius: float = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int или str = None, mask: int или список слоёв = None` | Круг (только пересечения и триггеры). `radius=None` — половина большей стороны спрайта. Якорь применяется к квадрату `(диаметр, диаметр)`. |
| `is_trigger` | `bool` | `True` — сенсор без физической реакции: `collider.is_trigger = True`. |
| `layer`, `mask` | `int`, `int` | Слой и маска столкновений (см. [5.3](#53-слои-и-маски-столкновений-collision-layers)). |
| `bounds` | `tuple` (свойство) | Точные границы `(left, top, right, bottom)` в мировых координатах. |
| `rect` | `pygame.Rect` (свойство) | Округлённый прямоугольник габаритов — для отрисовки и отладки, но не для физики. |
| `is_static` | `bool` (свойство) | Находится ли коллайдер на статичном объекте. |
| `overlaps(other)` | `other: Collider2D` | Точная проверка пересечения форм: `zone.overlaps(hero_collider)`. |
| `can_collide_with(other)` | `other: Collider2D` | Взаимодействуют ли пары по слоям и маскам (обе маски должны разрешать слой друг друга). |
| `contact_normal(other)` | `other: Collider2D` | Единичная нормаль `(nx, ny)` от `other` к этому коллайдеру. |
| `overlapping_colliders` | `frozenset` (свойство) | С чем коллайдер соприкасался на последнем шаге физики. |
| `on_trigger_enter/stay/exit` | `список fn(collider, other)` | Колбэки триггера: вход / пребывание (каждый шаг) / выход. |
| `on_collision_enter/stay/exit` | `список fn(collider, other)` | Колбэки столкновений (нужен `Rigidbody2D` хотя бы у одной стороны). |
| `Collision2D` | `collider, other, normal, game_object` | Аргумент метода `on_collision_*(collision)`: `collision.other` — чужой коллайдер, `collision.game_object` — чужой объект, `collision.normal` — нормаль контакта от чужого к своему (`(0, −1)`: нас поддержали снизу). |
| `BoxCollider2D.size` / `set_size(width, height)` | `width: float, height: float` | Текущий размер / осознанное изменение и повторная фиксация размера. |
| `BoxCollider2D.snap_left_to(x)`, `snap_right_to(x)`, `snap_top_to(y)`, `snap_bottom_to(y)` | `x: float` / `y: float` | Сдвигает `Transform` так, чтобы грань хитбокса оказалась ровно в данной мировой координате. |
| `CircleCollider2D.radius` / `set_radius(radius)` | `radius: float` | Радиус (только чтение) / осознанное изменение. `center_x`, `center_y` — мировой центр круга. |
| `scene.physics.query_point(x, y, mask, include_triggers)` | `x: float, y: float, mask: int = CollisionLayers.ALL, include_triggers: bool = True` | Коллайдеры в точке: `scene.physics.query_point(210, 360)`. |
| `scene.physics.query_rect(rect, ...)` / `query_bounds(left, top, right, bottom, ...)` | `rect: pygame.Rect` / `left, top, right, bottom: float` (+ те же `mask`, `include_triggers`) | Коллайдеры, пересекающие область. |

#### Пример использования

```python
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square


class DamageZone(Component):
    """Методы-обработчики физики: на любом компоненте любого из двух объектов."""

    def on_trigger_enter(self, other):                # other — вошедший коллайдер
        print(f"{other.game_object.name} вошёл в зону")

    def on_trigger_exit(self, other):
        print(f"{other.game_object.name} вышел из зоны")


class LandingLogger(Component):
    def on_collision_enter(self, collision):          # collision — Collision2D
        if collision.normal.y < -0.5:                 # опора снизу
            print("приземлился на", collision.game_object.name)


scene = Scene("colliders")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

zone = GameObject(200, 340, name="Zone", is_static=True)
zone_collider = zone.add_component(BoxCollider2D(size=(120, 60), is_trigger=True))
zone.add_component(DamageZone())
# Второй способ: список колбэков, сигнатура (свой_коллайдер, чужой_коллайдер)
zone_collider.on_trigger_enter.append(lambda me, other: print("колбэк-список:", other.game_object.name))
scene.add_game_object(zone)

hero = create_square(240, 100, size=40, name="Hero", add_rigidbody=True)
hero.add_component(LandingLogger())
scene.add_game_object(hero)

sensor = GameObject(600, 300, name="Sensor", is_static=True)
sensor.add_component(CircleCollider2D(radius=80, is_trigger=True))   # круглая зона обнаружения
scene.add_game_object(sensor)

for _ in range(120):                                  # герой падает сквозь зону и встаёт на пол
    scene.tick(1 / 60)

hero_box = hero.get_component(BoxCollider2D)
print(hero_box.bounds)                                # точные границы (240, 360, 280, 400)
print(hero_box.overlaps(zone_collider))               # True: герой стоит в зоне
print([c.game_object.name for c in scene.physics.query_point(250, 380)])   # Zone и Hero
```

### 5.3. Слои и маски столкновений (Collision Layers)

**Описание:** У каждого коллайдера есть **слой** (`layer`, число 0–31 или имя — «кто я») и **маска** (`mask`, набор слоёв — «с кем сталкиваюсь»). Два коллайдера взаимодействуют, только если маска **каждого** разрешает слой другого. Неподходящие пары отбрасываются ещё до точной проверки пересечения, так что разделение слоёв — самый дешёвый способ ускорить физику. По умолчанию все объекты лежат на слое 0 (`"default"`) и сталкиваются со всем. Слой объекта (`go.layer`) наследуют его коллайдеры, если у них нет своего `layer`. Имена слоям даёт `CollisionLayers.register`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `CollisionLayers.register(name, index)` | `name: str, index: int` | Даёт слою имя (0–31; регистр не важен): `CollisionLayers.register("enemy", 2)`. |
| `CollisionLayers.index(layer)` | `layer: int или str` | Проверяет и переводит имя или число в номер слоя; неизвестное имя — `ValueError`. |
| `CollisionLayers.mask(*layers)` | `*layers: int или str` | Маска из перечисленных слоёв: `CollisionLayers.mask("ground", "enemy")`. |
| `CollisionLayers.name_of(index)` | `index: int` | Имя слоя (или номер строкой, если имени нет). |
| `CollisionLayers.reset()` | — | Сбрасывает реестр имён (остаётся только `"default"`). |
| `CollisionLayers.ALL` / `NONE` / `MAX_LAYERS` | `int` | Маска «все слои» (`0xFFFFFFFF`) / «ни одного» / число слоёв (32). |
| `GameObject.layer` | `int или str` | Слой объекта: `go.layer = "player"`. |
| `Collider2D.layer` / `Collider2D.mask` | `int` / `int` | Слой и маска конкретного коллайдера (`mask` можно передать и в конструктор). |
| `Collider2D.can_collide_with(other)` | `other: Collider2D` | Проверка пары по слоям и маскам. |
| `mask` в запросах `scene.physics.query_*` | `int` | Ограничивает результат запроса нужными слоями. |

#### Пример использования

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

# Игрок сталкивается с землёй и врагами — но не со своими пулями
player = GameObject(100, 100, name="Player", layer="player")
player_box = player.add_component(BoxCollider2D(
    size=(32, 48), mask=CollisionLayers.mask("ground", "enemy")))

# Пуля игрока (триггер): попадает по врагам и земле, игрока и других пуль «не видит»
bullet = GameObject(140, 110, name="Bullet", layer="bullet")
bullet_box = bullet.add_component(BoxCollider2D(
    size=(8, 8), is_trigger=True, mask=CollisionLayers.mask("enemy", "ground")))

enemy = GameObject(300, 100, name="Enemy", layer="enemy")
enemy_box = enemy.add_component(BoxCollider2D(size=(32, 32)))

for go in (player, bullet, enemy):
    scene.add_game_object(go)

print(player_box.can_collide_with(bullet_box))   # False — пара не взаимодействует
print(bullet_box.can_collide_with(enemy_box))    # True — «bullet» видит «enemy», а «enemy» (маска по умолчанию) видит всех

enemy.layer = "ground"                           # слой можно менять на лету
print(CollisionLayers.name_of(enemy.layer))      # ground
```

---

## 6. Система ввода (Input)

**Описание:** `Input` — статический сервис, доступный из любого компонента без ссылки на `Engine`. Клавиши задаются строками (`"space"`, `"w"`, `"left_shift"`, `"mouse_left"`), константами `Key.*` или сырыми `pygame.K_*`; опечатка в имени клавиши сразу вызывает `ValueError`, а не молча ничего не делает. Система событийная: `Engine` передаёт в неё каждое событие pygame, поэтому короткое нажатие короче одного кадра не теряется, а потеря фокуса окна отпускает все зажатые клавиши. **Внутри `fixed_update` события «нажатие»/«отпускание» читаются из отдельного набора, который расходуется после каждого физического шага** — так каждое нажатие увидит ровно один физический шаг, даже если на кадр пришлось два шага или ни одного. Для обычной геймплейной логики предпочтительнее читать ввод в `update()`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Input.is_key_down(key)` | `key: str, int или Key` | `True`, пока клавиша зажата: `Input.is_key_down("d")`. |
| `Input.is_key_pressed(key)` | `key: str, int или Key` | `True` только в кадре (или физическом шаге) нажатия. |
| `Input.is_key_up(key)` | `key: str, int или Key` | `True` только в кадре отпускания. |
| `Input.get_axis(negative, positive)` | `negative: str, positive: str` | `-1`, `0` или `1` по паре клавиш: `Input.get_axis("a", "d")`. |
| `Input.mouse_position()` | — | `(x, y)` в пикселях экрана. |
| `Input.mouse_world_position()` | — | Позиция курсора в мировых координатах через активную камеру сцены (или `None`, если сцены нет). |
| `Input.mouse_delta()` | — | Смещение мыши с прошлого кадра `(dx, dy)`. |
| `Input.mouse_scroll()` / `mouse_scroll_x()` | — | Прокрутка колеса за кадр (вертикальная / горизонтальная). |
| `Input.is_mouse_pressed(button=0)` / `is_mouse_just_pressed(button)` / `is_mouse_just_released(button)` | `button: int` (0 — левая, 1 — средняя, 2 — правая) | Прежний числовой API для кнопок мыши. |
| `Input.is_pressed(key)` / `is_just_pressed(key)` / `is_just_released(key)` | `key: str, int или Key` | Прежние имена: `is_pressed` = `is_key_down`, `is_just_pressed` = `is_key_pressed`, `is_just_released` = `is_key_up`. |
| `Key.*` | — | Именованные константы: `Key.W`, `Key.SPACE`, `Key.LEFT`, `Key.F1` и т. д. — то же, что и строки, но с автодополнением в IDE. |
| `Input.inject_key(key, down=True)` / `inject_mouse_position(x, y)` / `inject_scroll(y, x=0)` | — | Имитация ввода без реальных событий pygame — удобно для тестов и ботов. |

#### Пример использования

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
        x = Input.get_axis("a", "d")               # -1 / 0 / 1 по строковым именам
        y = Input.get_axis(Key.W, Key.S)            # то же самое, но через Key.*
        self.body.velocity.x = x * self.speed
        self.body.velocity.y = y * self.speed

        if Input.is_key_pressed("space"):           # только в кадре нажатия
            print("прыжок!")

        if Input.is_mouse_just_pressed(0):           # левая кнопка мыши
            target = Input.mouse_world_position()
            print("клик по миру:", target)
```

---

## 7. Система пользовательского интерфейса (UI)

### 7.1. Canvas и Screen-Space UI

**Описание:** UI-элементы (`UIText`, `UIButton`, `UIPanel`, `UIHealthBar`) — это компоненты на `GameObject`, как и всё остальное. По умолчанию они рисуются в **экранных координатах** — после мира, поверх него, без смещения камеры, поэтому HUD никогда не «уезжает» при прокрутке. `Canvas` — необязательный корневой элемент: сам он ничего не рисует, но `canvas.visible = False` скрывает весь UI, прикреплённый к нему как к родителю. Элемент можно сделать и **мировым** (`world_space=True`) — тогда он рисуется вместе с миром через камеру (например, полоска здоровья над врагом): для этого объект UI-элемента делают потомком нужного объекта.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `UIElement(...)` | `width: int = 100, height: int = 30, visible: bool = True, draw_order: int = 0, anchor: str = None, pivot: str = None, world_space: bool = False` | Базовый класс всех UI-элементов; см. параметры якорей в [7.3](#73-сетка-якорей-ui-anchors-pivots). |
| `Canvas(...)` | `sort_order: int = 0, visible: bool = True` | Корневой UI-элемент-контейнер; сам не рисуется. `visible = False` скрывает всех потомков разом. |
| `visible` | `bool` | Показан ли элемент. |
| `is_visible` | `bool` (свойство) | Показан ли элемент **с учётом** видимости всех UI-родителей. |
| `draw_order` | `int` | Порядок отрисовки среди экранных элементов (меньше — раньше/ниже); при равенстве — порядок добавления. |
| `world_space` | `bool` | `True` — элемент рисуется в мире через камеру, а не в экранных координатах. |
| `rect` | `pygame.Rect` (свойство) | Текущий прямоугольник элемента в экранных координатах (для мирового элемента — с учётом камеры). |
| `contains_point(point_x, point_y)` | `point_x: float, point_y: float` | Попадает ли точка в прямоугольник элемента: `panel.contains_point(*Input.mouse_position())`. |
| `draw(screen)` | `screen: pygame.Surface` | Хук отрисовки — переопределяют конкретные виджеты. |

#### Пример использования

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
        self.canvas = hud.add_component(Canvas())      # общий переключатель видимости
        self.add_game_object(hud)

        label = GameObject(12, 12, name="ScoreLabel", parent=hud)
        self.score_text = label.add_component(UIText("Очки: 0", anchor="TopLeft"))

        bar = GameObject(12, 42, name="HealthBar", parent=hud)
        bar.add_component(UIHealthBar(220, 20, max_value=100, anchor="TopLeft"))

    def update(self, delta_time):
        super().update(delta_time)
        from engine.input.input_manager import Input
        if Input.is_key_pressed("h"):
            self.canvas.visible = not self.canvas.visible   # спрятать/показать весь HUD разом
```

### 7.2. UI-элементы (UIText, UIButton, UIPanel, UIHealthBar)

**Описание:** Четыре готовых виджета. `UIText` рисует строку (рендер кэшируется, повторная отрисовка одного текста не пересоздаёт поверхность). `UIButton` — прямоугольник с текстом и списком колбэков `on_click`, реагирующий на наведение и клик левой кнопкой мыши. `UIPanel` — простой прямоугольный фон, часто как подложка для других элементов. `UIHealthBar` — заполняемая полоса (здоровье, стамина, прогресс) с необязательным плавным сглаживанием и «полосой урона» (`trail_color`), догоняющей текущее значение. Цвета и шрифт по умолчанию берутся из `UIStyle.default()`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `UIText(...)` | `text: str = "", style: UIStyle = None, align: str = "left", width: int = None, height: int = None, **kwargs` | `**kwargs` — общие параметры `UIElement` (`anchor`, `pivot`, `world_space`…). `align`: `"left"`, `"center"` или `"right"`. Ширина/высота по умолчанию измеряются по тексту. |
| `UIText.text` / `set_text(text)` | `text: str` | Текущий текст / его смена: `label.set_text("Готово")`. |
| `UIButton(...)` | `text: str = "Button", width: int = 140, height: int = 40, style: UIStyle = None, **kwargs` | Кнопка с текстом. |
| `UIButton.on_click` | `список fn(button)` | Колбэки клика: `button.on_click.append(lambda b: print("клик"))`. |
| `UIButton.is_hovered` / `is_pressed` | `bool` | Наведена ли мышь / зажата ли кнопка сейчас. |
| `UIPanel(...)` | `width: int = 200, height: int = 100, style: UIStyle = None, **kwargs` | Прямоугольная подложка. |
| `UIHealthBar(...)` | `width: int = 200, height: int = 20, max_value: float = 100.0, value: float = None, fill_color: tuple = (80,200,90), low_color: tuple = (215,65,65), low_threshold: float = 0.3, trail_color: tuple = None, smooth_speed: float = 0.0, show_text: bool = False, **kwargs` | `low_color` включается при `ratio <= low_threshold`; `smooth_speed > 0` — плавное движение заполнения (доля в секунду) вместо мгновенного; `show_text` рисует `"хп/макс"` поверх полосы. |
| `UIHealthBar.value` / `set_value(v)` | `float` | Текущее значение. |
| `UIHealthBar.set_max_value(max_value, keep_ratio=False)` | `max_value: float, keep_ratio: bool` | Меняет максимум; `keep_ratio=True` сохраняет долю заполнения. |
| `UIHealthBar.bind(getter)` | `getter: вызываемый без аргументов` | Читает значение из функции каждый кадр: `bar.bind(lambda: player_health.hp)`. |
| `UIHealthBar.ratio` / `displayed_ratio` | `float` (свойства) | Истинная доля заполнения / та, что реально отрисована (с учётом сглаживания). |
| `UIStyle(...)` / `UIStyle.default()` | `background_color, border_color, border_width, text_color, font_name, font_size, hover_color, pressed_color` | Общий набор цветов и шрифта для виджетов; `default()` — фабрика стиля по умолчанию. |

#### Пример использования

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
        title.add_component(UIText("Пауза", anchor="Center", align="center"))

        health = GameObject(-140, -10, name="Health", parent=hud)
        bar = health.add_component(UIHealthBar(280, 24, max_value=100, value=65,
                                               anchor="Center", show_text=True,
                                               smooth_speed=2.0, trail_color=(220, 90, 90)))

        resume = GameObject(0, 40, name="Resume", parent=hud)
        button = resume.add_component(UIButton("Продолжить", 180, 44, anchor="Center"))
        button.on_click.append(lambda b: print("продолжаем игру"))

        bar.value = 40    # полоса плавно «догонит» новое значение благодаря smooth_speed
```

### 7.3. Сетка якорей (UI Anchors & Pivots)

**Описание:** Девять именованных якорей — `TopLeft`, `TopCenter`, `TopRight`, `MiddleLeft`, `Center`, `MiddleRight`, `BottomLeft`, `BottomCenter`, `BottomRight` (регистр и подчёркивания не важны: `"top_left"`, `"topleft"`, `"MidTop"` — все понимаются). Без якоря (`anchor=None`, поведение по умолчанию) позиция `GameObject` — это верхний левый угол элемента в экранных пикселях; при родителе-UI-элементе — относительно его прямоугольника. С якорем позиция объекта становится **смещением от опорной точки** прямоугольника-ориентира: экрана, либо ближайшего UI-предка, если он есть. `pivot` определяет, какая точка *самого элемента* садится на эту опорную точку (по умолчанию совпадает с `anchor`), поэтому `anchor="BottomRight"` со смещением `(-10, -10)` даёт отступ 10 пикселей от угла при любом размере окна.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `UIElement(anchor=..., pivot=...)` | `anchor: str = None, pivot: str = None` | `anchor` — к какой точке ориентира привязан элемент; `pivot` — какая точка элемента садится туда (по умолчанию равен `anchor`). |
| `UIElement.anchor` / `.pivot` | `str или None` | Можно менять после создания: `element.anchor = "BottomRight"`. |
| `normalize_anchor(name)` | `name: str` | Приводит произвольное написание к каноническому имени; неизвестное — `ValueError`. |
| `VALID_ANCHORS` | `set[str]` | Девять канонических имён в нижнем регистре без пробелов: `{"topleft", "midtop", ...}`. |
| `anchor_to_topleft_offset(anchor, width, height)` | `anchor: str, width: float, height: float` | `(dx, dy)` от опорной точки до верхнего левого угла прямоугольника такого размера — та же математика, что использует `SpriteRenderer` и коллайдеры ([9.1](#91-spriterenderer-и-якоря-спрайтов)). |

#### Пример использования

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.ui_button import UIButton
from engine.ui.ui_text import UIText

scene = Scene("anchors")

# Привязка к углам экрана — не зависит от размера окна
top_left = GameObject(10, 10, name="TopLeft")
top_left.add_component(UIText("Верх-лево", anchor="TopLeft"))
scene.add_game_object(top_left)

bottom_right = GameObject(-10, -10, name="BottomRight")   # отрицательные значения = отступ от угла
bottom_right.add_component(UIText("Низ-право", anchor="BottomRight", pivot="BottomRight"))
scene.add_game_object(bottom_right)

centered = GameObject(0, 0, name="CenterButton")
centered.add_component(UIButton("По центру", 160, 40, anchor="Center"))   # pivot по умолчанию = anchor
scene.add_game_object(centered)

# Вложенность: дочерний элемент якорится относительно родителя, а не экрана
panel = GameObject(0, 0, name="Panel")
panel.add_component(UIButton("Заглушка", 300, 200, anchor="Center"))
scene.add_game_object(panel)

corner_label = GameObject(-8, -8, name="PanelCorner", parent=panel)
corner_label.add_component(UIText("v1.0", anchor="BottomRight", pivot="BottomRight"))
```

---

## 8. Система частиц (Particle System)

**Описание:** `ParticleSystem` — лёгкий эмиттер пыли, искр, взрывов и следов. Частицы — не `GameObject`, а компактные структуры, переиспользуемые через `ObjectPool` (см. [10](#10-статические-сервисы-и-утилиты)): после «прогрева» непрерывная эмиссия не выделяет память и не порождает мусор для сборщика. Частицы не участвуют в столкновениях. Цвет, размер и прозрачность — чистые функции возраста частицы (0…1 от рождения до смерти), поэтому система один раз готовит небольшой набор готовых поверхностей (`lut_steps` штук) и рисует частицу как выбор нужной поверхности плюс один пакетный блит — без отрисовки «частица за частицей». `color_stops` задаёт градиент из нескольких цветов; `world_space=True` (по умолчанию) — частицы остаются на месте появления, даже если эмиттер уехал (взрыв, след); `world_space=False` — частицы едут вместе с эмиттером (пламя факела).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `ParticleSystem(...)` | `emission_rate: float = 0.0, lifetime: tuple = (0.5, 1.0), speed: tuple = (50.0, 100.0), direction: float = -90.0, spread: float = 360.0, gravity: float = 0.0, drag: float = 0.0, start_size: float = 6, end_size: float = None, start_color: tuple = (255,255,255), end_color: tuple = None, color_stops: list = None, start_alpha: int = 255, end_alpha: int = 0, shape: str = "circle", sprite: pygame.Surface = None, additive: bool = False, max_particles: int = 500, world_space: bool = True, z_index: int = 10, offset: tuple = (0.0, 0.0), spawn_radius: float = 0.0, duration: float = None, loop: bool = True, play_on_start: bool = True, lut_steps: int = 24, seed: int = None` | `direction`/`spread` — угол в градусах (0 = вправо, «−90» = вверх, по часовой стрелке); `additive=True` — аддитивное смешение (огонь, искры); `shape` — `"circle"` или `"square"`, либо задайте `sprite` для своей формы; `duration`/`loop` — конечный или бесконечный проигрыватель эмиссии. |
| `play()` / `stop(clear=False)` | — / `clear: bool` | Запустить непрерывную эмиссию (`emission_rate`) / остановить (`clear=True` — сразу убрать живые частицы). |
| `burst(count)` / `emit(count)` | `count: int` | Разово выпустить `count` частиц (взрыв, всплеск) — `emit` это псевдоним `burst`. |
| `clear()` | — | Убрать все текущие частицы немедленно. |
| `is_playing` | `bool` (свойство) | Идёт ли непрерывная эмиссия. |
| `particle_count` | `int` (свойство) | Сколько частиц живо сейчас. |
| `invalidate()` | — | Пересобрать таблицу цвет/размер/прозрачность после изменения этих параметров в рантайме. |
| `pool` | `ObjectPool` (свойство) | Пул, из которого берутся структуры частиц. |

#### Пример использования

```python
from engine.components.particle_system import ParticleSystem
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("particles")

# Разовый взрыв искр (аддитивное смешение, градиент жёлтый → оранжевый → тёмно-красный)
sparks_go = GameObject(400, 300, name="Sparks")
sparks = sparks_go.add_component(ParticleSystem(
    play_on_start=False, lifetime=(0.3, 0.6), speed=(120, 260), direction=-90, spread=180,
    gravity=500, start_size=8, end_size=1,
    color_stops=[(255, 246, 170), (255, 150, 40), (120, 40, 20)],
    additive=True, max_particles=200, seed=1,
))
scene.add_game_object(sparks_go)
sparks.burst(24)

# Непрерывный дым от факела: едет вместе с объектом (world_space=False)
torch_go = GameObject(200, 250, name="TorchSmoke")
smoke = torch_go.add_component(ParticleSystem(
    emission_rate=15, lifetime=(0.8, 1.4), speed=(20, 40), direction=-90, spread=30,
    gravity=-40, start_size=4, end_size=14, color_stops=[(200, 200, 200), (90, 90, 90)],
    start_alpha=160, end_alpha=0, world_space=False, play_on_start=True,
))
scene.add_game_object(torch_go)

for _ in range(60):
    scene.tick(1 / 60)
print("живых частиц дыма:", smoke.particle_count)
```

---

## 9. Графика, анимация и рендеринг

### 9.1. SpriteRenderer и якоря спрайтов

**Описание:** `SpriteRenderer` рисует `pygame.Surface` в мировой позиции объекта с учётом мирового поворота и масштаба `Transform`. `anchor` — те же девять имён, что у коллайдеров (см. [7.3](#73-сетка-якорей-ui-anchors-pivots) и [5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)): задайте одинаковый якорь спрайту и его коллайдеру, чтобы хитбокс и картинка совпадали. `z_index` определяет порядок слоёв (меньше — дальше/раньше); внутри одного `z_index` объекты сортируются по `мировой_y + offset_y`, что даёт дешёвую имитацию глубины для платформеров и видов сверху. Спрайт при первой отрисовке конвертируется в формат экрана (`convert()`/`convert_alpha()`), а повёрнутые и масштабированные варианты берутся из общего кэша (см. [10](#10-статические-сервисы-и-утилиты)) — статичный объект не пересчитывается каждый кадр. Видимые камере объекты определяются отсечением по границам (см. [9.4](#94-оптимизация-тайлмапов-baking)), поэтому спрайты вне экрана не рисуются вовсе.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `SpriteRenderer(...)` | `sprite: pygame.Surface = None, z_index: int = 0, offset_y: float = 0, anchor: str = "topleft", convert: bool = True` | `convert=False` отключает автоконвертацию в формат экрана (если поверхность уже подготовлена вручную). |
| `sprite` / `set_sprite(sprite)` | `pygame.Surface` | Текущий спрайт / его замена (используется `Animator`, см. [9.3](#93-анимации-и-спрайтшиты-animator)). |
| `anchor` | `str` | Одно из девяти имён якоря; неверное значение выводит предупреждение и откатывается к `"topleft"`. |
| `z_index` | `int` | Порядок слоёв. |
| `offset_y` | `float` | Влияет только на ключ сортировки по глубине (`world_y + offset_y`), на позицию отрисовки не влияет. |
| `is_visible` | `bool` (свойство) | Рисовался ли спрайт в последних кадрах — используется `Animator` для пропуска анимации вне экрана. |
| `get_anchor_offset()` | — | `(dx, dy)` от позиции объекта до исходного левого верхнего угла спрайта, по якорю. |
| `get_transformed_sprite(rotation, scale_x, scale_y)` | `rotation: float, scale_x: float, scale_y: float` | Повёрнутый/масштабированный спрайт из общего кэша. |
| `get_placement(world_x, world_y, rotation, scale_x, scale_y)` | — | Итоговая поверхность и левый верхний угол для блита с учётом якоря, поворота и масштаба — используется системой рендеринга. |

#### Пример использования

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
# Одинаковый якорь у спрайта и коллайдера — они всегда совпадают визуально
enemy.add_component(SpriteRenderer(sprite=sprite, anchor="center", z_index=1))
enemy.add_component(BoxCollider2D(size=sprite.get_size(), anchor="center"))
scene.add_game_object(enemy)

enemy.transform.rotation = 15      # рисуется повёрнутым вокруг центра спрайта
enemy.transform.scale = 1.5        # рисуется увеличенным в 1.5 раза
```

### 9.2. Камера (Camera)

**Описание:** `Camera` следует за целью (`target`), не трогая её `Transform` — вместо этого камера хранит собственную мировую точку, которая при отрисовке вычитается из позиции каждого спрайта. Это даёт естественное ощущение прыжка: двигается «взгляд», а не сам объект. `smooth_follow=True` (по умолчанию) плавно нагоняет цель с коэффициентом `follow_speed` (экспоненциальное сглаживание — не зависит от FPS и никогда не «перелетает» цель); `smooth_follow=False` — камера жёстко следует за целью каждый кадр. Камера читает **сглаженную** (интерполированную) позицию цели, поэтому на мониторах с высокой частотой обновления камера и спрайт цели двигаются в такт, без рассинхронизации. Без цели (`target=None`) мир рисуется без смещения — как будто камеры нет вовсе.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Camera(...)` | `target: GameObject = None, follow_speed: float = 5.0, smooth_follow: bool = True, position: Vector2 = None` | `follow_speed` — чем больше, тем «резче» слежение; `position` задаёт стартовую точку (актуально только до `start()`, который сразу центрируется на цели). |
| `target` | `GameObject или None` | Текущая цель слежения. |
| `set_target(target, snap=True)` | `target: GameObject, snap: bool` | Сменить цель; `snap=True` — сразу перескочить на неё, `False` — плавно доехать. |
| `snap_to_target()` | — | Мгновенно встать на текущую позицию цели (после телепорта/респавна). |
| `position` | `Vector2` | Текущая мировая точка, которая окажется в центре экрана. |
| `get_offset(screen_width, screen_height)` | `screen_width: int, screen_height: int` | Мировая точка, которая попадёт в левый верхний угол экрана; `(0, 0)`, если цели нет. |
| `get_view_bounds(screen_width, screen_height)` | `screen_width: int, screen_height: int` | `(left, top, right, bottom)` видимой камере области мира. |
| `world_to_screen(world_pos, w, h)` / `screen_to_world(screen_pos, w, h)` | `Vector2, int, int` | Перевод координат вручную (обычно удобнее `Scene.world_to_screen`/`screen_to_world`, см. [4.2](#42-управление-сценами-scene-и-scenemanager)). |

#### Пример использования

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
scene.set_active_camera(camera)          # без этого вызова мир рисуется без смещения

player.transform.position.x += 500       # игрок телепортировался далеко
camera.snap_to_target()                  # камера мгновенно догоняет, без «наезда»

visible_left, visible_top, visible_right, visible_bottom = camera.get_view_bounds(1280, 720)
print(f"сейчас видно от x={visible_left:.0f} до x={visible_right:.0f}")
```

### 9.3. Анимации и спрайтшиты (Animator)

**Описание:** `Animator` переключает кадры `SpriteRenderer` по времени. Проигрывание привязано к реальному времени (`dt * speed`), а не к частоте кадров. `play(name)` спроектирован так, что его безопасно вызывать **каждый кадр** с «желаемой» анимацией: повторный вызов с тем же именем не сбрасывает анимацию на первый кадр, а зациклённая (`loop=False`) анимация, доигранная до конца, остаётся на последнем кадре, даже если `play()` продолжают вызывать. `force_restart=True` — принудительный перезапуск с первого кадра. Если зацикленная анимация не рисовалась последние пару кадров (объект вне экрана), она **не тикает** — сотня врагов за кадром камеры не стоит ничего; незацикленные анимации и анимации с подписчиками `on_finished` тикают всегда, чтобы игровая логика («анимация атаки завершилась») срабатывала и вне экрана. `load_spritesheet_animations()` собирает набор анимаций прямо из спрайтшита и JSON-атласа (форматы `"hash"` и `"array"`, как у TexturePacker), с сортировкой кадров по числовому индексу в имени файла, а не по алфавиту (иначе `"walk_10"` встал бы перед `"walk_2"`).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Animator(...)` | `animations: dict = None, default_animation: str = None, frame_duration: float = 0.1, speed: float = 1.0, cull_offscreen: bool = True` | `animations` — словарь `{"имя": [surface, surface, ...]}`. |
| `play(anim_name=None, loop=True, reverse=False, force_restart=False)` | `anim_name: str, loop: bool, reverse: bool, force_restart: bool` | Безопасно вызывать каждый кадр — см. описание выше. |
| `pause()` / `stop()` | — | Остановить на текущем кадре / остановить и сбросить на первый кадр. |
| `has_animation(anim_name)` | `anim_name: str` | Есть ли такая анимация в словаре — удобно для отката на анимацию по умолчанию. |
| `set_animations(animations)` | `animations: dict` | Полностью заменить набор анимаций (кадры конвертируются один раз). |
| `is_playing`, `current_animation`, `frame_index` | `bool`, `str`, `int` | Текущее состояние проигрывателя. |
| `on_finished` | `список fn(animator, anim_name)` | Срабатывает один раз, когда незацикленная анимация доходит до последнего кадра. |
| `load_spritesheet_animations(json_path, image_path, generate_flipped=True)` | `json_path: str, image_path: str, generate_flipped: bool` | Возвращает `{имя: [surface, ...]}` для `Animator`. `generate_flipped=True` также создаёт зеркальные версии всех анимаций с префиксом `_` (например, `"idle"` → `"_idle"`). |

#### Пример использования

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

# Вариант 1: анимация из готовых кадров (Surface) — вручную
idle_frames = [make_frame((90, 160, 230)), make_frame((100, 170, 240))]
animator = hero.add_component(Animator({"idle": idle_frames}, default_animation="idle",
                                       frame_duration=0.2))
scene.add_game_object(hero)

animator.play("idle")            # безопасно вызывать это каждый кадр в update()

# Вариант 2: анимация из спрайтшита + JSON-атлас (если есть файлы assets/hero.png/.json)
# animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
# hero.get_component(Animator).set_animations(animations)
```

### 9.4. Оптимизация тайлмапов (Baking)

**Описание:** Отрисовка тысяч статичных тайлов — тысячи вызовов `blit()` каждый кадр, навсегда. Запекание (`baking`) рисует их **один раз**, при загрузке уровня, на большую поверхность (или несколько поверхностей-«чанков», если карта огромна); каждый кадр после этого стоит один блит на видимый чанк — обычно один-четыре. `bake_tilemap()` строит статичный `GameObject` прямо из сетки идентификаторов тайлов и словаря `{id: surface}`. `bake_static_sprites()` запекает **уже добавленные** в сцену статичные, неанимированные `SpriteRenderer` и отключает исходные компоненты (коллайдеры и игровые скрипты на тех же объектах продолжают работать как обычно). Полупрозрачные спрайты запекаются в предумноженном альфа-пространстве, поэтому перекрывающаяся прозрачность совпадает с попиксельной отрисовкой с точностью до округления. Запечённые пиксели «заморожены» (не двигаются, не анимируются) и делят один слой по `z_index`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `bake_tilemap(grid, tileset, tile_size, origin=(0,0), z_index=-100, chunk_size=None, opaque=False, background=(0,0,0), name="BakedTilemap")` | `grid: list[list[int]], tileset: dict или list, tile_size: int или tuple, origin: tuple, z_index: int, chunk_size: int, opaque: bool, name: str` | Строит статичный `GameObject` с запечённым слоем из сетки идентификаторов (`None`/`-1` — пустая клетка). Возвращает объект — добавьте его в сцену сами. |
| `bake_static_sprites(scene, chunk_size=None, z_range=None, opaque=False, name_prefix="Baked")` | `scene: Scene, chunk_size: int, z_range: tuple, opaque: bool` | Запекает все подходящие статичные спрайты уже добавленной сцены, по одному слою на `z_index`. Возвращает список новых объектов-слоёв. |
| `BakedLayer(z_index=-100, chunk_size=None, opaque=False, background=(0,0,0))` | — | Компонент запечённого слоя (обычно создаётся через функции выше, а не напрямую). |
| `BakedLayer.bake(items)` | `items: список (surface, x, y)` | Запекает произвольный набор изображений с мировыми координатами. |
| `BakedLayer.chunk_count` | `int` (свойство) | Сколько поверхностей-чанков реально создано (только там, где что-то нарисовано). |
| `BakedLayer.premultiplied_supported()` | — (статический метод) | Доступно ли точное смешение полупрозрачности на данной сборке pygame. |

#### Пример использования

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

# Способ 1: сразу из сетки идентификаторов
grid = [
    [1, 1, 1, 1, 1],
    [1, None, None, None, 1],   # None — пустая клетка (тоже подходит -1; НЕ 0 — 0 является обычным id)
    [1, 1, 1, 1, 1],
]
tileset = {1: tile((110, 80, 50))}
ground = bake_tilemap(grid, tileset, tile_size=32, origin=(0, 300), z_index=-50)
scene.add_game_object(ground)
print("тайлов запечено:", ground.get_component(BakedLayer).item_count)

# Способ 2: запечь то, что уже лежит в сцене как обычные статичные спрайты
for i in range(200):
    deco = create_square(i * 34, 500, size=30, color=(70, 130, 70), name=f"Grass{i}",
                         add_collider=False, is_static=True)
    scene.add_game_object(deco)

layers = bake_static_sprites(scene)      # сотни блитов травы -> несколько блитов чанков
print("создано запечённых слоёв:", len(layers))
```

---

## 10. Статические сервисы и утилиты

Все сервисы этого раздела доступны из любого места кода — импортом класса, без ссылки на `Engine` или `Scene`.

### Time

**Описание:** Глобальные часы движка. `fixed_delta_time` — длительность одного физического шага (по умолчанию 1/60 с, меняется через `Engine(fixed_fps=...)` или `Time.set_fixed_rate(hz)`); `alpha` — доля (0…1) прогресса между двумя последними физическими шагами, которую использует интерполяция отрисовки (см. [4.4](#44-иерархия-трансформаций-transform)); `time_scale = 0` ставит игру на паузу (гравитация и геймплей останавливаются).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Time.delta_time` / `unscaled_delta_time` | `float` | Переменный шаг кадра, с учётом `time_scale` и без. |
| `Time.fixed_delta_time` | `float` | Длительность физического шага. |
| `Time.time` / `unscaled_time` / `fixed_time` | `float` | Накопленное время игры. |
| `Time.time_scale` | `float` | Множитель скорости всей игры; `0` — пауза. |
| `Time.alpha` | `float` | 0…1 между физическими шагами — для интерполяции. |
| `Time.frame_count` / `fixed_frame_count` | `int` | Счётчики кадров и физических шагов. |
| `Time.set_fixed_rate(hz)` | `hz: float` | Изменить частоту физики: `Time.set_fixed_rate(120)`. |
| `Time.reset()` | — | Сбросить все значения к значениям по умолчанию (используется в тестах). |

#### Пример использования

```python
from engine.core.game_time import Time

Time.time_scale = 0.0     # пауза: физика и update() продолжают вызываться, но dt = 0
Time.time_scale = 0.5     # замедление в 2 раза
print(f"кадр №{Time.frame_count}, физический шаг {Time.fixed_delta_time * 1000:.2f} мс")
```

### EventBus

**Описание:** Глобальная шина publish/subscribe плюс отдельная шина на каждом `GameObject` (`go.events`) — события объекта никогда не долетают до глобальных подписчиков и наоборот. `owner=` привязывает подписку к владельцу (`Scene`, `GameObject`): при его уничтожении `Scene.destroy()`/`GameObject.destroy()` сами отписывают все его подписки, что снимает необходимость вручную отписываться и предотвращает утечки. Исключение в обработчике логируется через `Debug`, остальные обработчики всё равно выполняются.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `EventBus.subscribe(event, callback, owner=None, once=False, priority=0, weak=False)` | `event: str, callback: вызываемый, owner: любой объект, once: bool, priority: int, weak: bool` | Подписка на глобальное событие; `weak=True` хранит колбэк слабой ссылкой (уничтоженный слушатель отписывается сам). |
| `EventBus.emit(event, *args, **kwargs)` | `event: str, *args, **kwargs` | Оповестить подписчиков: `EventBus.emit("game_over", score=120)`. |
| `EventBus.unsubscribe(event, callback)` / `unsubscribe_owner(owner)` | — | Отписать конкретный колбэк / все подписки данного владельца разом. |
| `EventBus.once(event, callback, **kwargs)` | — | Сработает один раз, затем отпишется сама. |
| `EventBus.has_listeners(event)` / `listener_count(event=None)` | — | Есть ли подписчики / сколько их. |
| `go.events` | `EventDispatcher` | Личная шина объекта: `player.events.subscribe("jumped", hud.on_jump)`. |

#### Пример использования

```python
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("events")
EventBus.subscribe("coin_collected", lambda amount: print(f"+{amount} очков"), owner=scene)

player = GameObject(name="Player")
scene.add_game_object(player)
player.events.subscribe("jumped", lambda height: print(f"прыжок на {height} px"))

EventBus.emit("coin_collected", amount=10)      # услышит глобальный подписчик
player.events.emit("jumped", height=64)         # услышит только подписчик этого объекта

scene.destroy()          # подписка scene на "coin_collected" снимается автоматически
```

### ObjectPool и GameObjectPool

**Описание:** Переиспользование объектов вместо постоянного создания/удаления — снимает рывки сборщика мусора Python при частом спавне (пули, частицы, всплывающий текст). `ObjectPool` — обобщённый пул для любых объектов-фабрик; `GameObjectPool` — специализация для `GameObject` внутри конкретной `Scene`: неактивные объекты остаются в сцене, но выключены (`active=False`), поэтому спавн — это просто включение флага, без изменения списков сцены. Компоненты могут реализовать `on_spawn(**kwargs)` / `on_despawn()` для сброса своего состояния (`Rigidbody2D` останавливает себя сам).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `ObjectPool(factory, on_spawn=None, on_despawn=None, initial_size=0, max_size=None, name="ObjectPool")` | `factory: вызываемый без аргументов` | Общий пул. `initial_size` — сколько создать заранее («прогрев»). |
| `GameObjectPool(scene, factory, initial_size=0, max_size=None, name="GameObjectPool", clear_events_on_despawn=False)` | `scene: Scene, factory: вызываемый, возвращающий готовый GameObject` | Пул объектов конкретной сцены. |
| `spawn(*args, **kwargs)` (`ObjectPool`) / `spawn(x=None, y=None, **kwargs)` (`GameObjectPool`) | — | Выдать объект из пула (или создать новый, если свободных нет); `None`, если достигнут `max_size`. `**kwargs` передаются в `on_spawn` компонентов. |
| `despawn(obj)` | `obj` | Вернуть объект в пул. Для `GameObject` то же делает `go.despawn()`. |
| `despawn_all()` | — | Вернуть в пул все активные объекты. |
| `prewarm(count)` | `count: int` | Создать `count` объектов заранее, не активируя. |
| `active_count` / `free_count` | `int` (свойства) | Сколько объектов сейчас выдано / свободно в пуле. |

#### Пример использования

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

bullet = bullets.spawn(x=100, y=200)             # переиспользует свободный объект пула
if bullet is not None:
    bullet.get_component(Rigidbody2D).velocity.x = 500

for _ in range(90):
    scene.tick(1 / 60)

bullet.despawn()                                  # вернуть в пул, а не destroy()
print("свободно в пуле:", bullets.free_count, "/ выдано:", bullets.active_count)
```

### PlayerPrefs

**Описание:** Юнити-подобное хранилище настроек и прогресса поверх одного JSON-файла (по умолчанию `playerprefs.json` в рабочей директории). Значения типизированы: `get_int` по ключу, где на самом деле лежит строка, вернёт значение по умолчанию, а не ошибку. `save()` пишет атомарно (через временный файл), поэтому падение игры на записи не может оставить повреждённый файл; если существующий файл всё же не читается, он переименовывается в `*.corrupt`, ошибка логируется, а игра продолжает работу с пустым хранилищем. `Engine` сам сохраняет несохранённые изменения при выходе.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `PlayerPrefs.set_path(path)` / `get_path()` | `path: str` | Использовать другой файл (сбрасывает несохранённые изменения). |
| `set_int(key, value)` / `get_int(key, default=0)` | `key: str, value: int, default: int` | Целые числа: `PlayerPrefs.set_int("high_score", 4200)`. |
| `set_float(key, value)` / `get_float(key, default=0.0)` | `key: str, value: float, default: float` | Дробные числа. |
| `set_string(key, value)` / `get_string(key, default="")` | `key: str, value: str, default: str` | Строки. |
| `has_key(key)` / `delete_key(key)` / `delete_all()` | `key: str` | Проверка наличия / удаление одного значения / очистка всего хранилища. |
| `save()` | — | Атомарно записать на диск. Ничего не попадает на диск до этого вызова. |
| `reload()` | — | Отбросить несохранённые изменения и перечитать файл. |
| `is_dirty()` | — | Есть ли несохранённые изменения. |

#### Пример использования

```python
from engine.core.player_prefs import PlayerPrefs

PlayerPrefs.set_path("saves/profile.json")

PlayerPrefs.set_int("high_score", 4200)
PlayerPrefs.set_string("player_name", "Georgii")
PlayerPrefs.set_float("music_volume", 0.6)
PlayerPrefs.save()                              # ничего не пишется на диск до этой строки

print(PlayerPrefs.get_int("high_score"))        # 4200
print(PlayerPrefs.get_int("no_such_key", 0))    # 0 — значение по умолчанию
```

### AudioManager и AudioSource

**Описание:** `AudioManager` управляет музыкой, звуковыми эффектами, громкостью и позиционным звуком; два канала зарезервированы под музыку («две деки»), поэтому кроссфейд действительно накладывает треки друг на друга, а звуковые эффекты никогда не «крадут» музыкальный канал. Затухания идут внутри `update(dt)` и не блокируют игру. Итоговая громкость = мастер × (sfx или music) × громкость источника × затухание по расстоянию — пересчитывается каждый кадр, поэтому движение слайдера сразу влияет на уже играющие звуки. Позиционные звуки (`position=(x, y)`) линейно затухают между `min_distance` и `max_distance` вокруг слушателя (по умолчанию — активная камера) и панорамируются по горизонтальному смещению. `AudioSource` — компонент для звука, привязанного к объекту (`spatial=True` заставляет его следовать за объектом). Без звукового устройства всё превращается в запись в лог и не мешает игре работать дальше.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `AudioManager.play_music(path, loop=True, fade_in=0.0, volume=1.0)` | `path: str` | Запускает трек, обрывая предыдущий (с плавным нарастанием, если задан `fade_in`). |
| `AudioManager.crossfade_to(path, duration=2.0, loop=True, volume=1.0)` | `path: str, duration: float` | Плавно сменяет трек, старый и новый звучат одновременно во время перехода. |
| `AudioManager.stop_music(fade_out=0.0)` / `pause_music()` / `resume_music()` | — | Остановить (с затуханием) / поставить на паузу / возобновить музыку. |
| `AudioManager.play_sfx(sound, volume=1.0, loop=False, position=None, min_distance=100.0, max_distance=800.0, rolloff="linear")` | `sound: str или pygame.mixer.Sound, position: tuple` | Разовый или зацикленный звуковой эффект; `position` включает затухание по расстоянию и панораму. |
| `AudioManager.set_master_volume(v)` / `set_sfx_volume(v)` / `set_music_volume(v)` | `v: float 0..1` | Три независимых слайдера громкости. |
| `AudioManager.mute()` / `unmute()` / `toggle_mute()` / `is_muted()` | — | Общее приглушение звука. |
| `AudioManager.load_sound(path, cache=True)` | `path: str` | Предзагрузить и закэшировать звук заранее (избежать паузы при первом проигрывании). |
| `AudioManager.save_settings(prefix="audio.")` / `load_settings(prefix="audio.")` | `prefix: str` | Сохранить/загрузить три слайдера громкости через `PlayerPrefs`. |
| `AudioSource(path=None, volume=1.0, loop=False, play_on_start=False, spatial=False, min_distance=100.0, max_distance=800.0)` | — | Компонент-обёртка над `AudioManager` для конкретного объекта. |
| `AudioSource.play()` / `stop()` / `pause()` / `resume()` | — | Управление воспроизведением. |
| `AudioSource.load(path)` / `set_volume(v)` | `path: str` / `v: float` | Сменить звук / громкость. |

#### Пример использования

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

AudioManager.play_sfx("assets/coin.wav", volume=0.7, position=(420, 280))   # разовый позиционный звук
AudioManager.crossfade_to("assets/battle.ogg", duration=2.0)                # плавная смена трека
```

### Debug

**Описание:** Единая точка логирования и отладочных оверлеев. `Debug` — псевдоним `DebugManager` (`Debug.log(...)` в стиле Unity `Debug.Log`). Встроенные оверлеи переключаются функциональными клавишами (переназначаются через `debug.keys`): **F1** — статистика (FPS, время кадра, число сущностей, вызовы отрисовки, счётчики физики), **F2** — контуры коллайдеров и векторы скорости, **F3** — координатная сетка мира, **F4** — прокручиваемая консоль последних логов. `Engine(debug=False)` отключает все горячие клавиши и оверлеи разом — для релизной сборки.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Debug.log(message, source=None)` | `message: любой, source: str` | Обычная запись в лог: `Debug.log("Уровень загружен")`. |
| `Debug.log_warning(message, source=None)` / `log_error(message, source=None)` | — | Предупреждение / ошибка (разные цвета в консоли F4). |
| `Debug.log_exception(exc, source=None)` | `exc: Exception` | Записать исключение как ошибку. |
| `Debug.clear_logs()` | — | Очистить историю логов. |
| `debug.set_stat(name, value)` | `name: str, value: любой или None` | Добавить свою строку в оверлей F1 (`None` — убрать). |
| `debug.toggle_overlay()` / `toggle_colliders()` / `toggle_grid()` / `toggle_console()` | — | Программно переключить любой из четырёх оверлеев. |
| `debug.keys` | `dict` | Переназначение клавиш: `debug.keys["console"] = "grave"`. |

#### Пример использования

```python
from engine.core.debug_manager import Debug

Debug.log("Игра запущена")
Debug.log_warning("Текстура не найдена, используется заглушка")
try:
    1 / 0
except ZeroDivisionError as exc:
    Debug.log_exception(exc, source="Инициализация")
```

### Vector2 и вспомогательные утилиты

**Описание:** `Vector2` — минимальный 2D-вектор, используемый везде, где иначе пришлось бы носить пару `x`/`y` (позиция, скорость, смещение камеры). `engine.primitives` — быстрые фабрики готовых `GameObject` (прямоугольник, квадрат, круг, треугольник, линия) со спрайтом и, по желанию, коллайдером и `Rigidbody2D` — удобно для прототипирования без подготовки своих изображений.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и пример применения |
| :--- | :--- | :--- |
| `Vector2(x=0.0, y=0.0)` | `x: float, y: float` | Поддерживает `+`, `-`, унарный `-`, `*`/`/` на число, `+=`, `-=`, `==`. |
| `copy()` | — | Независимая копия. |
| `length()` | — | Длина вектора (`math.hypot`). |
| `normalized()` | — | Вектор той же длины 1 (для нулевого вектора — `(0, 0)`, без деления на ноль). |
| `lerp(other, t)` | `other: Vector2, t: float` | Линейная интерполяция; `t` зажимается в `[0, 1]`. |
| `as_tuple()` / `as_int_tuple()` | — | Обычный `(x, y)` или округлённый до целых. |
| `Vector2.zero()` / `Vector2.one()` | — (статические) | Быстрые `(0, 0)` и `(1, 1)`. |
| `create_rectangle(x=0, y=0, width=50, height=50, color=(200,200,200), name="Rectangle", add_collider=True, add_rigidbody=False, border_radius=0, is_static=False, layer=0)` | — | Готовый прямоугольный `GameObject`. |
| `create_square(x=0, y=0, size=50, ..., is_static=False, layer=0)` | — | То же для квадрата (сторона `size`). |
| `create_circle(x=0, y=0, radius=25, ..., precise_collider=False, is_static=False, layer=0)` | — | Круг; `precise_collider=True` даёт `CircleCollider2D` вместо квадратного хитбокса-приближения. |
| `create_triangle(x=0, y=0, size=50, ..., is_static=False, layer=0)` / `create_line(x=0, y=0, length=100, thickness=4, ..., vertical=False, is_static=False, layer=0)` | — | Треугольник, вписанный в квадрат `size×size`, и отрезок (горизонтальный или вертикальный). |

#### Пример использования

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
