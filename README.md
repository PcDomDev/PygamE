# PygamE — 2D-движок (ECS-фреймворк)

> **PygamE** — компактный 2D-движок и фреймворк на базе **Pygame** с компонентной архитектурой в стиле Unity (ECS: `GameObject` + `Component`) для создания 2D-игр и интерактивных приложений. Из коробки: детерминированная физика с фиксированным шагом (swept AABB, слои и маски столкновений, колбэки столкновений и триггеров), иерархия трансформаций с интерполяцией при отрисовке, экранный UI с якорями, пулированная система частиц, запекание тайлмапов, камера, анимация, аудио с кроссфейдом и позиционным звуком, опциональный ввод с геймпада, сетевая игра по LAN (хост/подключение, репликация объектов, RPC) и статические сервисы (`Input`, `EventBus`, `PlayerPrefs`, `Debug`, `NetworkManager`). Архитектурные преимущества: физика никогда не зависит от частоты кадров, отрисовка и симуляция платят только за то, что видно и что действительно движется, сцены можно безопасно переключать посреди кадра, а единственная зависимость — Pygame.

## Оглавление

1. [Обзор и архитектурные принципы](#1-обзор-и-архитектурные-принципы)
2. [Требования и установка](#2-требования-и-установка)
3. [Быстрый старт](#3-быстрый-старт)
4. [Каркас движка и жизненный цикл](#4-каркас-движка-и-жизненный-цикл)
   - 4.1. [Engine и главный цикл](#41-engine-и-главный-цикл)
   - 4.2. [Управление сценами (Scene и SceneManager)](#42-управление-сценами-scene-и-scenemanager)
   - 4.3. [GameObject и компонентная модель](#43-gameobject-и-компонентная-модель)
   - 4.4. [Иерархия трансформаций](#44-иерархия-трансформаций)
5. [Физическая система](#5-физическая-система)
   - 5.1. [Rigidbody2D](#51-rigidbody2d)
   - 5.2. [Коллайдеры (BoxCollider2D, CircleCollider2D)](#52-коллайдеры-boxcollider2d-circlecollider2d)
   - 5.3. [Слои и маски столкновений](#53-слои-и-маски-столкновений)
6. [Система ввода](#6-система-ввода)
   - 6.1. [Ввод с геймпада](#61-ввод-с-геймпада)
   - 6.2. [PlayerController](#62-playercontroller)
7. [Система пользовательского интерфейса (UI)](#7-система-пользовательского-интерфейса-ui)
   - 7.1. [Canvas и экранный UI](#71-canvas-и-экранный-ui)
   - 7.2. [Элементы UI (UIText, UIButton, UIPanel, UIHealthBar)](#72-элементы-ui-uitext-uibutton-uipanel-uihealthbar)
   - 7.3. [Якоря и точки опоры UI](#73-якоря-и-точки-опоры-ui)
8. [Система частиц](#8-система-частиц)
9. [Графика, анимация и отрисовка](#9-графика-анимация-и-отрисовка)
   - 9.1. [SpriteRenderer и якоря спрайтов](#91-spriterenderer-и-якоря-спрайтов)
   - 9.2. [Камера](#92-камера)
   - 9.3. [Анимация и спрайт-листы (Animator)](#93-анимация-и-спрайт-листы-animator)
   - 9.4. [Оптимизация тайлмапов (запекание)](#94-оптимизация-тайлмапов-запекание)
10. [Статические сервисы и утилиты](#10-статические-сервисы-и-утилиты)
11. [Сеть (многопользовательская игра по LAN)](#11-сеть-многопользовательская-игра-по-lan)
    - 11.1. [NetworkManager](#111-networkmanager)
    - 11.2. [Сетевые компоненты (NetworkIdentity, NetworkTransform, NetworkState)](#112-сетевые-компоненты-networkidentity-networktransform-networkstate)

## 1. Обзор и архитектурные принципы

PygamE построен вокруг одной идеи: **мир состоит из объектов, а поведение объекта состоит из компонентов, которые вы к нему прикрепляете**. `GameObject` сам не умеет ни рисовать себя, ни падать, ни реагировать на нажатие клавиши — всё это делают прикреплённые к нему компоненты.

| Роль в ECS | Что это в PygamE | Ответственность |
| :--- | :--- | :--- |
| **Entity (сущность)** | `GameObject` | Именованный контейнер: `Transform`, список компонентов, флаги `active` / `is_static` / `layer` и иерархия «родитель — потомок». |
| **Component (компонент)** | `Component` и его подклассы: `SpriteRenderer`, `Rigidbody2D`, `BoxCollider2D`, `Animator`, `PlayerController`, `Camera`, `ParticleSystem`, `UIText` и т. д. | Данные и поведение. Ваш собственный игровой код — тоже компоненты (`class Enemy(Component)`). |
| **System (система)** | `PhysicsWorld` и `RenderSystem` (создаются в каждой `Scene`), а также статические сервисы `Input`, `AudioManager`, `EventBus` и др. | Сквозная логика над множеством компонентов: физика, отрисовка, звук, события. |
| **Scene (сцена)** | `Scene` | Владеет объектами и системами. Её индексы (по типу компонента, по порядку обновления) поддерживаются инкрементально. |
| **Engine (движок)** | `Engine` | Окно, часы и главный цикл. |

> **О терминологии.** «ECS» в PygamE означает компонентную модель в стиле Unity (компонент хранит и данные, и поведение), а не data-oriented ECS с «голыми» данными и отдельными системами.

### Архитектурные принципы

1. **Два отсчёта времени.** Физика работает в `fixed_update` с фиксированным шагом (по умолчанию 60 Гц); игровая логика, анимация и камера работают в `update` с переменным `dt`. При падении частоты кадров физика выполняет несколько шагов подряд, а не «растягивает» один: результат зависит только от *числа шагов* и никогда — от частоты кадров.
2. **Интерполяция при отрисовке.** Между физическими шагами позиции тел интерполируются (`Time.alpha`), поэтому движение остаётся плавным на мониторах от 144 Гц.
3. **Глобальный порядок обновления.** `Component.update_order` действует на всю сцену, а не только внутри одного объекта: физика (−100) → коллайдеры (−90) → игровая логика (0) → камера (100). Камера всегда видит итоговые позиции кадра.
4. **Платите только за используемое.** Сцена вызывает только те хуки, которые действительно *переопределены*; статические объекты (`is_static=True`) полностью пропускают физику и пересчёты; рисуются только спрайты, видимые камере; тайлмапы запекаются в считаные блиты.
5. **Безопасность посреди кадра.** `GameObject.destroy()`, `Scene.remove_game_object()` и `SceneManager.change_scene()`, вызванные из `update`, колбэка столкновения или нажатия кнопки, применяются в конце текущей фазы — цикл обхода никогда не ломается.
6. **Статические сервисы.** `Input`, `Time`, `EventBus`, `AudioManager`, `PlayerPrefs`, `Debug`, `SceneManager`, `CollisionLayers` и `NetworkManager` доступны из любого места без ссылки на `Engine`.
7. **Предсказуемые координаты.** Единицы измерения — пиксели, ось Y направлена вниз, углы измеряются в градусах по часовой стрелке.

### Кадр движка

```text
Engine.run()
 └─ каждый кадр:
     ├─ события pygame → Input; отладочные горячие клавиши (F1–F4)
     ├─ SceneManager.update(dt) → Scene.tick(dt)
     │    ├─ 0…N раз: Scene.fixed_update(1/60)
     │    │     ├─ Component.fixed_update()   (приложение сил)
     │    │     └─ PhysicsWorld.step()        (движение → контакты → колбэки)
     │    ├─ Scene.update(dt)                 (Component.update() в порядке update_order)
     │    └─ отложенные уничтожения и смены сцены
     ├─ AudioManager.update(dt)               (затухания, громкость)
     ├─ NetworkManager.update()               (опрос сокетов, применение полученного; вне сессии ничего не делает)
     └─ отрисовка: фон → Scene.draw() [мир через камеру → UI поверх] → отладочные оверлеи → flip
```

### Ключевые возможности

- **Физика:** фиксированный шаг, swept-AABB без туннелирования и дрожания, гравитация / ускорение / трение / сопротивление / масса, слои и маски столкновений, события `enter` / `stay` / `exit` и для столкновений, и для триггеров. → [Раздел 5](#5-физическая-система)
- **Сцены и объекты:** жизненный цикл `start` / `update` / `fixed_update` / `draw` / `destroy`, кэшированная иерархия трансформаций (`is_dirty`), отложенное уничтожение. → [Раздел 4](#4-каркас-движка-и-жизненный-цикл)
- **Отрисовка:** отсечение по камере, пространственная сетка, запекание тайлмапов, кэш повёрнутых/масштабированных спрайтов, пропуск анимации за пределами экрана. → [Раздел 9](#9-графика-анимация-и-отрисовка)
- **UI:** экранный Canvas, `UIText` / `UIButton` / `UIPanel` / `UIHealthBar`, девять якорей и точек опоры, UI в мировых координатах. → [Раздел 7](#7-система-пользовательского-интерфейса-ui)
- **Частицы:** эмиттер на базе `ObjectPool`, цветовые градиенты, масштабирование, затухание. → [Раздел 8](#8-система-частиц)
- **Геймпады:** включаются по желанию, единые названия кнопок и осей для любого геймпада (раскладка в стиле Xbox через SDL), аналоговые стики с мёртвой зоной, горячее подключение, по одному геймпаду на игрока. → [Раздел 6.1](#61-ввод-с-геймпада)
- **Управление персонажем:** `PlayerController` — вид сверху или платформер, coyote time, буферизация прыжка, мультипрыжок, инерция, которая сохраняется после порталов и взрывов, клавиатура и геймпад. → [Раздел 6.2](#62-playercontroller)
- **Сеть:** хост/подключение по LAN поверх TCP, автоматический поиск серверов, репликация объектов с авторитетом владельца, RPC, подключение посреди игры. → [Раздел 11](#11-сеть-многопользовательская-игра-по-lan)
- **Сервисы:** `Input` со строковыми названиями клавиш, `EventBus` (глобальный и для отдельных объектов), `ObjectPool`, `PlayerPrefs`, `AudioManager`, `Debug`. → [Раздел 10](#10-статические-сервисы-и-утилиты)

---

## 2. Требования и установка

**Требования**

| Компонент | Версия |
| :--- | :--- |
| Python | 3.8+ (движок не использует синтаксис новее 3.8; проверено на 3.12) |
| pygame | 2.x (проверено на 2.6.1) |
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
engine/                    сам движок — не зависит от вашей игры
├── core/                    app.py (Engine) · scene.py · scene_manager.py · game_object.py
│                            game_time.py (Time) · event_bus.py · object_pool.py
│                            player_prefs.py · spatial_hash.py · debug_manager.py
├── components/              transform · sprite_renderer · animator · camera · rigidbody2d
│                            collider2d / box_collider2d / circle_collider2d
│                            particle_system · audio_source · player_controller · component
│                            network_identity · network_transform · network_state
├── physics/                 physics_world.py · layers.py · collision.py
├── rendering/               render_system.py · surface_cache.py · tilemap.py
├── input/                   input_manager.py (Input) · key.py (Key)
├── ui/                      ui_element · canvas · ui_text · ui_button · ui_panel
│                            ui_health_bar · ui_layout · ui_style
├── audio/                   audio_manager.py
├── networking/              network_manager.py (NetworkManager) · connection.py · protocol.py · discovery.py
├── utils/                   vector2 · anchors · fonts · spritesheet_loader · warnings
└── primitives.py            фабрики create_rectangle / square / circle / triangle / line
tests/                     test_engine.py · test_physics_and_gamepad.py · test_networking_*.py — тесты без окна · benchmark.py — замеры
examples/                  showcase.py — демо-уровень, задействующий все системы
main.py                    точка входа вашей игры
requirements.txt
```

Импорты всегда идут от корня проекта: `from engine.core.app import Engine`. `engine/` ничего не знает о вашей игре — код вашей игры находится снаружи.

### Проверка установки (smoke-тест)

Скрипт ниже не открывает окно и не требует звуковой карты (он использует «пустые» драйверы SDL — dummy): создаёт сцену, роняет тело на пол и проверяет, что физика отработала. Сохраните его как `smoke_test.py` в **корне проекта** и запустите.

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

for _ in range(180):                 # 3 секунды симуляции при 60 кадрах/с
    scene.tick(1 / 60)

assert body.is_grounded, "the body should have landed on the floor"
assert abs(ball.transform.world_y - 180) < 1e-6, ball.transform.world_y   # верх пола 200 − высота 20
print("PygamE is working: the body landed at y =", ball.transform.world_y)
```

```bash
python smoke_test.py                     # ожидается строка "PygamE is working: ..."
python -m unittest discover tests        # полный набор тестов; ожидается "OK"
python examples/showcase.py              # играбельное демо (открывает окно)
python examples/showcase.py --headless 300 shot.png   # то же самое, но без окна, со скриншотом
```

Если `smoke_test.py` завершается без ошибок, установка выполнена верно: Python, pygame и движок работают вместе.

---

## 3. Быстрый старт

Минимальная игра: платформер с двойным прыжком, монетами, камерой и счётчиком очков. Сохраните её как `main.py` в корне проекта.

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

        # Земля и платформа — статические: пропускают физику и никогда не пересчитываются
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

        # HUD: якорь прикрепляет текст к углу экрана
        hud = GameObject(12, 12, name="HUD")
        self.score_text = hud.add_component(UIText("Coins: 0", anchor="TopLeft"))
        self.add_game_object(hud)

    def on_coin_touched(self, coin_collider, other_collider):
        if other_collider.game_object.name == "Player":
            coin_collider.game_object.destroy()     # можно смело вызывать прямо внутри колбэка
            self.score += 1
            self.score_text.set_text(f"Coins: {self.score}")


def main():
    engine = Engine(1280, 720, "PygamE — Quick Start", fps=144,
                    background_color=(120, 172, 226))
    engine.change_scene(GameScene)            # создаёт сцену, вызывает start()
    engine.run()


if __name__ == "__main__":
    main()
```

```bash
python main.py
```

**Управление:** `A` / `D` или `←` / `→` — движение, `Space` — прыжок (второй раз — в воздухе), `Esc` закрывает окно, если вы сами это обрабатываете (см. [Input](#6-система-ввода)). **Отладка:** `F1` — статистика, `F2` — коллайдеры, `F3` — сетка мира, `F4` — консоль лога.

Что сейчас произошло:

1. `Engine` открыл окно и запустил главный цикл ([4.1](#41-engine-и-главный-цикл)).
2. `change_scene(GameScene)` создал сцену и вызвал `start()`, где мы построили мир из `GameObject`ов ([4.2](#42-управление-сценами-scene-и-scenemanager), [4.3](#43-gameobject-и-компонентная-модель)).
3. Физика работает с фиксированным шагом, а `PlayerController` читает ввод каждый кадр ([5.1](#51-rigidbody2d), [Input](#6-система-ввода)).
4. Монета — статический триггер: колбэк срабатывает при касании ([5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)).
5. Камера следует за игроком, а HUD остаётся на месте — UI рисуется в экранных координатах ([9.2](#92-камера), [7.1](#71-canvas-и-экранный-ui)).

---

## 4. Каркас движка и жизненный цикл

### 4.1. Engine и главный цикл

**Описание:** `Engine` владеет окном, часами и главным циклом — это единственный класс, который нужен `main.py`. Каждый кадр он передаёт события в `Input`, обрабатывает отладочные горячие клавиши, вызывает `SceneManager.update()` (фиксированные физические шаги, затем переменный `update`), обновляет звук и рисует сцену. Физика никогда не зависит от частоты кадров: `fps` лишь ограничивает, как часто перерисовывается экран, а `fixed_fps` задаёт частоту физики. При выходе `Engine` уничтожает активную сцену (вызывая каждый `on_destroy`), останавливает звук, сохраняет несохранённые `PlayerPrefs` и завершает работу pygame.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Engine(...)` | `width: int = 1280, height: int = 720, title: str = "Pygame Engine", fps: int = 60, background_color: tuple = (30, 30, 35), fixed_fps: int = 60, vsync: bool = False, resizable: bool = False, debug: bool = True, gamepad: bool = False, gamepad_deadzone: float = 0.2` | Создаёт окно и подсистемы. `fps=0` — частота кадров без ограничения; `fixed_fps` — частота физики в Гц; `vsync=True` запрашивает вертикальную синхронизацию (включает флаг `SCALED`); `resizable` разрешает менять размер окна; `debug=False` отключает все отладочные горячие клавиши и оверлеи (релизная сборка); `gamepad=True` включает ввод с геймпада (см. [6.1](#61-ввод-с-геймпада)) с заданной мёртвой зоной стиков `gamepad_deadzone`. |
| `run()` | — | Блокирующий главный цикл. Завершается, когда окно закрыто или вызван `quit()`. Вызывайте его последним: `engine.run()`. |
| `quit()` | — | Останавливает цикл после текущего кадра: `engine.quit()`. |
| `load_scene(name, scene)` | `name: str, scene: Scene` | Регистрирует готовый экземпляр сцены под именем и сразу делает его активным; предыдущая сцена, если она есть, остаётся жить (см. [4.2](#42-управление-сценами-scene-и-scenemanager)). |
| `change_scene(target, *args, **kwargs)` | `target: a Scene class, instance, or name` | Уничтожает текущую сцену и запускает новую: `engine.change_scene(Level1, difficulty=2)`. Обёртка над `SceneManager.change_scene`. |
| `active_scene` | `Scene or None` (свойство) | Текущая активная сцена. |
| `screen` | `pygame.Surface` | Поверхность окна. |
| `clock` | `pygame.time.Clock` | Часы главного цикла. |
| `input` / `debug` / `audio` / `network` | `Input` / `DebugManager` / `AudioManager` / `NetworkManager` | Подсистемы, которыми владеет движок (те же экземпляры, что и статические сервисы). `Engine.run()` вызывает `NetworkManager.update()` раз в кадр, так что вам этого делать не нужно. |
| `scene_manager` | `SceneManager` | Статический менеджер сцен (сам класс). |
| `width`, `height`, `fps`, `background_color`, `running` | `int`, `int`, `int`, `tuple`, `bool` | Параметры окна и флаг «цикл работает». |
| `Engine.MAX_DELTA_TIME` | `float = 0.05` | Верхняя граница переменного `dt`, передаваемого в `update` (защита от скачка после паузы в отладчике). На физику не влияет — у неё свои ограничения: `Time.max_frame_time` и `Time.max_fixed_steps`. |

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
        Debug.log("Scene started")

    def update(self, delta_time):
        super().update(delta_time)          # без super() компоненты никогда не обновляются
        self.elapsed += delta_time
        if self.elapsed > 3.0:              # закрыть окно через 3 секунды
            pygame.event.post(pygame.event.Event(pygame.QUIT))


def main():
    engine = Engine(
        width=1280, height=720, title="Demo",
        fps=0,                # частота кадров без ограничения (или vsync=True)
        fixed_fps=60,         # физика всегда работает с частотой 60 шагов в секунду
        resizable=True,
        debug=True,           # F1–F4 работают; False — для релизной сборки
    )
    engine.change_scene(DemoScene)
    engine.run()


if __name__ == "__main__":
    main()
```

### 4.2. Управление сценами (Scene и SceneManager)

**Описание:** `Scene` — это набор `GameObject`ов плюс системы, которые ими управляют: `physics` (`PhysicsWorld`) и `render_system` (`RenderSystem`). Хуки жизненного цикла: `start()` (один раз, при загрузке), `update(dt)` (каждый кадр), `fixed_update(dt)` (каждый физический шаг), `draw(screen)` и `destroy()` (при выходе). Базовые `update` / `fixed_update` / `draw` **как раз и запускают ваши компоненты**, поэтому подкласс всегда должен вызывать `super()`. `SceneManager` — статический менеджер: `SceneManager.change_scene(Level1Scene)` уничтожает текущую сцену (`destroy()` освобождает объекты, подписки и физические/графические структуры — после этого старую сцену подбирает сборщик мусора) и запускает новую (`start()`). Если переключение запрошено *посреди кадра* (клик по кнопке, колбэк столкновения), оно откладывается до конца этого кадра; в любой другой момент (запуск программы, тесты) оно происходит немедленно.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Scene(name)` | `name: str = "Scene"` | Создаёт пустую сцену. Имя по умолчанию заменяется именем класса при загрузке через `SceneManager`. |
| `start()` | — | Хук: вызывается один раз, при загрузке. Стройте здесь свой мир и вызывайте `super().start()`. |
| `update(delta_time)` | `delta_time: float` | Хук: переменный шаг; запускает `update` компонентов в порядке `update_order`, затем применяет отложенные удаления. |
| `fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Хук: один физический шаг — сначала `fixed_update` компонентов, затем `physics.step()` и колбэки столкновений. |
| `draw(screen)` | `screen: pygame.Surface` | Хук: рисует мир через камеру, затем UI. `render(screen)` — старое имя; оно перенаправляет сюда. |
| `destroy()` | — | Хук: уничтожает все объекты и очищает системы сцены. Вызывается менеджером при выходе из сцены. |
| `add_game_object(go)` | `go: GameObject` | Добавляет объект **вместе с его потомками** и сразу запускает его: `scene.add_game_object(player)`. |
| `remove_game_object(go)` | `go: GameObject` | Убирает объект из сцены, не уничтожая его. Внутри цикла это откладывается до конца фазы. |
| `destroy_game_object(go)` | `go: GameObject` | Уничтожает объект (`on_destroy`, потомки, подписки). `go.destroy()` делает то же самое. |
| `find_game_object(name)` | `name: str` | Первый объект с таким именем или `None`. |
| `find_game_objects_with_tag(tag)` | `tag: str` | Список объектов с таким тегом. |
| `get_components(component_type)` | `component_type: type` | Все живые компоненты этого типа (включая подклассы) на активных объектах — свежий список, по которому безопасно итерироваться: `scene.get_components(UIButton)`. |
| `get_component(component_type)` | `component_type: type` | Первый компонент этого типа или `None`. |
| `set_active_camera(camera)` | `camera: Camera` | Задаёт камеру, через которую рисуется мир. Свойство `active_camera` возвращает её. |
| `screen_to_world(pos)` / `world_to_screen(pos)` | `pos: tuple or Vector2` | Преобразование координат через активную камеру: `scene.screen_to_world(Input.mouse_position())`. |
| `tick(frame_dt)` | `frame_dt: float` | Симулирует один кадр без окна: накапливает время, выполняет 0…N шагов `fixed_update`, затем `update`. Для тестов и инструментов. Возвращает, сколько физических шагов выполнено. |
| `game_objects`, `physics`, `render_system` | `list`, `PhysicsWorld`, `RenderSystem` | Список объектов сцены и её системы; порядок отрисовки задают `render_system.sort_y` / `sort_x` (см. [9.1](#91-spriterenderer-и-якоря-спрайтов)). |
| `entity_count`, `active_entity_count`, `draw_calls` | `int` | Всего объектов, активных объектов и вызовов отрисовки в последнем кадре. |
| `is_started`, `is_destroyed`, `name` | `bool`, `bool`, `str` | Состояние жизненного цикла и имя сцены. |
| `SceneManager.change_scene(...)` | `target, *args, immediate: bool = None, destroy_previous: bool = True, **kwargs` | Переключает сцены: `target` — класс `Scene`, экземпляр или зарегистрированное имя; `*args` / `**kwargs` передаются конструктору класса. Возвращает новую сцену или `None`, если переключение отложено до конца кадра. `immediate=True/False` принудительно выбирает одно из поведений. |
| `SceneManager.register(name, scene_or_class)` | `name: str, scene_or_class: Scene or type` | Регистрирует сцену или класс: `SceneManager.register("menu", MenuScene)`, после чего `change_scene("menu")` каждый раз создаёт свежий экземпляр. |
| `SceneManager.add_scene(name, scene)` / `set_active(name)` | `name: str, scene: Scene` | Устаревший API: регистрирует и переключает **без** уничтожения предыдущей сцены (её состояние сохраняется; `start()` выполняется только при первой активации). |
| `SceneManager.get_scene(name)` / `remove_scene(name)` | `name: str` | Получить зарегистрированный экземпляр / забыть его и уничтожить. |
| `SceneManager.active_scene` | `Scene or None` | Активная сцена. |
| `SceneManager.shutdown()` / `reset()` | — | Уничтожить активную сцену (вызывается `Engine` при выходе) / забыть всё (для тестов). |

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
        title.add_component(UIText("My Game", anchor="Center"))
        self.add_game_object(title)

        play = GameObject(0, 0, name="PlayButton")
        button = play.add_component(UIButton("Play", 200, 48, anchor="Center"))
        # Клик происходит внутри кадра — смена сцены применится в его конце
        button.on_click.append(lambda _button: SceneManager.change_scene(LevelScene, level=1))
        self.add_game_object(play)


class LevelScene(Scene):
    def __init__(self, level=1):
        super().__init__(f"Level{level}")
        self.level = level

    def start(self):
        super().start()
        print(f"Level {self.level} loaded")

    def destroy(self):
        print(f"Level {self.level} unloaded")
        super().destroy()


SceneManager.register("menu", MenuScene)     # по имени: каждый раз свежий экземпляр
SceneManager.change_scene("menu")            # до запуска цикла — происходит немедленно
SceneManager.change_scene(LevelScene, level=2)   # выгружает меню, загружает уровень 2
# В настоящей игре кадрами управляет Engine.run(); здесь — один кадр вручную:
SceneManager.update(1 / 60)
```

### 4.3. GameObject и компонентная модель

**Описание:** `GameObject` — контейнер с обязательным `Transform`; поведение добавляется через компоненты (`add_component`). Компоненты наследуются от `Component` и переопределяют только нужные им хуки — сцена вызывает **только переопределённые**, поэтому неиспользуемый хук ничего не стоит. Флаги объекта: `active` (неактивный объект не обновляется, не участвует в физике и не рисуется — как и все его потомки; см. `active_in_hierarchy`), `is_static` (объект никогда не будет двигаться: он пропускает физику и пересчёты, а его коллайдер и спрайт регистрируются один раз; чтобы подвинуть такой объект, сначала установите `is_static = False`) и `layer` (слой столкновений). `update_order` задаёт порядок запуска компонентов **глобально для всей сцены**.

| Компонент | `update_order` |
| :--- | :---: |
| `Rigidbody2D` | −100 |
| `BoxCollider2D` / `CircleCollider2D` | −90 |
| ваша игровая логика, `Animator`, `PlayerController`, UI | 0 |
| `Camera` | 100 |

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `GameObject(...)` | `x: float = 0.0, y: float = 0.0, name: str = "GameObject", layer: int or str = 0, tag: str = None, is_static: bool = False, parent: GameObject = None` | Создаёт объект с `Transform` в точке `(x, y)`. `parent` сразу прикрепляет его к родителю. |
| `add_component(component)` | `component: Component` | Прикрепляет компонент и возвращает его: `body = go.add_component(Rigidbody2D())`. Если объект уже находится в сцене, компонент запускается сразу. |
| `get_component(cls)` / `get_components(cls)` / `has_component(cls)` | `cls: type` | Первый компонент этого типа (или `None`) / список всех таких / проверка наличия. Соседние компоненты ищите в `start()`, а не в `__init__`. |
| `remove_component(component)` | `component: Component` | Отсоединяет компонент (выполняется его `on_destroy`). `Transform` удалить нельзя. |
| `transform` | `Transform` | Есть всегда — проверять на `None` не нужно. |
| `name`, `tag` | `str`, `str` | Имя и тег для поиска (`scene.find_game_object("Player")`). |
| `active` / `active_in_hierarchy` | `bool` | Собственный флаг объекта / «активен и каждый его предок тоже активен». |
| `is_static` | `bool` | Никогда не двигается — см. описание выше. |
| `layer` | `int or str` | Слой столкновений, по умолчанию наследуемый его коллайдерами: `go.layer = "enemy"` (см. [5.3](#53-слои-и-маски-столкновений)). |
| `parent` / `children` | `GameObject or None` / `list` | Иерархия; `children` — список потомков. |
| `set_parent(parent, keep_world_position=False)` | `parent: GameObject or None, keep_world_position: bool` | Меняет родителя (подробности в [4.4](#44-иерархия-трансформаций)). `add_child(child)` и `find_child(name)` — сокращения. |
| `x`, `y` | `float` | Псевдонимы локальной позиции: `go.x += 5`. |
| `scene` | `Scene or None` | Сцена, в которой объект находится сейчас. |
| `events` | `EventDispatcher` | Собственная шина событий объекта (см. [EventBus](#eventbus)): `go.events.emit("hit", damage=5)`. `clear_events()` сбрасывает её подписки. |
| `destroy()` | — | Уничтожает объект и его потомков. Внутри цикла откладывается до конца фазы, поэтому вызывать его из колбэков безопасно. Выполняет `on_destroy` у каждого компонента. |
| `despawn()` | — | Возвращает объект в его пул (если он пришёл из `GameObjectPool`), иначе вызывает `destroy()`. |
| `Component.start()` | — | Хук: один раз, при попадании в сцену. Здесь ищите соседние компоненты. |
| `Component.update(delta_time)` | `delta_time: float` | Хук: каждый кадр, переменный шаг. Ввод, анимация, визуальная логика. |
| `Component.fixed_update(fixed_delta_time)` | `fixed_delta_time: float` | Хук: каждый физический шаг, **до** самого физического шага — место для `add_force`. |
| `Component.draw_world(screen, offset_x, offset_y, alpha)` | `screen: Surface, offset_x: int, offset_y: int, alpha: float` | Хук: собственная отрисовка в мировых координатах (частицы, запечённые слои). Возвращает число блитов (или `None`). |
| `Component.on_destroy()` | — | Хук: когда объект уничтожен или компонент удалён — освобождайте ресурсы здесь. |
| `on_collision_enter/stay/exit(collision)` | `collision: Collision2D` | Необязательные методы-обработчики физики на любом компоненте (см. [5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)). |
| `on_trigger_enter/stay/exit(other)` | `other: Collider2D` | То же самое для триггеров. |
| `game_object`, `transform`, `events` | — | Объект-владелец, его `Transform` и его шина событий (сокращения). |
| `enabled` | `bool` | `False` — компонент не получает `update` / `fixed_update`. |
| `update_order`, `updates_when_static` | `int = 0`, `bool = True` | Порядок запуска (таблица выше). `updates_when_static = False` пропускает компонент на статических объектах. |

#### Пример использования

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_square


class Spinner(Component):
    """Rotation is a visual effect, so it belongs in update (every frame)."""

    def __init__(self, degrees_per_second=90):
        super().__init__()
        self.degrees_per_second = degrees_per_second

    def update(self, delta_time):
        self.game_object.transform.rotation += self.degrees_per_second * delta_time


class Thruster(Component):
    """Forces are applied in fixed_update — right before the physics step."""

    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)   # соседние компоненты ищем в start()

    def fixed_update(self, fixed_delta_time):
        self.body.add_force(0, -1200)       # тяга вверх, сильнее гравитации (500 px/s²)


class SelfDestruct(Component):
    def __init__(self, seconds):
        super().__init__()
        self.left = seconds

    def update(self, delta_time):
        self.left -= delta_time
        if self.left <= 0:
            self.game_object.destroy()      # откладывается до конца фазы — это безопасно

    def on_destroy(self):
        print(f"{self.game_object.name} destroyed")


scene = Scene("components")
rocket = create_square(200, 300, size=30, name="Rocket", add_rigidbody=True)
rocket.tag = "projectile"
rocket.add_component(Thruster())
rocket.add_component(Spinner(180))
rocket.add_component(SelfDestruct(2.0))
scene.add_game_object(rocket)

for _ in range(150):                         # 2,5 секунды симуляции
    scene.tick(1 / 60)
assert scene.find_game_object("Rocket") is None      # самоуничтожился
```

### 4.4. Иерархия трансформаций

**Описание:** Каждый `GameObject` автоматически получает `Transform`, хранящий его позицию, поворот и масштаб. Значения бывают двух видов: **локальные** (относительно родителя — именно они хранятся на самом деле) и **мировые** (результат композиции всей цепочки родителей). `position` — псевдоним `local_position`; у объекта без родителя локальные и мировые значения совпадают, поэтому код, написанный до появления иерархии, продолжает работать без изменений. Поворот измеряется в градусах по часовой стрелке (Y направлена вниз). Мировые значения кэшируются за флагом `is_dirty`: изменение трансформации помечает её и всё её поддерево «грязными», а чтение мирового значения пересчитывает его, только если оно «грязное», — неподвижная иерархия не пересчитывает вообще ничего. Отслеживаются даже правки «на месте» (`position.x += 5`). Для физических тел `get_render_xy(alpha)` даёт сглаженную позицию между двумя физическими шагами; потомки строятся от *сглаженной* позиции родителя, поэтому оружие в руках игрока никогда не отстаёт.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Transform(...)` | `x: float = 0.0, y: float = 0.0, rotation: float = 0.0, scale_x: float = 1.0, scale_y: float = 1.0` | Создаётся автоматически внутри `GameObject`. |
| `position` / `local_position` | `Vector2` | Локальная позиция; поддерживает правки «на месте»: `t.position.x += 10`. |
| `rotation` / `local_rotation` | `float` | Локальный поворот в градусах. |
| `scale` / `local_scale` | `Vector2` (число тоже принимается) | Локальный масштаб: `t.scale = 2`. Коллайдеры вместе с ним не масштабируются. |
| `world_position` | `Vector2` (копия), можно присваивать | Мировая позиция. Правка копии ничего не даёт — присваивайте: `t.world_position = Vector2(0, 0)`. |
| `world_rotation`, `world_scale` | `float`, `Vector2` | Мировой поворот и масштаб (только чтение). |
| `world_x`, `world_y`, `get_world_xy()` | `float`, `float`, `tuple` | Быстрое чтение мировой позиции без копирования. |
| `set_world_position(x, y)` | `x: float, y: float` | Задаёт мировую позицию (пересчитывает локальную). |
| `translate(dx, dy)` | `dx: float, dy: float` | Сдвигает в пространстве родителя. |
| `teleport(x, y)` | `x: float, y: float` | Перемещает без интерполяции, поэтому сглаживание никогда не «растягивает» скачок. |
| `parent` | `Transform or None` | Родитель (присваивание вызывает `set_parent`). |
| `set_parent(parent, keep_world_position=False)` | `parent: Transform, GameObject or None, keep_world_position: bool` | Меняет родителя. По умолчанию локальное смещение сохраняется; `keep_world_position=True` оставляет объект на том же месте в мире. Цикл (родитель, который одновременно потомок) вызывает `ValueError`. |
| `detach(keep_world_position=True)` | `keep_world_position: bool` | Отсоединяет от родителя. |
| `children`, `child_count`, `root`, `depth` | `tuple`, `int`, `Transform`, `int` | Навигация по иерархии. |
| `transform_point(x, y)` / `inverse_transform_point(x, y)` | `x: float, y: float` | Точка из локального пространства в мировое и обратно: `t.transform_point(30, 0)`. |
| `is_dirty`, `world_version` | `bool`, `int` | Кэш мировых значений: устарел ли он и сколько раз пересчитывался. |
| `interpolate` | `bool` | Включает сглаживание между физическими шагами (`Rigidbody2D` включает его сам). |
| `get_render_xy(alpha)` / `render_position` | `alpha: float` | Позиция для отрисовки с интерполяцией; `render_position` использует `Time.alpha`. |
| `reset_interpolation()` | — | «Предыдущая позиция := текущая»: следующий кадр рисуется ровно там, где стоит объект. |

#### Пример использования

```python
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square
from engine.utils.vector2 import Vector2

scene = Scene("hierarchy")

player = create_square(200, 300, size=40, name="Player", add_rigidbody=True)
sword = create_rectangle(0, 0, 30, 8, color=(220, 220, 230), name="Sword", add_collider=False)

sword.set_parent(player)                  # меч — потомок игрока
sword.transform.position.x = 40           # в 40 px справа от игрока (в локальном пространстве)
sword.transform.rotation = -30            # поворот относительно родителя
scene.add_game_object(player)             # потомок попадает в сцену вместе с родителем

print(sword.transform.get_world_xy())     # (240.0, 300.0): родитель + смещение
player.transform.position.x += 100        # игрок сдвинулся — меч следует за ним
print(sword.transform.get_world_xy())     # (340.0, 300.0)

world = sword.transform.world_position    # копия: её правка ничего не даёт
sword.transform.world_position = Vector2(500, 100)   # а так работает (мировые координаты)

sword.set_parent(None, keep_world_position=True)     # отсоединить, не сдвигая в мире
player.transform.teleport(500, 100)       # переместить без сглаживания
```

---

## 5. Физическая система

Физика PygamE — это `Rigidbody2D` (движение) + коллайдеры (форма) + `PhysicsWorld` (система, которую создаёт каждая сцена). Всё происходит в `fixed_update`, с интервалом `Time.fixed_delta_time` (по умолчанию 1/60 с). Порядок одного шага: `fixed_update` компонентов → обновление коллайдеров, сдвинутых скриптами → симуляция каждого тела → поиск контактов → колбэки (`exit`, затем `enter`, затем `stay`). Широкая фаза (broad phase) — равномерная сетка (`SpatialHash`): статические коллайдеры регистрируются один раз, а запросы запускают только движущиеся коллайдеры.

### 5.1. Rigidbody2D

**Описание:** Компонент, который двигает объект: скорость, ускорение, гравитация, сопротивление, трение и масса. Движение разрешается **по одной оси за раз с помощью сканирования вдоль пути (swept AABB)**: тело проходит ровно до ближайшего препятствия и останавливается вплотную к нему. Это значит: никакого туннелирования на любой скорости, никакого дрожания при приземлении и стабильный `is_grounded` (покой на поверхности — это контакт с нулевым зазором). Тело, которое начинает шаг внутри твёрдого объекта (появилось там или было телепортировано), выталкивается по оси наименьшего проникновения. Порядок внутри шага: силы, ускорение и гравитация → сопротивление (`exp(-drag·dt)` по обеим осям) → трение о землю (`friction · |gravity|` px/s² по горизонтали) → предел скорости от гравитации (`terminal_velocity`) → выталкивание из препятствий → движение по X → движение по Y. Единицы измерения — пиксели и секунды.

**Скорость падения и запуска.** Гравитация накапливается: каждый шаг добавляет `g · dt` к вертикальной скорости, поэтому падение начинается медленно и продолжает линейно ускоряться — по умолчанию **без ограничения** (`terminal_velocity=None`), так что чем больше `gravity`, тем заметно быстрее и жёстче падение. Позиция продвигается на *среднюю* скорость шага, что точно для постоянного ускорения: падение проходит ровно `g · t² / 2`, а прыжок достигает вершины ровно в `v² / (2g)` при любой частоте физики. Вторая формула подсказывает, как подобрать прыжок: для высоты `h` задайте телу (или `PlayerController.jump_force`) скорость около `sqrt(2 · g · h)` — при `gravity=4000` для прыжка на 100 px нужно примерно 890, а `jump_force=350` по умолчанию поднимет лишь на ~15 px. Ограничить падение можно двумя способами. Жёсткий предел `terminal_velocity=<px/s>`: большая гравитация тогда лишь быстрее достигает предела, и дальше любое падение выглядит одинаково. Или, что естественнее, сопротивление воздуха через `drag`: предельная скорость становится примерно `gravity / drag` и по-прежнему растёт вместе с гравитацией (`drag` замедляет и горизонтальное движение). В любом случае `terminal_velocity` ограничивает то, что может сделать *гравитация*, а не скорость тела: гравитация никогда не разгоняет тело выше этого предела, но тело, которое уже быстрее (вылет из портала, сильный импульс, взрыв), сохраняет свою скорость, пока его не замедлят `drag` или столкновение. Горизонтальная скорость и скорость вверх никогда не ограничиваются. `bounce` (0 — полная остановка, 1 — абсолютно упругий удар) отражает скорость вдоль нормали удара; удары медленнее 40 px/s «успокаивают» тело вместо дрожания.

**Порталы и другие телепортации.** `teleport(x, y, keep_velocity=True)` перемещает тело без сглаживания и не трогает его скорость; затем `redirect_velocity(dx, dy)` сохраняет скорость, но направляет её по новому направлению (куда смотрит выходной портал). Быстрые тела также не могут проскочить тонкий триггер вроде входа в портал — см. [5.2](#52-коллайдеры-boxcollider2d-circlecollider2d).

> **Ограничения.** Твёрдыми препятствиями могут быть только `BoxCollider2D` (круги работают только как триггеры). Тела считают друг друга неподвижными стенами (передачи импульса нет). Кинематические платформы не «увозят» стоящие на них тела. Размещайте `Rigidbody2D` на корневых объектах: на потомке он работает в локальном пространстве родителя (движок пишет предупреждение в лог).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Rigidbody2D(...)` | `gravity: float = 500, gravity_scale: float = 1.0, drag: float = 0.0, mass: float = 1.0, use_gravity: bool = True, is_kinematic: bool = False, terminal_velocity: float = None, friction: float = 0.0, acceleration: tuple or Vector2 = None, interpolate: bool = True, bounce: float = 0.0` | Создаёт тело. `gravity` (px/s²) и `gravity_scale` управляют падением; `drag` — сопротивление воздуха (1/с); `friction` — коэффициент трения о землю; `mass` делит силы и импульсы; `terminal_velocity` — необязательная скорость вниз, выше которой гравитация не может разогнать тело (`None` — без предела; тело, которое уже быстрее, сохраняет свою скорость); `acceleration` — постоянное ускорение (ветер, тяга); `is_kinematic` означает, что тело двигается только по `velocity`, не разрешает столкновения, но по-прежнему порождает события; `interpolate` включает плавную отрисовку между шагами; `bounce` — доля скорости, сохраняемая после удара (0 — ничего, 1 — вся). Все параметры также доступны как атрибуты. |
| `velocity` | `Vector2` | Скорость в px/s. Можно править напрямую: `body.velocity.x = 200`. `velocity_x` / `velocity_y` — скалярные псевдонимы. |
| `acceleration` | `Vector2` | Постоянное ускорение в px/s². |
| `is_grounded` | `bool` | `True`, если тело опирается на что-то снизу (обновляется каждый шаг). |
| `collider` | `BoxCollider2D or None` | Находится в `start()`; без него гравитация всё равно действует, но ничего не сталкивается (в лог пишется предупреждение). |
| `add_impulse(impulse_x, impulse_y)` | `impulse_x: float, impulse_y: float` | Мгновенное изменение скорости: `Δv = impulse / mass`. Прыжок, отбрасывание: `body.add_impulse(0, -400)`. |
| `add_force(force_x, force_y, delta_time=None)` | `force_x: float, force_y: float, delta_time: float = None` | Сила накапливается и применяется на **следующем** физическом шаге, затем обнуляется — вызывайте её каждый `fixed_update` для постоянного толчка. С `delta_time` действует прежнее поведение: `v += F / m · dt` сразу. |
| `stop()` | — | Обнуляет скорость и накопленные силы. |
| `teleport(x, y, keep_velocity=False)` | `x: float, y: float, keep_velocity: bool = False` | Перемещает в мировую точку без сглаживания. По умолчанию ещё и останавливает тело; с `keep_velocity=True` скорость остаётся нетронутой (тело лишь перестаёт считаться «стоящим на земле» и сбрасывает накопленные силы) — то, что нужно порталу: `body.teleport(ex, ey, keep_velocity=True)`. |
| `speed` | `float` (свойство) | Текущая скорость в px/s — длина `velocity`. |
| `redirect_velocity(direction_x, direction_y)` | `direction_x: float, direction_y: float` | Сохраняет текущую скорость, но направляет её по заданному направлению (нормализовать его не нужно): `body.redirect_velocity(1, 0)` отправляет тело вправо с той же скоростью. Нулевое направление ничего не меняет. |
| `on_spawn()` / `on_despawn()` | `**kwargs` / — | Хуки для `GameObjectPool`: тело само останавливается, когда его выдают из пула и когда возвращают в него. |

#### Пример использования

```python
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square

scene = Scene("physics")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

# Ящик с трением: он скользит и останавливается
crate = create_square(100, 300, size=40, name="Crate", add_rigidbody=True)
crate_body = crate.get_component(Rigidbody2D)
crate_body.friction = 0.6        # замедляется на 0.6 · gravity px/s² пока стоит на земле
crate_body.mass = 2.0
scene.add_game_object(crate)

# Прыгучий мяч: каждый удар сохраняет 60% скорости, и через несколько прыжков он успокаивается
ball = create_square(400, 100, size=20, name="Ball", add_rigidbody=True)
ball_body = ball.get_component(Rigidbody2D)
ball_body.bounce = 0.6
scene.add_game_object(ball)

# Кинематическая платформа: двигается по скорости, проходит сквозь всё, игнорирует гравитацию
platform = create_rectangle(300, 250, 120, 16, name="Platform", add_rigidbody=True)
platform_body = platform.get_component(Rigidbody2D)
platform_body.is_kinematic = True
platform_body.velocity.x = 60
scene.add_game_object(platform)

for _ in range(60):                        # одна секунда падения
    scene.tick(1 / 60)
assert crate_body.is_grounded              # стоит на полу

crate_body.add_impulse(400, 0)             # толчок вправо: velocity += 400 / mass
for _ in range(120):
    scene.tick(1 / 60)
print(crate_body.velocity.x)               # 0.0 — трение остановило ящик

crate_body.teleport(100, 100)              # вернуть его наверх без «размазывания» по кадрам

# Выход из портала: тело вылетает со скоростью, с которой прилетело (1800 px/s), в направлении вправо.
# Даже если предел задан (например, terminal_velocity=1000), он ограничивает только то, что может добавить гравитация, так что это тело он никогда не замедляет.
crate_body.velocity.y = 1800
crate_body.teleport(100, 100, keep_velocity=True)   # обычный teleport() остановил бы тело намертво
crate_body.redirect_velocity(1, 0)                  # та же скорость, новое направление
print(crate_body.speed)                             # 1800.0
```

### 5.2. Коллайдеры (BoxCollider2D, CircleCollider2D)

**Описание:** Коллайдер задаёт форму объекта для столкновений (твёрдый) или для обнаружения касаний (триггер, `is_trigger=True`). `BoxCollider2D` — прямоугольник, единственная форма, которую `Rigidbody2D` разрешает как твёрдую. `CircleCollider2D` выполняет точную проверку расстояния до центра (круг—круг и круг—прямоугольник), но работает **только для пересечений и триггеров** — твёрдого круга нет. Геометрия хранится в виде точных чисел с плавающей точкой (`bounds`); `rect` — просто округлённый `pygame.Rect` для отрисовки и старого кода. **Размер:** лучше всего передавать `size=(w, h)` явно; иначе он один раз измеряется по спрайту в `start()` и затем *фиксируется* — смена кадра анимации не меняет размер хитбокса (для намеренного изменения размера, например при приседании, используйте `set_size`). **Якорь** (`anchor`) использует те же девять имён, что и `SpriteRenderer`: задайте спрайту и его коллайдеру одинаковый якорь, чтобы хитбокс совпадал с картинкой (см. [9.1](#91-spriterenderer-и-якоря-спрайтов)).

**События.** Твёрдый объект, касающийся твёрдого, порождает события столкновения, если хотя бы у одной стороны есть `Rigidbody2D`; всё, что пересекает триггер, порождает события триггера. Получать их можно двумя способами, оба работают одновременно и для любой из сторон:

- **Методы-обработчики** на любом компоненте любого из двух объектов: `on_collision_enter/stay/exit(self, collision)` и `on_trigger_enter/stay/exit(self, other)`;
- **Списки колбэков** на коллайдере: `collider.on_trigger_enter.append(fn)` с сигнатурой `fn(my_collider, other_collider)`.

**Быстрые тела и триггеры.** Твёрдые объекты проверяются вдоль пути (swept), поэтому тело никогда не пролетает сквозь стену. Триггеры получают такую же защиту: тело, которое за один шаг смещается дальше, чем на половину своей меньшей стороны, проверяется на триггеры по всему пройденному пути, поэтому тонкий вход в портал или линию контрольной точки нельзя проскочить на любой скорости. `enter` срабатывает на шаге, когда тело пересекло триггер, а `exit` — на следующем. Проверяется путь только движущегося тела — триггер, который сам очень быстро движется, по-прежнему проверяется в конечной позиции.

Если объект деактивирован, удалён или уничтожен во время касания другого, другая сторона получает `exit`. Исключения внутри обработчиков пишутся в лог и никогда не пробрасываются; уничтожать объекты изнутри обработчика безопасно.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `BoxCollider2D(...)` | `size: tuple = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int or str = None, mask: int or a list of layers = None` | Прямоугольник. `size=None` измеряет размер по спрайту (один раз, в `start()`); `offset_x/offset_y` сдвигают хитбокс; `layer=None` использует слой объекта; `mask=None` сталкивается со всеми слоями. |
| `CircleCollider2D(...)` | `radius: float = None, offset_x: float = 0, offset_y: float = 0, anchor: str = "topleft", is_trigger: bool = False, layer: int or str = None, mask: int or a list of layers = None` | Круг (только пересечения и триггеры). `radius=None` — половина большей стороны спрайта. Якорь применяется к квадрату `(диаметр, диаметр)`. |
| `is_trigger` | `bool` | `True` делает его датчиком без физической реакции: `collider.is_trigger = True`. |
| `layer`, `mask` | `int`, `int` | Слой и маска столкновений (см. [5.3](#53-слои-и-маски-столкновений)). |
| `bounds` | `tuple` (свойство) | Точные мировые `(left, top, right, bottom)`. |
| `rect` | `pygame.Rect` (свойство) | Округлённый ограничивающий прямоугольник — для отрисовки и отладки, но никогда не для физики. |
| `is_static` | `bool` (свойство) | Находится ли коллайдер на статическом объекте. |
| `overlaps(other)` | `other: Collider2D` | Точная проверка пересечения форм: `zone.overlaps(hero_collider)`. |
| `can_collide_with(other)` | `other: Collider2D` | Взаимодействует ли пара по правилам слоёв/масок (маска каждого должна разрешать слой другого). |
| `contact_normal(other)` | `other: Collider2D` | Единичная нормаль `(nx, ny)` от `other` к этому коллайдеру. |
| `overlapping_colliders` | `frozenset` (свойство) | С чем этот коллайдер соприкасался на последнем физическом шаге. |
| `on_trigger_enter/stay/exit` | `a list of fn(collider, other)` | Колбэки триггера: вход / нахождение (каждый шаг) / выход. |
| `on_collision_enter/stay/exit` | `a list of fn(collider, other)` | Колбэки столкновения (нужен `Rigidbody2D` хотя бы с одной стороны). |
| `Collision2D` | `collider, other, normal, game_object` | Аргумент, передаваемый в `on_collision_*(collision)`: `collision.other` — другой коллайдер, `collision.game_object` — его объект, а `collision.normal` — нормаль контакта от другого объекта к этому (`(0, −1)` означает «меня поддержали снизу»). |
| `BoxCollider2D.size` / `set_size(width, height)` | `width: float, height: float` | Текущий размер / намеренное изменение размера, фиксирующее новый размер. |
| `BoxCollider2D.snap_left_to(x)`, `snap_right_to(x)`, `snap_top_to(y)`, `snap_bottom_to(y)` | `x: float` / `y: float` | Сдвигает `Transform` так, чтобы соответствующий край хитбокса оказался ровно на этой мировой координате. |
| `CircleCollider2D.radius` / `set_radius(radius)` | `radius: float` | Радиус (только чтение) / намеренное изменение размера. `center_x`, `center_y` дают мировой центр круга. |
| `scene.physics.query_point(x, y, mask, include_triggers)` | `x: float, y: float, mask: int = CollisionLayers.ALL, include_triggers: bool = True` | Коллайдеры в точке: `scene.physics.query_point(210, 360)`. |
| `scene.physics.query_rect(rect, ...)` / `query_bounds(left, top, right, bottom, ...)` | `rect: pygame.Rect` / `left, top, right, bottom: float` (плюс те же `mask`, `include_triggers`) | Коллайдеры, пересекающие область. |

#### Пример использования

```python
from engine.components.circle_collider2d import CircleCollider2D
from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.primitives import create_rectangle, create_square


class DamageZone(Component):
    """Handler methods: on any component of either of the two objects."""

    def on_trigger_enter(self, other):                # other — коллайдер, который вошёл
        print(f"{other.game_object.name} entered the zone")

    def on_trigger_exit(self, other):
        print(f"{other.game_object.name} left the zone")


class LandingLogger(Component):
    def on_collision_enter(self, collision):          # collision — объект Collision2D
        if collision.normal.y < -0.5:                 # поддержали снизу
            print("landed on", collision.game_object.name)


scene = Scene("colliders")
scene.add_game_object(create_rectangle(0, 400, 800, 40, name="Floor", is_static=True))

zone = GameObject(200, 340, name="Zone", is_static=True)
zone_collider = zone.add_component(BoxCollider2D(size=(120, 60), is_trigger=True))
zone.add_component(DamageZone())
# Другой способ: список колбэков с сигнатурой (my_collider, other_collider)
zone_collider.on_trigger_enter.append(lambda me, other: print("callback list:", other.game_object.name))
scene.add_game_object(zone)

hero = create_square(240, 100, size=40, name="Hero", add_rigidbody=True)
hero.add_component(LandingLogger())
scene.add_game_object(hero)

sensor = GameObject(600, 300, name="Sensor", is_static=True)
sensor.add_component(CircleCollider2D(radius=80, is_trigger=True))   # круглая зона обнаружения
scene.add_game_object(sensor)

for _ in range(120):                                  # герой падает сквозь зону и приземляется
    scene.tick(1 / 60)

hero_box = hero.get_component(BoxCollider2D)
print(hero_box.bounds)                                # точные границы (240, 360, 280, 400)
print(hero_box.overlaps(zone_collider))               # True: герой стоит в зоне
print([c.game_object.name for c in scene.physics.query_point(250, 380)])   # Zone и Hero
```

### 5.3. Слои и маски столкновений

**Описание:** У каждого коллайдера есть **слой** (`layer`, число 0–31 или имя — «кто я») и **маска** (`mask`, набор слоёв — «с чем я сталкиваюсь»). Два коллайдера взаимодействуют, только если маска **каждого** разрешает слой другого. Неподходящие пары отбрасываются ещё до точной проверки пересечения, поэтому разделение по слоям — самый дешёвый способ ускорить физику. По умолчанию каждый объект находится на слое 0 (`"default"`) и сталкивается со всем. Коллайдер наследует `layer` от своего объекта, если у него нет собственного. Слоям даются имена через `CollisionLayers.register`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `CollisionLayers.register(name, index)` | `name: str, index: int` | Даёт слою имя (0–31; регистр не важен): `CollisionLayers.register("enemy", 2)`. |
| `CollisionLayers.index(layer)` | `layer: int or str` | Проверяет и приводит имя или число к индексу слоя; неизвестное имя вызывает `ValueError`. |
| `CollisionLayers.mask(*layers)` | `*layers: int or str` | Маска из указанных слоёв: `CollisionLayers.mask("ground", "enemy")`. |
| `CollisionLayers.name_of(index)` | `index: int` | Имя слоя (или число в виде строки, если имени нет). |
| `CollisionLayers.reset()` | — | Сбрасывает реестр имён (остаётся только `"default"`). |
| `CollisionLayers.ALL` / `NONE` / `MAX_LAYERS` | `int` | Маска «все слои» (`0xFFFFFFFF`) / «ни одного слоя» / число слоёв (32). |
| `GameObject.layer` | `int or str` | Слой объекта: `go.layer = "player"`. |
| `Collider2D.layer` / `Collider2D.mask` | `int` / `int` | Слой и маска конкретного коллайдера (`mask` можно задать и в конструкторе). |
| `Collider2D.can_collide_with(other)` | `other: Collider2D` | Проверяет пару по правилам слоёв и масок. |
| `mask` в вызовах `scene.physics.query_*` | `int` | Ограничивает запрос указанными слоями. |

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

# Пуля игрока (триггер): попадает во врагов и землю, игнорирует игрока и другие пули
bullet = GameObject(140, 110, name="Bullet", layer="bullet")
bullet_box = bullet.add_component(BoxCollider2D(
    size=(8, 8), is_trigger=True, mask=CollisionLayers.mask("enemy", "ground")))

enemy = GameObject(300, 100, name="Enemy", layer="enemy")
enemy_box = enemy.add_component(BoxCollider2D(size=(32, 32)))

for go in (player, bullet, enemy):
    scene.add_game_object(go)

print(player_box.can_collide_with(bullet_box))   # False — эта пара не взаимодействует
print(bullet_box.can_collide_with(enemy_box))    # True — «bullet» видит «enemy», а маска «enemy» по умолчанию видит всех

enemy.layer = "ground"                           # слой можно менять на лету
print(CollisionLayers.name_of(enemy.layer))      # ground
```

---

## 6. Система ввода

**Описание:** `Input` — статический сервис, доступный из любого компонента без ссылки на `Engine`. Клавиши задаются строками (`"space"`, `"w"`, `"left_shift"`, `"mouse_left"`), константами `Key.*` или «сырыми» кодами `pygame.K_*`; опечатка в названии клавиши сразу вызывает `ValueError`, а не молча ничего не делает. Система событийная: `Engine` передаёт ей каждое событие pygame, поэтому нажатие короче одного кадра никогда не теряется, а потеря фокуса окна отпускает все удерживаемые клавиши. **Внутри `fixed_update` фронты «нажато»/«отпущено» читаются из отдельного набора, который очищается после каждого физического шага** — поэтому каждое нажатие видит ровно один физический шаг, независимо от того, выполняет кадр два шага или ни одного. Для обычной игровой логики читать ввод в `update()` по-прежнему предпочтительнее. Геймпады включаются по желанию и описаны в [6.1](#61-ввод-с-геймпада); готовый контроллер персонажа, который читает и клавиатуру, и геймпад, описан в [6.2](#62-playercontroller).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Input.is_key_down(key)` | `key: str, int, or Key` | `True`, пока клавиша удерживается: `Input.is_key_down("d")`. |
| `Input.is_key_pressed(key)` | `key: str, int, or Key` | `True` только в кадре (или физическом шаге), когда клавишу нажали. |
| `Input.is_key_up(key)` | `key: str, int, or Key` | `True` только в кадре, когда клавишу отпустили. |
| `Input.get_axis(negative, positive)` | `negative: str, positive: str` | `-1`, `0` или `1` по паре клавиш: `Input.get_axis("a", "d")`. |
| `Input.mouse_position()` | — | `(x, y)` в пикселях экрана. |
| `Input.mouse_world_position()` | — | Позиция курсора в мировых координатах через активную камеру сцены (или `None`, если сцены нет). |
| `Input.mouse_delta()` | — | Насколько сдвинулась мышь с прошлого кадра `(dx, dy)`. |
| `Input.mouse_scroll()` / `mouse_scroll_x()` | — | Прокрутка колеса в этом кадре (вертикальная / горизонтальная). |
| `Input.is_mouse_pressed(button=0)` / `is_mouse_just_pressed(button)` / `is_mouse_just_released(button)` | `button: int` (0 — левая, 1 — средняя, 2 — правая) | Устаревший числовой API кнопок мыши. |
| `Input.is_pressed(key)` / `is_just_pressed(key)` / `is_just_released(key)` | `key: str, int, or Key` | Устаревшие имена: `is_pressed` = `is_key_down`, `is_just_pressed` = `is_key_pressed`, `is_just_released` = `is_key_up`. |
| `Key.*` | — | Именованные константы: `Key.W`, `Key.SPACE`, `Key.LEFT`, `Key.F1` и так далее — то же, что и строки, но с автодополнением в IDE. |
| `Input.inject_key(key, down=True)` / `inject_mouse_position(x, y)` / `inject_scroll(y, x=0)` | — | Имитирует ввод без настоящих событий pygame — удобно для тестов и ботов. |

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
        x = Input.get_axis("a", "d")               # -1 / 0 / 1 по строковым названиям клавиш
        y = Input.get_axis(Key.W, Key.S)            # то же самое, но через Key.*
        self.body.velocity.x = x * self.speed
        self.body.velocity.y = y * self.speed

        if Input.is_key_pressed("space"):           # только в кадре, когда клавишу нажали
            print("jump!")

        if Input.is_mouse_just_pressed(0):           # левая кнопка мыши
            target = Input.mouse_world_position()
            print("clicked in world space:", target)
```

### 6.1. Ввод с геймпада

**Описание:** Поддержка геймпадов **включается по желанию**: пока вы не вызвали `Input.enable_gamepad()` (или не передали `gamepad=True` в `Engine`), ничего не опрашивается, каждый запрос к геймпаду возвращает `False` / `0.0`, а игра, которой геймпады не нужны, ничего за них не платит. Геймпады проходят через слой игровых контроллеров SDL, поэтому каждый поддерживаемый геймпад сообщает одни и те же названия кнопок и осей, какой бы ни была его настоящая раскладка. Геймпады можно **подключать «на горячую»** в любой момент, и каждый получает стабильный **слот** (0 — первый геймпад): если отключить геймпад 0, геймпад 1 так и останется геймпадом 1, поэтому в локальной игре на нескольких игроков игроки никогда не меняются местами. Кнопки подчиняются тем же правилам, что и клавиши: `is_gamepad_pressed` / `is_gamepad_up` — покадровые фронты, а **внутри `fixed_update` они читают отдельный набор фронтов, очищаемый после каждого физического шага**, поэтому каждое нажатие видит ровно один шаг. У стиков есть **мёртвая зона** (доля хода, игнорируемая вокруг центра, чтобы скрыть дрейф); оставшийся диапазон масштабируется так, что полный отклонённый стик по-прежнему читается ровно как 1. Отключение геймпада отпускает всё, что он удерживал, — как и потеря фокуса окна.

**Названия.** Кнопки: `a`, `b`, `x`, `y`, `back`, `guide`, `start`, `left_stick`, `right_stick` (нажатия на стики), `left_shoulder`, `right_shoulder`, `dpad_up`, `dpad_down`, `dpad_left`, `dpad_right`. Оси: `left_x`, `left_y`, `right_x`, `right_y`, `left_trigger`, `right_trigger`. Названия следуют раскладке SDL в стиле Xbox (`a` — кнопка Cross на геймпаде PlayStation); на геймпадах Nintendo SDL может следовать подписям на кнопках, а не их положению. Любое другое название вызывает `ValueError` со списком допустимых, так что опечатка никогда не остаётся незамеченной.

> **Ограничения.** Геймпады, для которых у SDL нет карты контроллера, игнорируются. Вибрация, гироскоп и тачпады не поддерживаются. Функция проверена на имитированных и синтетических событиях SDL, а не на физическом контроллере — проверьте её на своём геймпаде.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Input.enable_gamepad(enabled=True, deadzone=0.2)` | `enabled: bool = True, deadzone: float = 0.2` | Включает (или выключает) ввод с геймпада. `deadzone` (0–0.95) — доля хода стика, игнорируемая вокруг центра. Выключение отпускает все удерживаемые кнопки геймпада. `Engine(..., gamepad=True, gamepad_deadzone=0.2)` делает то же самое. |
| `Input.is_gamepad_enabled()` | — | Включён ли сейчас ввод с геймпада. |
| `Input.gamepad_count()` | — | Сколько геймпадов подключено прямо сейчас (`0`, пока геймпады выключены). |
| `Input.gamepad_name(slot=0)` | `slot: int = 0` | Название геймпада так, как его сообщает система, или `None` для пустого слота. |
| `Input.is_gamepad_down(button, slot=0)` | `button: str, slot: int = 0` | `True`, пока кнопка удерживается: `Input.is_gamepad_down("right_shoulder")`. |
| `Input.is_gamepad_pressed(button, slot=0)` | `button: str, slot: int = 0` | `True` только в кадре (или физическом шаге), когда кнопку нажали: `Input.is_gamepad_pressed("a")`. |
| `Input.is_gamepad_up(button, slot=0)` | `button: str, slot: int = 0` | `True` только в кадре, когда кнопку отпустили. |
| `Input.gamepad_axis(axis, slot=0)` | `axis: str, slot: int = 0` | Одна ось от `-1` до `1` с вычтенной мёртвой зоной; триггеры читаются от `0` до `1`. `Input.gamepad_axis("left_x")`. Возвращает `0.0`, когда геймпады выключены или слот пуст. |
| `Input.gamepad_stick(side="left", slot=0)` | `side: str = "left" or "right", slot: int = 0` | `(x, y)` стика с **радиальной** мёртвой зоной (диагонали не обрезаются), длиной не больше 1. Вверх — **отрицательный** `y`, как в экранных координатах, поэтому `body.velocity.y = y * speed` работает напрямую. |
| `GAMEPAD_BUTTONS` / `GAMEPAD_AXES` | `dict` | Допустимые названия (в `engine.input.input_manager`). |
| `Input.instance().inject_gamepad_button(button, down=True, slot=0)` | `button: str, down: bool = True, slot: int = 0` | Имитирует нажатие или отпускание — удобно для тестов и ботов. Также делает так, что `slot` считается подключённым. |
| `Input.instance().inject_gamepad_axis(axis, value, slot=0)` | `axis: str, value: float, slot: int = 0` | Имитирует положение оси (`-1`..`1`). |

#### Пример использования

```python
from engine.components.component import Component
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.input.input_manager import Input
from engine.primitives import create_square


class PadMover(Component):
    def start(self):
        self.body = self.game_object.get_component(Rigidbody2D)

    def update(self, delta_time):
        x, y = Input.gamepad_stick("left")               # аналоговое значение, мёртвая зона уже применена
        self.body.velocity.x = x * 220
        self.body.velocity.y = y * 220
        if Input.is_gamepad_pressed("a"):                # только в кадре, когда A нажали
            print("A pressed")
        if Input.gamepad_axis("right_trigger") > 0.5:    # триггеры читаются в диапазоне 0..1
            print("firing")


Input.enable_gamepad(deadzone=0.2)                       # по умолчанию выключено; Engine(..., gamepad=True) делает то же самое

scene = Scene("pad")
hero = create_square(100, 100, size=32, name="Hero", add_rigidbody=True)
hero.get_component(Rigidbody2D).use_gravity = False
hero.add_component(PadMover())
scene.add_game_object(hero)

# Настоящим геймпадам больше кода не нужно. Для тестов и ботов имитируем один:
pad = Input.instance()
pad.inject_gamepad_axis("left_x", 0.6)                   # стик отклонён на 60% вправо
pad.inject_gamepad_button("a")
scene.tick(1 / 60)
print(round(hero.get_component(Rigidbody2D).velocity.x, 1))   # 110.0: (0.6 - 0.2) / (1 - 0.2) = половина полной скорости
print(Input.gamepad_count(), Input.is_gamepad_down("a"))      # 1 True
```

### 6.2. PlayerController

**Описание:** Готовый компонент-контроллер персонажа с двумя режимами. `"top_down"` — движение в 4/8 направлениях без гравитации (диагонали нормализуются, поэтому они не быстрее прямых). `"platformer"` — бег по горизонтали плюс прыжок под действием гравитации через `Rigidbody2D`, с **coyote time** (прыжок ещё разрешён в течение короткого времени после схода с уступа), **буферизацией прыжка** (нажатие прямо перед приземлением не пропадает) и необязательным **мультипрыжком**. Он читает клавиатуру через `Input`/`Key` и — когда геймпады включены ([6.1](#61-ввод-с-геймпада)) — ещё и крестовину, кнопку прыжка и **аналоговый левый стик** (половинный наклон — ходьба вполсилы). Использование геймпада настраивается для каждого персонажа: `use_gamepad=False` отключает его, а `gamepad_slot` выбирает, какой геймпад персонаж слушает (по одному геймпаду на игрока).

**Инерция.** В режиме платформера, пока тело движется медленнее `speed`, контроллер напрямую задаёт скорость бега, как это делают классические платформерные контроллеры. Тело, которое *уже быстрее* — вылетевшее из портала, подброшенное взрывом, получившее `add_impulse`, — сохраняет эту лишнюю скорость, а не теряет её в следующем кадре. Избыток сверх `speed` гасится со скоростью `momentum_ground_decel` px/s² на земле и `momentum_air_decel` в воздухе (`0` сохраняет его до приземления или столкновения), а нажатие против движения в воздухе тормозит его с ускорением `air_steer_accel` px/s². Установите `momentum_ground_decel` очень большим, чтобы вернуть прежнее ощущение «всегда сразу переходить на скорость бега».

> **Ограничения.** Режиму платформера нужен `Rigidbody2D` на том же объекте (без него контроллер двигается только по горизонтали и пишет предупреждение в лог). Без `Rigidbody2D` режим top-down двигает `Transform` напрямую и игнорирует столкновения. Неизвестный `movement_type` не применяет никакого движения и выдаёт `EngineWarning`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `PlayerController(...)` | `speed: float = 200, jump_force: float = 350, movement_type: str = "top_down", keybinds: dict = None, anim_map: dict = None, coyote_time: float = 0.1, jump_buffer_time: float = 0.1, max_jumps: int = 1, momentum_ground_decel: float = 2500, momentum_air_decel: float = 0, air_steer_accel: float = 1500, use_gamepad: bool = True, gamepad_slot: int = 0, gamepad_binds: dict = None` | `speed` — скорость бега (px/s), а `jump_force` — скорость прыжка вверх (px/s; высота прыжка равна `jump_force² / (2 · gravity)`); `movement_type` — `"top_down"` или `"platformer"`; `coyote_time` / `jump_buffer_time` задаются в секундах; `max_jumps=2` — двойной прыжок. `keybinds` / `gamepad_binds` переназначают управление (см. ниже); `anim_map` сопоставляет логические названия анимаций названиям в вашем `Animator`. Параметры `momentum_*` и `air_steer_accel` описаны выше. Каждый параметр также является атрибутом, который можно менять во время работы. |
| `keybinds` | `dict[str, list]` | Действие → список клавиш для действий `left`, `right`, `up`, `down`, `jump`. По умолчанию (`DEFAULT_KEYBINDS`): `A`/`Left`, `D`/`Right`, `W`/`Up`, `S`/`Down`, `Space`. Пример: `PlayerController(keybinds={"left": ["j"], "right": ["l"], "up": [], "down": [], "jump": ["space", "k"]})`. |
| `gamepad_binds` | `dict[str, list]` | Те же действия, сопоставленные названиям кнопок геймпада. По умолчанию (`DEFAULT_GAMEPAD_BINDS`): крестовина для четырёх направлений и `a` для `jump`. Левый стик всегда тоже управляет движением, а побеждает больший из значений стика и крестовины/клавиш. |
| `anim_map` | `dict[str, str]` | Логическое название → название анимации. Логические названия: `idle`, `idle_left`, `idle_right`, `idle_up`, `idle_down`, `walk_up`, `walk_down`, `walk_left`, `walk_right`, `jump`, `jump_left`, `jump_right` (`DEFAULT_ANIM_MAP` сопоставляет каждому такое же название). Используется, только если у объекта есть `Animator`. |
| `jumps_remaining` | `int` (свойство) | Сколько прыжков осталось до приземления (`max_jumps` минус использованные). |
| `is_grounded` | `bool` | Стоит ли персонаж на чём-то (режим платформера). |
| `facing_x`, `facing_y` | `int` | Последнее направление взгляда по горизонтали / вертикали, `1` или `-1` (по нему выбираются анимации покоя и прыжка). |
| События `game_object.events` | `"jumped"`, `"landed"`, `"jumps_changed"` | События сущности, посылаются только если на них кто-то подписан: `jumped(jumps_used, remaining)`, `landed()`, `jumps_changed(remaining, maximum)` — удобно для HUD двойного прыжка: `player.events.subscribe("jumps_changed", lambda remaining, maximum: ...)`. |
| `_on_jump()` | — | Пустой хук, вызываемый после каждого прыжка; переопределите его в подклассе для звука прыжка или частиц пыли. |

#### Пример использования

```python
from engine.components.player_controller import PlayerController
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.scene import Scene
from engine.input.input_manager import Input
from engine.primitives import create_rectangle, create_square

scene = Scene("platformer")
scene.add_game_object(create_rectangle(0, 300, 800, 40, name="Floor", is_static=True))

hero = create_square(100, 250, size=32, name="Hero", add_rigidbody=True)
hero.add_component(PlayerController(speed=240, jump_force=460, movement_type="platformer", max_jumps=2))
hero.events.subscribe("jumps_changed", lambda remaining, maximum: print(f"jumps left: {remaining}/{maximum}"))
scene.add_game_object(hero)
body = hero.get_component(Rigidbody2D)

keys = Input.instance()


def frame(press=(), release=()):
    keys.begin_frame()                                 # настоящий Engine делает это каждый кадр: новый кадр, затем события, затем update
    for key in press:
        keys.inject_key(key)                           # имитируем нажатие клавиши (настоящей клавиатуре код не нужен)
    for key in release:
        keys.inject_key(key, down=False)
    scene.tick(1 / 60)


for _ in range(30):                                    # приземляемся на пол
    frame()

frame(press=["d"])                                     # удерживаем "D"
print(body.velocity.x)                                 # 240: скорость бега

frame(press=["space"])                                 # нажимаем Space
print(body.velocity.y)                                 # -460: прыжок (а "jumps left: 1/2" вывело событие)

body.velocity.x = 900                                  # отброшен вбок в воздухе (выход из портала, взрыв)
frame(release=["d", "space"])
print(body.velocity.x)                                 # 900.0 — сохранилось в воздухе, а не сброшено до скорости бега 240
```

---

## 7. Система пользовательского интерфейса (UI)

### 7.1. Canvas и экранный UI

**Описание:** Элементы UI (`UIText`, `UIButton`, `UIPanel`, `UIHealthBar`) — это компоненты на `GameObject`, как и всё остальное. По умолчанию они рисуются в **экранных координатах** — после мира, поверх него, без смещения камеры, поэтому HUD никогда не «уплывает», пока вид прокручивается. `Canvas` — необязательный корневой элемент: сам он ничего не рисует, но `canvas.visible = False` скрывает все элементы UI, у которых он является родителем. Элемент также можно сделать **мировым** (`world_space=True`) — тогда он рисуется вместе с миром через камеру (например, полоска здоровья над врагом): сделайте объект UI-элемента потомком того объекта, за которым он должен следовать.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `UIElement(...)` | `width: int = 100, height: int = 30, visible: bool = True, draw_order: int = 0, anchor: str = None, pivot: str = None, world_space: bool = False` | Базовый класс для каждого элемента UI; параметры якорей см. в [7.3](#73-якоря-и-точки-опоры-ui). |
| `Canvas(...)` | `sort_order: int = 0, visible: bool = True` | Корневой контейнерный элемент UI; сам он не рисуется. `visible = False` скрывает сразу всех потомков. |
| `visible` | `bool` | Показан ли элемент. |
| `is_visible` | `bool` (свойство) | Показан ли элемент **с учётом** видимости каждого UI-предка. |
| `draw_order` | `int` | Порядок отрисовки среди экранных элементов (меньшее значение рисуется раньше/позади); при равенстве сохраняется порядок добавления. |
| `world_space` | `bool` | `True` рисует элемент в мире через камеру, а не в экранных координатах. |
| `rect` | `pygame.Rect` (свойство) | Текущий прямоугольник элемента в экранных координатах (для мирового элемента — с поправкой на камеру). |
| `contains_point(point_x, point_y)` | `point_x: float, point_y: float` | Попадает ли точка в прямоугольник элемента: `panel.contains_point(*Input.mouse_position())`. |
| `draw(screen)` | `screen: pygame.Surface` | Хук отрисовки — конкретные виджеты переопределяют его. |

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
        self.canvas = hud.add_component(Canvas())      # один общий переключатель видимости
        self.add_game_object(hud)

        label = GameObject(12, 12, name="ScoreLabel", parent=hud)
        self.score_text = label.add_component(UIText("Score: 0", anchor="TopLeft"))

        bar = GameObject(12, 42, name="HealthBar", parent=hud)
        bar.add_component(UIHealthBar(220, 20, max_value=100, anchor="TopLeft"))

    def update(self, delta_time):
        super().update(delta_time)
        from engine.input.input_manager import Input
        if Input.is_key_pressed("h"):
            self.canvas.visible = not self.canvas.visible   # скрыть/показать весь HUD сразу
```

### 7.2. Элементы UI (UIText, UIButton, UIPanel, UIHealthBar)

**Описание:** Четыре готовых виджета. `UIText` рисует строку (её отрисованная поверхность кэшируется, поэтому перерисовка неизменённого текста не рендерит его заново). `UIButton` — прямоугольник с подписью и списком колбэков `on_click`, реагирующий на наведение и клик левой кнопкой. `UIPanel` — простой прямоугольный фон, часто используется как подложка для других элементов. `UIHealthBar` — заполняемая полоса (здоровье, выносливость, индикатор прогресса) с необязательным сглаживанием и «следом урона» (`trail_color`), который догоняет текущее значение. Цвета и шрифт по умолчанию берутся из `UIStyle.default()`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `UIText(...)` | `text: str = "", style: UIStyle = None, align: str = "left", width: int = None, height: int = None, **kwargs` | `**kwargs` — общие параметры `UIElement` (`anchor`, `pivot`, `world_space` и т. д.). `align` — `"left"`, `"center"` или `"right"`. Ширина/высота по умолчанию равны измеренному размеру текста. |
| `UIText.text` / `set_text(text)` | `text: str` | Текущий текст / его изменение: `label.set_text("Done")`. |
| `UIButton(...)` | `text: str = "Button", width: int = 140, height: int = 40, style: UIStyle = None, **kwargs` | Кнопка с подписью. |
| `UIButton.on_click` | `a list of fn(button)` | Колбэки клика: `button.on_click.append(lambda b: print("clicked"))`. |
| `UIButton.is_hovered` / `is_pressed` | `bool` | Находится ли над ней мышь / нажата ли она сейчас. |
| `UIPanel(...)` | `width: int = 200, height: int = 100, style: UIStyle = None, **kwargs` | Прямоугольная подложка. |
| `UIHealthBar(...)` | `width: int = 200, height: int = 20, max_value: float = 100.0, value: float = None, fill_color: tuple = (80,200,90), low_color: tuple = (215,65,65), low_threshold: float = 0.3, background_color: tuple = (35,35,40), border_color: tuple = (12,12,15), border_width: int = 2, trail_color: tuple = None, smooth_speed: float = 0.0, show_text: bool = False, text_color: tuple = (245,245,245), font_size: int = None, **kwargs` | `background_color`, `border_color` и `border_width` оформляют рамку; `low_color` включается при `ratio <= low_threshold`; `smooth_speed > 0` плавно ведёт заливку (доля в секунду) вместо мгновенного скачка; `show_text` рисует `"hp/max"` поверх полосы цветом `text_color` (`font_size=None` берёт 80% высоты полосы, но не меньше 10). |
| `UIHealthBar.value` / `set_value(v)` | `float` | Текущее значение. |
| `UIHealthBar.set_max_value(max_value, keep_ratio=False)` | `max_value: float, keep_ratio: bool` | Меняет максимум; `keep_ratio=True` сохраняет долю заполнения. |
| `UIHealthBar.bind(getter)` | `getter: a callable with no arguments` | Читает значение из функции каждый кадр: `bar.bind(lambda: player_health.hp)`. |
| `UIHealthBar.ratio` / `displayed_ratio` | `float` (свойства) | Истинная доля заполнения / та, что реально рисуется (с учётом сглаживания). |
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
        title.add_component(UIText("Paused", anchor="Center", align="center"))

        health = GameObject(-140, -10, name="Health", parent=hud)
        bar = health.add_component(UIHealthBar(280, 24, max_value=100, value=65,
                                               anchor="Center", show_text=True,
                                               smooth_speed=2.0, trail_color=(220, 90, 90)))

        resume = GameObject(0, 40, name="Resume", parent=hud)
        button = resume.add_component(UIButton("Resume", 180, 44, anchor="Center"))
        button.on_click.append(lambda b: print("resuming the game"))

        bar.value = 40    # полоса плавно «догонит» новое значение благодаря smooth_speed
```

### 7.3. Якоря и точки опоры UI

**Описание:** Девять именованных якорей — `TopLeft`, `TopCenter`, `TopRight`, `MiddleLeft`, `Center`, `MiddleRight`, `BottomLeft`, `BottomCenter`, `BottomRight` (регистр и подчёркивания не важны: `"top_left"`, `"topleft"`, `"MidTop"` — всё понимается). Без якоря (`anchor=None`, по умолчанию) позиция `GameObject` — это левый верхний угол элемента в экранных пикселях; если у него родитель — UI-элемент, позиция отсчитывается от прямоугольника этого родителя. С якорем позиция объекта становится **смещением от точки привязки** опорного прямоугольника: ближайшего UI-предка или экрана, если его нет. `pivot` решает, какая точка *самого элемента* ложится на эту точку привязки (по умолчанию совпадает с якорем), поэтому `anchor="BottomRight"` со смещением `(-10, -10)` даёт отступ в 10 пикселей от угла при любом размере окна.


**Расположение в ряд.** Для колонки или ряда элементов (меню, список характеристик) `UILayoutGroup` проще, чем вычислять смещения вручную: прикрепите его к собственному `GameObject`, вызовите `add_item()` для каждого UI-объекта, который нужно выстроить, и каждый кадр он будет выравнивать их, начиная с собственной мировой позиции, с промежутком `spacing` пикселей. Это вспомогательный инструмент позиционирования, а не полноценный контейнер раскладки: он ничего не масштабирует, а элементы с якорями лучше размещать через `anchor=`.
#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `UILayoutGroup(...)` | `direction: str = "vertical", spacing: float = 8` | Выстраивает свои элементы в `"vertical"` колонку или `"horizontal"` ряд; неизвестное направление заменяется на вертикальное с предупреждением. Элементы сохраняют свои размеры; следующий размещается после высоты (или ширины) предыдущего плюс `spacing`. |
| `UILayoutGroup.add_item(game_object)` / `remove_item(game_object)` | `game_object: GameObject` | Добавляет объект в колонку (возвращается для цепочки вызовов) / убирает его. Неактивные объекты и объекты без `UIElement` пропускаются. |
| `UIElement(anchor=..., pivot=...)` | `anchor: str = None, pivot: str = None` | `anchor` — к какой точке опорного прямоугольника прикреплён элемент; `pivot` — какая точка элемента ложится на неё (по умолчанию равна `anchor`). |
| `UIElement.anchor` / `.pivot` | `str or None` | Можно менять после создания: `element.anchor = "BottomRight"`. |
| `normalize_anchor(name)` | `name: str` | Приводит любое написание к каноническому имени; неизвестное вызывает `ValueError`. |
| `VALID_ANCHORS` | `set[str]` | Девять канонических имён в нижнем регистре без пробелов: `{"topleft", "midtop", ...}`. |
| `anchor_to_topleft_offset(anchor, width, height)` | `anchor: str, width: float, height: float` | `(dx, dy)` от точки привязки до левого верхнего угла прямоугольника такого размера — та же математика, что используют `SpriteRenderer` и коллайдеры ([9.1](#91-spriterenderer-и-якоря-спрайтов)). |

#### Пример использования

```python
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.ui.ui_button import UIButton
from engine.ui.ui_layout import UILayoutGroup
from engine.ui.ui_text import UIText

scene = Scene("anchors")

# Прикреплены к углам экрана — независимо от размера окна
top_left = GameObject(10, 10, name="TopLeft")
top_left.add_component(UIText("Top-left", anchor="TopLeft"))
scene.add_game_object(top_left)

bottom_right = GameObject(-10, -10, name="BottomRight")   # отрицательные значения = отступ от угла
bottom_right.add_component(UIText("Bottom-right", anchor="BottomRight", pivot="BottomRight"))
scene.add_game_object(bottom_right)

centered = GameObject(0, 0, name="CenterButton")
centered.add_component(UIButton("Centered", 160, 40, anchor="Center"))   # pivot по умолчанию равен anchor
scene.add_game_object(centered)

# Вложенность: дочерний элемент привязывается к родителю, а не к экрану
panel = GameObject(0, 0, name="Panel")
panel.add_component(UIButton("Placeholder", 300, 200, anchor="Center"))
scene.add_game_object(panel)

corner_label = GameObject(-8, -8, name="PanelCorner", parent=panel)
corner_label.add_component(UIText("v1.0", anchor="BottomRight", pivot="BottomRight"))

# Расположение в ряд: UILayoutGroup выстраивает элементы в колонку с промежутком `spacing` пикселей
menu = GameObject(40, 120, name="Menu")
group = menu.add_component(UILayoutGroup(direction="vertical", spacing=12))
scene.add_game_object(menu)
for label in ("Play", "Options", "Quit"):
    item = GameObject(0, 0, name=label)
    item.add_component(UIButton(label, 160, 40))
    scene.add_game_object(item)
    group.add_item(item)
```

---

## 8. Система частиц

**Описание:** `ParticleSystem` — лёгкий эмиттер для пыли, искр, взрывов и шлейфов. Частицы — не `GameObject`ы: это компактные структуры, переиспользуемые через `ObjectPool` (см. [10](#10-статические-сервисы-и-утилиты)): после «прогрева» непрерывная эмиссия не выделяет память и не создаёт мусора для сборщика. Частицы не участвуют в столкновениях. Цвет, размер и затухание — чистые функции возраста частицы (0…1 от рождения до смерти), поэтому система один раз заранее рендерит небольшой набор готовых поверхностей (`lut_steps` штук) и рисует частицу, выбирая подходящую плюс один пакетный блит — никакой отрисовки «частица за частицей». `color_stops` задаёт градиент по нескольким цветам; `world_space=True` (по умолчанию) оставляет частицы там, где они были испущены, даже если эмиттер двинулся дальше (взрыв, шлейф); `world_space=False` заставляет частицы двигаться вместе с эмиттером (пламя факела).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `ParticleSystem(...)` | `emission_rate: float = 0.0, lifetime: tuple = (0.5, 1.0), speed: tuple = (50.0, 100.0), direction: float = -90.0, spread: float = 360.0, gravity: float = 0.0, drag: float = 0.0, start_size: float = 6, end_size: float = None, start_color: tuple = (255,255,255), end_color: tuple = None, color_stops: list = None, start_alpha: int = 255, end_alpha: int = 0, shape: str = "circle", sprite: pygame.Surface = None, additive: bool = False, max_particles: int = 500, world_space: bool = True, z_index: int = 10, offset: tuple = (0.0, 0.0), spawn_radius: float = 0.0, duration: float = None, loop: bool = True, play_on_start: bool = True, lut_steps: int = 24, seed: int = None` | `direction`/`spread` — углы в градусах (0 = вправо, «−90» = вверх, по часовой стрелке); `additive=True` включает аддитивное смешивание (огонь, искры); `shape` — `"circle"` или `"square"`, либо передайте `sprite` для собственной формы; `duration`/`loop` делают эмиссию конечной или бесконечной. |
| `play()` / `stop(clear=False)` | — / `clear: bool` | Запустить непрерывную эмиссию (`emission_rate`) / остановить её (`clear=True` ещё и сразу убирает живые частицы). |
| `burst(count)` / `emit(count)` | `count: int` | Испустить `count` частиц разом (взрыв, всплеск) — `emit` — псевдоним `burst`. |
| `clear()` | — | Сразу убирает все текущие частицы. |
| `is_playing` | `bool` (свойство) | Идёт ли непрерывная эмиссия. |
| `particle_count` | `int` (свойство) | Сколько частиц живо прямо сейчас. |
| `invalidate()` | — | Перестроить таблицу цвета/размера/прозрачности после изменения этих параметров во время работы. |
| `pool` | `ObjectPool` (свойство) | Пул, из которого берутся структуры частиц. |

#### Пример использования

```python
from engine.components.particle_system import ParticleSystem
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("particles")

# Разовый залп искр (аддитивное смешивание, градиент жёлтый → оранжевый → тёмно-красный)
sparks_go = GameObject(400, 300, name="Sparks")
sparks = sparks_go.add_component(ParticleSystem(
    play_on_start=False, lifetime=(0.3, 0.6), speed=(120, 260), direction=-90, spread=180,
    gravity=500, start_size=8, end_size=1,
    color_stops=[(255, 246, 170), (255, 150, 40), (120, 40, 20)],
    additive=True, max_particles=200, seed=1,
))
scene.add_game_object(sparks_go)
sparks.burst(24)

# Непрерывный дым от факела: движется вместе с объектом (world_space=False)
torch_go = GameObject(200, 250, name="TorchSmoke")
smoke = torch_go.add_component(ParticleSystem(
    emission_rate=15, lifetime=(0.8, 1.4), speed=(20, 40), direction=-90, spread=30,
    gravity=-40, start_size=4, end_size=14, color_stops=[(200, 200, 200), (90, 90, 90)],
    start_alpha=160, end_alpha=0, world_space=False, play_on_start=True,
))
scene.add_game_object(torch_go)

for _ in range(60):
    scene.tick(1 / 60)
print("live smoke particles:", smoke.particle_count)
```

---

## 9. Графика, анимация и отрисовка

### 9.1. SpriteRenderer и якоря спрайтов

**Описание:** `SpriteRenderer` рисует `pygame.Surface` в мировой позиции объекта, применяя мировые поворот и масштаб его `Transform`. `anchor` использует те же девять имён, что и коллайдеры (см. [7.3](#73-якоря-и-точки-опоры-ui) и [5.2](#52-коллайдеры-boxcollider2d-circlecollider2d)): задайте спрайту и его коллайдеру один и тот же якорь, чтобы хитбокс и картинка совпадали. `z_index` определяет порядок слоёв (меньшее значение — дальше/раньше); при одинаковом `z_index` объекты сортируются по `world_y + offset_y`, а при равенстве — по `world_x + offset_x`, что даёт дешёвый приём глубины для платформеров и видов сверху. В какую сторону сортируется каждая ось — настройка сцены: `scene.render_system.sort_y` и `sort_x`, каждая `1`, `-1` или `0` (см. таблицу ниже). Спрайт преобразуется в формат дисплея при первой отрисовке (`convert()`/`convert_alpha()`), а повёрнутые/масштабированные варианты берутся из общего кэша (см. [10](#10-статические-сервисы-и-утилиты)) — статический объект никогда не пересчитывается каждый кадр. Какие объекты видит камера, решает отсечение по границам (см. [9.4](#94-оптимизация-тайлмапов-запекание)), так что спрайты за пределами экрана вообще не рисуются.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `SpriteRenderer(...)` | `sprite: pygame.Surface = None, z_index: int = 0, offset_y: float = 0, anchor: str = "topleft", convert: bool = True, offset_x: float = 0` | `convert=False` отключает автоматическое преобразование в формат дисплея (если поверхность уже подготовлена вручную). |
| `sprite` / `set_sprite(sprite)` | `pygame.Surface` | Текущий спрайт / его замена (используется `Animator`, см. [9.3](#93-анимация-и-спрайт-листы-animator)). |
| `anchor` | `str` | Одно из девяти названий якорей; недопустимое значение пишет предупреждение в лог и заменяется на `"topleft"`. |
| `z_index` | `int` | Порядок слоёв. |
| `offset_y` | `float` | Влияет только на ключ сортировки по глубине (`world_y + offset_y`), но не на позицию отрисовки. |
| `offset_x` | `float` | То же для горизонтального ключа сортировки (`world_x + offset_x`); имеет значение, только пока включена `sort_x`. |
| `scene.render_system.sort_y` | `int = 1` | Порядок отрисовки по Y внутри одного `z_index`: `1` — что ниже на экране (больше y), рисуется позже, спереди; `-1` — что ниже, рисуется раньше, сзади; `0` — Y не учитывается. Y сравнивается первым. Можно менять в любой момент. |
| `scene.render_system.sort_x` | `int = 0` | То же для X: `1` — что правее, рисуется позже, спереди; `-1` — что правее, рисуется раньше; `0` (по умолчанию) — X не учитывается. X лишь разрешает ничьи по Y, поэтому для порядка строго слева направо поставьте `sort_y = 0`. Запечённые слои и частицы сохраняют своё место (всегда до / после всех спрайтов). |
| `is_visible` | `bool` (свойство) | Рисовался ли спрайт в последние пару кадров — используется `Animator`, чтобы пропускать анимацию за пределами экрана. |
| `get_anchor_offset()` | — | `(dx, dy)` от позиции объекта до исходного левого верхнего угла спрайта в соответствии с якорем. |
| `get_transformed_sprite(rotation, scale_x, scale_y)` | `rotation: float, scale_x: float, scale_y: float` | Повёрнутый/масштабированный спрайт из общего кэша. |
| `get_placement(world_x, world_y, rotation, scale_x, scale_y)` | — | Итоговая поверхность и левый верхний угол для блита с учётом якоря, поворота и масштаба — используется системой отрисовки изнутри. |

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
# Один и тот же якорь у спрайта и коллайдера — они всегда визуально совпадают
enemy.add_component(SpriteRenderer(sprite=sprite, anchor="center", z_index=1))
enemy.add_component(BoxCollider2D(size=sprite.get_size(), anchor="center"))
scene.add_game_object(enemy)

enemy.transform.rotation = 15      # рисуется повёрнутым вокруг центра спрайта
enemy.transform.scale = 1.5        # рисуется в 1,5 раза крупнее
```

### 9.2. Камера

**Описание:** `Camera` следует за `target`, не трогая его `Transform` — вместо этого камера хранит собственную мировую точку, которую проход отрисовки вычитает из позиции каждого спрайта. Именно это придаёт прыжку естественное ощущение: двигается «вид», а не сам объект. `smooth_follow=True` (по умолчанию) плавно приближается к цели со скоростью `follow_speed` (экспоненциальное сглаживание — не зависит от частоты кадров и никогда не проскакивает цель); `smooth_follow=False` каждый кадр жёстко ставит камеру точно на цель. Камера читает **сглаженную** (интерполированную) позицию цели, поэтому на мониторах с высокой частотой обновления камера и спрайт цели двигаются синхронно, без отставания друг от друга. Без цели (`target=None`) мир рисуется вообще без смещения — как будто камеры нет.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Camera(...)` | `target: GameObject = None, follow_speed: float = 5.0, smooth_follow: bool = True, position: Vector2 = None` | `follow_speed` — чем он выше, тем «резче» слежение; `position` задаёт начальную точку (важно только до запуска `start()`, который сразу центрируется на цели). |
| `target` | `GameObject or None` | Текущая цель слежения. |
| `set_target(target, snap=True)` | `target: GameObject, snap: bool` | Переключает цель; `snap=True` сразу прыгает на неё, `False` — плавно подъезжает. |
| `snap_to_target()` | — | Мгновенно переносится на текущую позицию цели (полезно после телепортации или респауна). |
| `position` | `Vector2` | Текущая мировая точка, которая будет в центре экрана. |
| `get_offset(screen_width, screen_height)` | `screen_width: int, screen_height: int` | Мировая точка, попадающая в левый верхний угол экрана; `(0, 0)`, если цели нет. |
| `get_view_bounds(screen_width, screen_height)` | `screen_width: int, screen_height: int` | `(left, top, right, bottom)` мировой области, которая сейчас на экране. |
| `world_to_screen(world_pos, w, h)` / `screen_to_world(screen_pos, w, h)` | `Vector2, int, int` | Ручное преобразование координат (обычно удобнее `Scene.world_to_screen`/`screen_to_world`, см. [4.2](#42-управление-сценами-scene-и-scenemanager)). |

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
camera.snap_to_target()                  # камера мгновенно догоняет, без пролёта через весь мир

visible_left, visible_top, visible_right, visible_bottom = camera.get_view_bounds(1280, 720)
print(f"currently visible from x={visible_left:.0f} to x={visible_right:.0f}")
```

### 9.3. Анимация и спрайт-листы (Animator)

**Описание:** `Animator` переключает кадры `SpriteRenderer` во времени. Воспроизведение привязано к реальному времени (`dt * speed`), а не к частоте кадров. `play(name)` спроектирован так, чтобы его можно было безопасно вызывать **каждый кадр** с «нужной» анимацией: повторный вызов с тем же именем не сбрасывает её на кадр 0, а неповторяющаяся (`loop=False`) анимация, проигранная до конца, остаётся на последнем кадре, даже если `play()` продолжают вызывать. `force_restart=True` принудительно перезапускает с кадра 0. Если зацикленная анимация не рисовалась последние пару кадров (объект за пределами экрана), она просто **не тикает** — сотня врагов за экраном ничего не стоит. Незацикленные анимации и анимации с подписчиками `on_finished` тикают всегда, поэтому игровая логика («анимация атаки закончилась») срабатывает и за экраном. `load_spritesheet_animations()` строит набор анимаций прямо из спрайт-листа и JSON-атласа (форматы `"hash"` и `"array"`, как у TexturePacker), сортируя кадры по числовому индексу в имени файла, а не по алфавиту (иначе `"walk_10"` встал бы раньше `"walk_2"`).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Animator(...)` | `animations: dict = None, default_animation: str = None, frame_duration: float = 0.1, speed: float = 1.0, cull_offscreen: bool = True` | `animations` — словарь `{"name": [surface, surface, ...]}`. |
| `play(anim_name=None, loop=True, reverse=False, force_restart=False)` | `anim_name: str, loop: bool, reverse: bool, force_restart: bool` | Безопасно вызывать каждый кадр — см. описание выше. |
| `pause()` / `stop()` | — | Остановить на текущем кадре / остановить и сбросить на первый кадр. |
| `has_animation(anim_name)` | `anim_name: str` | Есть ли такая анимация в словаре — полезно для отката на анимацию по умолчанию. |
| `set_animations(animations)` | `animations: dict` | Заменяет весь набор анимаций (кадры преобразуются один раз). |
| `is_playing`, `current_animation`, `frame_index` | `bool`, `str`, `int` | Текущее состояние проигрывателя. |
| `on_finished` | `a list of fn(animator, anim_name)` | Срабатывает один раз, когда незацикленная анимация доходит до последнего кадра. |
| `load_spritesheet_animations(json_path, image_path, generate_flipped=True)` | `json_path: str, image_path: str, generate_flipped: bool` | Возвращает `{name: [surface, ...]}` для `Animator`. `generate_flipped=True` также создаёт зеркальную версию каждой анимации с префиксом `_` (например, `"idle"` → `"_idle"`). |

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

# Вариант 1: анимация, собранная вручную из готовых кадров (Surface)
idle_frames = [make_frame((90, 160, 230)), make_frame((100, 170, 240))]
animator = hero.add_component(Animator({"idle": idle_frames}, default_animation="idle",
                                       frame_duration=0.2))
scene.add_game_object(hero)

animator.play("idle")            # безопасно вызывать это каждый кадр в update()

# Вариант 2: анимация, собранная из спрайт-листа + JSON-атласа (при наличии assets/hero.png/.json)
# animations = load_spritesheet_animations("assets/hero.json", "assets/hero.png")
# hero.get_component(Animator).set_animations(animations)
```

### 9.4. Оптимизация тайлмапов (запекание)

**Описание:** Отрисовка тысяч статических тайлов — это тысячи вызовов `blit()` каждый кадр, бесконечно. Запекание рисует их **один раз**, при загрузке уровня, на большую поверхность (или на несколько «чанковых» поверхностей для огромной карты); каждый последующий кадр стоит по одному блиту на видимый чанк — обычно от одного до четырёх. `bake_tilemap()` строит статический `GameObject` прямо из сетки ID тайлов и словаря `{id: surface}`. `bake_static_sprites()` запекает статические неанимированные `SpriteRenderer`ы, **уже добавленные** в сцену, и отключает исходные компоненты (коллайдеры и игровые скрипты на тех же объектах продолжают работать как обычно). Полупрозрачные спрайты запекаются в пространстве с предумноженной альфой, поэтому наложение прозрачности совпадает с попиксельной отрисовкой с точностью до округления. Запечённые пиксели «заморожены» (они никогда не двигаются и не анимируются) и делят один слой на своём `z_index`. Спрайты при запекании перекрывают друг друга в порядке, который задают `scene.render_system.sort_y` / `sort_x` (см. [9.1](#91-spriterenderer-и-якоря-спрайтов)), поэтому задайте их **до** вызова `bake_static_sprites()`: порядок фиксируется в момент запекания. Сам запечённый слой всегда рисуется раньше обычных спрайтов с тем же `z_index`.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `bake_tilemap(grid, tileset, tile_size, origin=(0,0), z_index=-100, chunk_size=None, opaque=False, background=(0,0,0), name="BakedTilemap")` | `grid: list[list[int]], tileset: dict or list, tile_size: int or tuple, origin: tuple, z_index: int, chunk_size: int, opaque: bool, name: str` | Строит статический `GameObject` с запечённым слоем из сетки ID тайлов (`None`/`-1` — пустая клетка). Возвращает объект — добавьте его в сцену сами. |
| `bake_static_sprites(scene, chunk_size=None, z_range=None, opaque=False, name_prefix="Baked")` | `scene: Scene, chunk_size: int, z_range: tuple, opaque: bool` | Запекает каждый подходящий статический спрайт, уже находящийся в сцене, по одному слою на каждый `z_index`; порядок наложения берётся из `sort_y` / `sort_x` сцены на момент запекания. Возвращает список новых объектов-слоёв. |
| `BakedLayer(z_index=-100, chunk_size=None, opaque=False, background=(0,0,0))` | — | Компонент запечённого слоя (обычно создаётся через функции выше, а не напрямую). |
| `BakedLayer.bake(items)` | `items: a list of (surface, x, y)` | Запекает произвольный набор изображений в заданных мировых координатах. |
| `BakedLayer.chunk_count` | `int` (свойство) | Сколько чанковых поверхностей реально создано (только там, где что-то нарисовано). |
| `BakedLayer.premultiplied_supported()` | — (статический метод) | Доступно ли в этой сборке pygame точное смешивание прозрачности. |

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

# Вариант 1: напрямую из сетки ID тайлов
grid = [
    [1, 1, 1, 1, 1],
    [1, None, None, None, 1],   # None — пустая клетка (-1 тоже работает; но НЕ 0 — 0 это обычный id)
    [1, 1, 1, 1, 1],
]
tileset = {1: tile((110, 80, 50))}
ground = bake_tilemap(grid, tileset, tile_size=32, origin=(0, 300), z_index=-50)
scene.add_game_object(ground)
print("tiles baked:", ground.get_component(BakedLayer).item_count)

# Вариант 2: запечь то, что уже лежит в сцене в виде обычных статических спрайтов
for i in range(200):
    deco = create_square(i * 34, 500, size=30, color=(70, 130, 70), name=f"Grass{i}",
                         add_collider=False, is_static=True)
    scene.add_game_object(deco)

layers = bake_static_sprites(scene)      # сотни блитов травы -> горстка блитов чанков
print("baked layers created:", len(layers))
```

---

## 10. Статические сервисы и утилиты

Каждый сервис в этом разделе доступен из любого места вашего кода — достаточно импортировать класс, ссылка на `Engine` или `Scene` не нужна.

### Time

**Описание:** Глобальные часы движка. `fixed_delta_time` — длительность одного физического шага (по умолчанию 1/60 с; меняется через `Engine(fixed_fps=...)` или `Time.set_fixed_rate(hz)`); `alpha` — доля (0…1) прогресса между двумя последними физическими шагами, используемая интерполяцией при отрисовке (см. [4.4](#44-иерархия-трансформаций)); `time_scale = 0` ставит игру на паузу (останавливаются и гравитация, и игровая логика).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Time.delta_time` / `unscaled_delta_time` | `float` | Переменный шаг кадра: с учётом `time_scale` и без него. |
| `Time.fixed_delta_time` | `float` | Длительность одного физического шага. |
| `Time.time` / `unscaled_time` / `fixed_time` | `float` | Накопленное игровое время. |
| `Time.time_scale` | `float` | Множитель скорости всей игры; `0` ставит её на паузу. |
| `Time.alpha` | `float` | 0…1 между физическими шагами — для интерполяции. |
| `Time.frame_count` / `fixed_frame_count` | `int` | Счётчики кадров и физических шагов. |
| `Time.set_fixed_rate(hz)` | `hz: float` | Меняет частоту физики: `Time.set_fixed_rate(120)`. |
| `Time.reset()` | — | Сбрасывает все значения к значениям по умолчанию (используется в тестах). |

#### Пример использования

```python
from engine.core.game_time import Time

Time.time_scale = 0.0     # пауза: физика и update() продолжают вызываться, но dt = 0
Time.time_scale = 0.5     # половинная скорость
print(f"frame #{Time.frame_count}, physics step {Time.fixed_delta_time * 1000:.2f} ms")
```

### EventBus

**Описание:** Глобальная шина «издатель — подписчик», а также отдельная шина у каждого `GameObject` (`go.events`) — собственные события объекта никогда не доходят до глобальных подписчиков, и наоборот. `owner=` привязывает подписку к владельцу (`Scene`, `GameObject`): когда он уничтожается, `Scene.destroy()`/`GameObject.destroy()` автоматически сбрасывают все его подписки, избавляя от ручной отписки и предотвращая утечки. Исключение внутри обработчика пишется в лог через `Debug`, а остальные обработчики всё равно выполняются.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `EventBus.subscribe(event, callback, owner=None, once=False, priority=0, weak=False)` | `event: str, callback: callable, owner: any object, once: bool, priority: int, weak: bool` | Подписывает на глобальное событие; `weak=True` держит колбэк по слабой ссылке (уничтоженный слушатель отписывается сам). |
| `EventBus.emit(event, *args, **kwargs)` | `event: str, *args, **kwargs` | Уведомляет подписчиков: `EventBus.emit("game_over", score=120)`. |
| `EventBus.unsubscribe(event, callback)` / `unsubscribe_owner(owner)` | — | Отписывает один колбэк / сразу все подписки данного владельца. |
| `EventBus.once(event, callback, **kwargs)` | — | Срабатывает один раз, затем отписывается сам. |
| `EventBus.has_listeners(event)` / `listener_count(event=None)` | — | Есть ли подписчики / сколько их. |
| `go.events` | `EventDispatcher` | Приватная шина объекта: `player.events.subscribe("jumped", hud.on_jump)`. |

#### Пример использования

```python
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene import Scene

scene = Scene("events")
EventBus.subscribe("coin_collected", lambda amount: print(f"+{amount} points"), owner=scene)

player = GameObject(name="Player")
scene.add_game_object(player)
player.events.subscribe("jumped", lambda height: print(f"jumped {height} px"))

EventBus.emit("coin_collected", amount=10)      # это слышит глобальный подписчик
player.events.emit("jumped", height=64)         # это слышит только подписчик этого объекта

scene.destroy()          # подписка сцены на «coin_collected» сбрасывается автоматически
```

### ObjectPool и GameObjectPool

**Описание:** Переиспользование объектов вместо постоянного создания и выбрасывания — это позволяет избежать подтормаживаний сборщика мусора при частом порождении (пули, частицы, всплывающий текст). `ObjectPool` — универсальный пул для любых объектов, создаваемых фабрикой; `GameObjectPool` специализирует его для `GameObject`ов внутри конкретной `Scene`: простаивающие объекты остаются в сцене, но отключены (`active=False`), так что порождение — это просто переключение флага без изменения собственных списков сцены. Компоненты могут реализовать `on_spawn(**kwargs)` / `on_despawn()`, чтобы сбрасывать своё состояние (`Rigidbody2D` останавливается сам).

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `ObjectPool(factory, on_spawn=None, on_despawn=None, initial_size=0, max_size=None, name="ObjectPool")` | `factory: a callable with no arguments` | Универсальный пул. `initial_size` — сколько объектов создать заранее («прогрев»). |
| `GameObjectPool(scene, factory, initial_size=0, max_size=None, name="GameObjectPool", clear_events_on_despawn=False)` | `scene: Scene, factory: a callable returning a ready-made GameObject` | Пул объектов для одной сцены. |
| `spawn(*args, **kwargs)` (`ObjectPool`) / `spawn(x=None, y=None, **kwargs)` (`GameObjectPool`) | — | Выдаёт объект из пула (или создаёт новый, если свободных нет); `None`, если достигнут `max_size`. `**kwargs` передаются в `on_spawn` компонентов. |
| `despawn(obj)` | `obj` | Возвращает объект в пул. Для `GameObject` то же делает `go.despawn()`. |
| `despawn_all()` | — | Возвращает в пул каждый выданный сейчас объект. |
| `prewarm(count)` | `count: int` | Заранее создаёт `count` объектов, не активируя их. |
| `active_count` / `free_count` | `int` (свойства) | Сколько объектов сейчас выдано / свободно в пуле. |
| `active_objects()` | — | Свежий список выданных сейчас объектов: `for bullet in bullets.active_objects(): ...`. |

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

bullet.despawn()                                  # вернуть его в пул, а не destroy()
print("free in the pool:", bullets.free_count, "/ handed out:", bullets.active_count)
```

### PlayerPrefs

**Описание:** Хранилище настроек и данных сохранений в стиле Unity на основе одного JSON-файла (по умолчанию `playerprefs.json` в рабочем каталоге). Значения типизированы: вызов `get_int` для ключа, в котором на самом деле строка, возвращает значение по умолчанию, а не ошибку. `save()` пишет атомарно (через временный файл), поэтому сбой посреди записи никогда не оставит испорченный файл; если существующий файл всё же не разбирается, он переименовывается в `*.corrupt`, ошибка пишется в лог, а игра продолжает работу с пустым хранилищем. `Engine` сам сохраняет несохранённые изменения при выходе.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `PlayerPrefs.set_path(path)` / `get_path()` | `path: str` | Использовать другой файл (несохранённые изменения отбрасываются). |
| `set_int(key, value)` / `get_int(key, default=0)` | `key: str, value: int, default: int` | Целые числа: `PlayerPrefs.set_int("high_score", 4200)`. |
| `set_float(key, value)` / `get_float(key, default=0.0)` | `key: str, value: float, default: float` | Числа с плавающей точкой. |
| `set_string(key, value)` / `get_string(key, default="")` | `key: str, value: str, default: str` | Строки. |
| `has_key(key)` / `delete_key(key)` / `delete_all()` | `key: str` | Проверить наличие ключа / удалить одно значение / очистить всё хранилище. |
| `save()` | — | Атомарно записывает на диск. Пока это не вызвано, на диск ничего не попадает. |
| `reload()` | — | Отбрасывает несохранённые изменения и заново читает файл. |
| `is_dirty()` | — | Есть ли несохранённые изменения. |

#### Пример использования

```python
from engine.core.player_prefs import PlayerPrefs

PlayerPrefs.set_path("saves/profile.json")

PlayerPrefs.set_int("high_score", 4200)
PlayerPrefs.set_string("player_name", "Georgii")
PlayerPrefs.set_float("music_volume", 0.6)
PlayerPrefs.save()                              # до этой строки на диск ничего не записывается

print(PlayerPrefs.get_int("high_score"))        # 4200
print(PlayerPrefs.get_int("no_such_key", 0))    # 0 — значение по умолчанию
```

### AudioManager и AudioSource

**Описание:** `AudioManager` управляет музыкой, звуковыми эффектами, громкостью и позиционным звуком; для музыки зарезервированы два канала («две деки»), поэтому кроссфейд по-настоящему накладывает треки друг на друга, а звуковой эффект никогда не займёт канал музыки. Затухания выполняются внутри `update(dt)` и никогда не блокируют. Итоговая громкость = master × (sfx или music) × собственная громкость источника × затухание с расстоянием, пересчитывается каждый кадр — поэтому перемещение ползунка сразу влияет на уже играющие звуки. Позиционные звуки (`position=(x, y)`) линейно затухают между `min_distance` и `max_distance` вокруг слушателя (по умолчанию — активной камеры) и панорамируются по горизонтальному смещению. `AudioSource` — компонент для звука, прикреплённого к объекту (`spatial=True` заставляет его следовать за объектом). Если звукового устройства нет, всё просто пишется в лог и не мешает игре работать.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `AudioManager.play_music(path, loop=True, fade_in=0.0, volume=1.0)` | `path: str` | Запускает трек, обрывая предыдущий (с нарастанием громкости, если задан `fade_in`). |
| `AudioManager.crossfade_to(path, duration=2.0, loop=True, volume=1.0)` | `path: str, duration: float` | Плавно переключает треки: во время перехода играют оба сразу. |
| `AudioManager.stop_music(fade_out=0.0)` / `pause_music()` / `resume_music()` | — | Остановить (с затуханием) / поставить на паузу / продолжить музыку. |
| `AudioManager.play_sfx(sound, volume=1.0, loop=False, position=None, min_distance=100.0, max_distance=800.0, rolloff="linear")` | `sound: str or pygame.mixer.Sound, position: tuple` | Разовый или зацикленный звуковой эффект; `position` включает затухание с расстоянием и панорамирование. |
| `AudioManager.set_master_volume(v)` / `set_sfx_volume(v)` / `set_music_volume(v)` | `v: float, 0..1` | Три независимых ползунка громкости. |
| `AudioManager.mute()` / `unmute()` / `toggle_mute()` / `is_muted()` | — | Глобальное отключение звука. |
| `AudioManager.load_sound(path, cache=True)` / `preload(path, cache=True)` | `path: str` | Заранее загружает и кэширует звук, чтобы избежать паузы при первом воспроизведении (`preload` — псевдоним). Возвращает `pygame.mixer.Sound` или `None`, если файл отсутствует или не декодируется. |
| `AudioManager.get_master_volume()` / `get_sfx_volume()` / `get_music_volume()` | — | Считывает три ползунка обратно (0..1): `slider.value = AudioManager.get_music_volume()`. |
| `AudioManager.stop_all_sfx()` / `active_sfx_count()` | — | Останавливает все звуковые эффекты (музыка продолжает играть) / сколько эффектов играет прямо сейчас. |
| `AudioManager.current_music()` / `is_music_playing()` | — | Путь к треку, который играет (или нарастает), либо `None` / играет ли сейчас музыкальный трек. |
| `AudioManager.save_settings(prefix="audio.")` / `load_settings(prefix="audio.")` | `prefix: str` | Сохраняет/загружает три ползунка громкости через `PlayerPrefs`. |
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

**Описание:** Единая точка для логирования и отладочных оверлеев. `Debug` — псевдоним `DebugManager` (`Debug.log(...)` в стиле Unity `Debug.Log`). Встроенные оверлеи переключаются функциональными клавишами (переназначаются через `debug.keys`): **F1** — статистика (FPS, время кадра, число сущностей, вызовы отрисовки, счётчики физики), **F2** — контуры коллайдеров и векторы скорости, **F3** — сетка мировых координат, **F4** — прокручиваемая консоль последних записей лога. `Engine(debug=False)` разом отключает все горячие клавиши и оверлеи — для релизной сборки.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Debug.log(message, source=None)` | `message: any, source: str` | Обычная запись в лог: `Debug.log("Level loaded")`. |
| `Debug.log_warning(message, source=None)` / `log_error(message, source=None)` | — | Предупреждение / ошибка (разными цветами в консоли F4). |
| `Debug.log_exception(exc, source=None)` | `exc: Exception` | Пишет исключение в лог как ошибку. |
| `Debug.clear_logs()` | — | Очищает историю лога. |
| `debug.set_stat(name, value)` | `name: str, value: any or None` | Добавляет вашу собственную строку в оверлей F1 (`None` убирает её). |
| `debug.toggle_overlay()` / `toggle_colliders()` / `toggle_grid()` / `toggle_console()` | — | Программно переключает любой из четырёх оверлеев. |
| `debug.keys` | `dict` | Переназначает горячие клавиши: `debug.keys["console"] = "grave"`. |

#### Пример использования

```python
from engine.core.debug_manager import Debug

Debug.log("Game started")
Debug.log_warning("Texture not found, using a placeholder")
try:
    1 / 0
except ZeroDivisionError as exc:
    Debug.log_exception(exc, source="Startup")
```

### Vector2 и вспомогательные утилиты

**Описание:** `Vector2` — минимальный 2D-вектор, который используется везде, где иначе пришлось бы таскать пару `x`/`y` (позиция, скорость, смещение камеры). `engine.primitives` предоставляет быстрые фабрики готовых `GameObject`ов (прямоугольник, квадрат, круг, треугольник, линия) со спрайтом и, при желании, коллайдером и `Rigidbody2D` — удобно для прототипирования без подготовки собственных картинок.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `Vector2(x=0.0, y=0.0)` | `x: float, y: float` | Поддерживает `+`, `-`, унарный `-`, `*`/`/` на число, `+=`, `-=`, `==`. |
| `copy()` | — | Независимая копия. |
| `length()` | — | Длина вектора (`math.hypot`). |
| `normalized()` | — | Вектор того же направления длиной 1 (нулевой вектор остаётся `(0, 0)`, без деления на ноль). |
| `lerp(other, t)` | `other: Vector2, t: float` | Линейная интерполяция; `t` ограничивается диапазоном `[0, 1]`. |
| `as_tuple()` / `as_int_tuple()` | — | Обычный `(x, y)` или с округлением до целых. |
| `Vector2.zero()` / `Vector2.one()` | — (статические) | Быстрые `(0, 0)` и `(1, 1)`. |
| `create_rectangle(x=0, y=0, width=50, height=50, color=(200,200,200), name="Rectangle", add_collider=True, add_rigidbody=False, border_radius=0, is_static=False, layer=0)` | — | Готовый прямоугольный `GameObject`. |
| `create_square(x=0, y=0, size=50, ..., is_static=False, layer=0)` | — | То же для квадрата (длина стороны `size`). |
| `create_circle(x=0, y=0, radius=25, ..., precise_collider=False, is_static=False, layer=0)` | — | Круг; `precise_collider=True` даёт ему `CircleCollider2D` вместо хитбокса-приближения квадратом. |
| `create_triangle(x=0, y=0, size=50, ..., is_static=False, layer=0)` / `create_line(x=0, y=0, length=100, thickness=4, ..., vertical=False, is_static=False, layer=0)` | — | Треугольник, вписанный в квадрат `size×size`, и отрезок линии (горизонтальный или вертикальный). |

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

---

## 11. Сеть (многопользовательская игра по LAN)

Многопользовательский режим PygamE рассчитан на кооператив по локальной сети (друзья в одной сети Wi-Fi или за одним роутером): один игрок — **хост** (он тоже играет), все остальные **подключаются** к нему. Клиенты общаются только с хостом и никогда друг с другом, а хост решает, что существует, где стоит и кому принадлежит. Транспорт — TCP; потоков нет: `Engine.run()` вызывает `NetworkManager.update()` раз в кадр (см. [4.1](#41-engine-и-главный-цикл)), и тот опрашивает сокеты и применяет всё, что пришло. Система состоит из двух частей: статического сервиса `NetworkManager` ([11.1](#111-networkmanager)) и трёх компонентов, которые делают `GameObject` сетевым ([11.2](#112-сетевые-компоненты-networkidentity-networktransform-networkstate)).

### 11.1. NetworkManager

**Описание:** `NetworkManager` — статический сервис: он запускает сессию или подключается к ней, находит хосты в LAN, создаёт и уничтожает сетевые объекты и доставляет RPC. Хост — всегда игрок `0` (`HOST_PLAYER_ID`) и учитывается в `max_players`; каждый клиент при подключении получает следующий свободный id.

**Правила, на которых всё держится.** Шесть вещей, верных на каждом компьютере:

1. **Владелец управляет, остальные наблюдают.** У каждого сетевого объекта один владелец. Физика объекта работает только на компьютере владельца; на всех остальных компьютерах его `Rigidbody2D` отключается сам, а копия просто следует за получаемыми обновлениями. Менять `NetworkState` объекта может только владелец (остальные просят об изменениях через RPC).
2. **Создавайте и удаляйте через `NetworkManager`:** `spawn()` / `despawn()`. На хосте они выполняются сразу; на клиенте это *запрос* к хосту: `spawn()` возвращает `None`, а объект появляется на каждом компьютере (включая ваш) чуть позже — слушайте `network_object_spawned`, если нужна ссылка. Вызов `.destroy()` для сетевого объекта безопасен только на хосте (это замечается и рассылается); на клиенте он рассинхронизирует вас.
3. **Регистрируйте префабы на каждом компьютере** через `register_prefab` — до `host()` / `join()` — и делайте так, чтобы фабрика везде строила одно и то же. Компьютер, который не знает имени префаба, пишет ошибку в лог и пропускает этот объект, а не падает.
4. **По сети идут только простые данные:** числа, строки, `True`/`False`, `None`, списки и словари со **строковыми** ключами. Всё остальное (`set`, `Surface`, `NaN`, словарь с числовым ключом) вызывает `TypeError` прямо в месте вызова.
5. **Подключение посреди игры работает само:** хост присылает новичку каждый существующий объект с его текущей позицией и состоянием. Всё, что живёт *вне* объектов (таймер раунда, номер уровня), следует отправлять через RPC из вашего обработчика `network_player_joined`.
6. **Смена сцены не завершает сессию;** объекты клиента удаляются у всех, когда его сцена разрушается. Игрок, молчащий `peer_timeout` секунд, отключается, а если хост закрывается, сессия заканчивается для всех.

> **Ограничения.** Система рассчитана на друзей в локальной сети: **нет ни шифрования, ни аутентификации**. Клиент может двигать, менять или удалять только свои объекты — хост отклоняет всё остальное и отбрасывает некорректные сообщения, — но относитесь к ней как к инструменту для доверенной LAN, а не как к защите от читеров. Нет переноса хоста, нет клиентского предсказания (копии отстают от оригинала на сетевую задержку плюс сглаживание) и нет IPv6. Автоматический поиск использует UDP-широковещание, которое блокируют гостевые сети Wi-Fi и некоторые VPN, — тогда введите IP хоста в `join()` (он от поиска не зависит). Через интернет это работает, если хост пробросит порт. Проверено на Linux по loopback-TCP и на отдельных реальных процессах; не проверено на двух физических компьютерах, Windows и macOS.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `NetworkManager.host(...)` | `port: int = 7777, name: str = "Game", max_players: int = 8, player_name: str = "Host", discoverable: bool = True, discovery_port: int = 7778` | Начинает хостинг и делает этот компьютер игроком `0`. Возвращает `True` при успехе и `False`, если порт открыть не удалось (причина пишется в лог). `port=0` позволяет ОС выбрать свободный порт (прочитайте его из `NetworkManager.port`); `max_players` учитывает и хоста; `discoverable=True` ещё и объявляет игру в LAN, чтобы другие компьютеры могли найти её без IP. |
| `NetworkManager.join(...)` | `address: str, port: int = 7777, name: str = "Player", timeout: float = 5.0` | Начинает подключение и сразу возвращается; результат приходит событием (`network_connected` / `network_connection_failed`), поэтому подпишитесь заранее. `timeout` ограничивает всё рукопожатие. Лучше использовать числовой IP — имя хоста разрешается синхронно и может подвесить кадр. |
| `NetworkManager.disconnect()` | — | Покидает сессию (хост закрывает её для всех). Безопасно вызывать откуда угодно, включая обработчик события. |
| `NetworkManager.kick(player_id, reason="kicked")` | `player_id: int, reason: str = "kicked"` | **Только хост.** Удаляет игрока; тот получает `network_disconnected` с этой `reason`. Возвращает `True`, если кого-то исключили. |
| `NetworkManager.players()` | — | Свежий список `PlayerInfo(id, name, ping_ms)` для всех в сессии, включая вас и хоста; пуст, если нет подключения. |
| `NetworkManager.get_ping(player_id)` | `player_id: int` | Последнее измеренное время кругового пути до этого игрока в миллисекундах или `None`, если оно пока неизвестно (хост измеряет каждого клиента; клиент измеряет хоста). |
| `NetworkManager.local_ip()` | — | Приблизительный адрес в LAN, который стоит показать игрокам, чтобы они ввели его в `join()`; при неудаче возвращается `"127.0.0.1"`. |
| `NetworkManager.is_host` / `is_client` / `is_connected` / `is_connecting` | `bool` | Состояние сессии. `is_connected` равно `True` для хоста и для клиента, завершившего рукопожатие. |
| `NetworkManager.local_player_id` | `int or None` | Ваш id игрока (`0` у хоста); `None` вне сессии. |
| `NetworkManager.start_discovery(discovery_port=7778)` / `stop_discovery()` | `discovery_port: int = 7778` | Начинает / прекращает прослушивание хостов в LAN. |
| `NetworkManager.discovered_servers()` | — | Свежий список `ServerInfo(name, address, port, players, max_players, last_seen)`, видимых в данный момент (пуст, пока никто не ответил). Используйте `address` и `port` для `join()`. |
| `NetworkManager.register_prefab(name, factory)` | `name: str, factory: fn(x, y, **kwargs) -> GameObject` | Регистрирует рецепт сетевого объекта. Фабрика возвращает `GameObject`, который пока не находится ни в одной сцене; `NetworkManager` добавляет его в активную сцену и прикрепляет `NetworkIdentity` (и `NetworkTransform` по умолчанию, если фабрика не добавила свой). |
| `NetworkManager.spawn(prefab_name, x, y, owner_id=None, **kwargs)` | `prefab_name: str, x: float, y: float, owner_id: int = None` | Создаёт сетевой объект на каждом компьютере. `kwargs` везде передаются фабрике, поэтому должны быть простыми данными. `owner_id` по умолчанию — вызывающий; хост может отдать владение любому игроку, клиент — только себе или хосту. На хосте возвращает `GameObject`, на клиенте — `None`. |
| `NetworkManager.despawn(target)` | `target: GameObject, NetworkIdentity, or int` | Уничтожает сетевой объект везде (при вызове на клиенте — запрос к хосту). |
| `NetworkManager.get_networked_object(network_id)` | `network_id: int` | Объект с этим id на данном компьютере или `None`. |
| `NetworkManager.networked_objects()` / `objects_owned_by(player_id=None)` | `player_id: int = None` | Свежий список всех сетевых объектов здесь / принадлежащих игроку (по умолчанию — вам), например «найти собственный аватар». |
| `NetworkManager.register_rpc(name, handler)` / `unregister_rpc(name, handler=None)` | `name: str, handler: fn(sender_id, *args, **kwargs)` | Регистрирует (или убирает) обработчик именованного удалённого вызова. Несколько обработчиков на одно имя вызываются все, в порядке регистрации. |
| `NetworkManager.send_rpc(name, *args, target="all", **kwargs)` | `name: str, target: "all", "host", or a player id` | Вызывает `name` на других компьютерах: `"all"` — все, *включая вас*, `"host"` — только хост, целое число — только этот игрок. Каждый вызов идёт через хост, поэтому ждите несколько миллисекунд до его действия, даже локально. Аргументы должны быть простыми данными. Если нет подключения, ничего не делает (и пишет в лог). |
| Настройки (атрибуты класса) | `ping_interval = 2.0`, `peer_timeout = 8.0`, `handshake_timeout = 5.0`, `accepting_players = True` | Как часто измерять пинг (с); сколько терпеть молчащего игрока до отключения (с); лимит рукопожатия при подключении (с); `False` запрещает подключаться новым игрокам (блокировка «игра уже идёт»). `max_players`, `local_name`, `session_name` и `port` тоже доступны для чтения. |
| EventBus: `network_connected` | `as_host: bool, player_id: int` | Вы в сессии. |
| EventBus: `network_connection_failed` | `reason: str` | `join()` не удался (`"timeout"`, `"server_full"`, имя сокетной ошибки вроде `ECONNREFUSED`, ...). |
| EventBus: `network_disconnected` | `reason: str` | Вы вышли или были удалены: `"left"`, `"kicked"`, `"host_closed"`, `"disconnected"`, `"timeout"`. |
| EventBus: `network_player_joined` / `network_player_left` | `player_id: int, name: str` / `player_id: int, reason: str` | Кто-то вошёл в сессию или вышел из неё. |
| EventBus: `network_object_spawned` / `network_object_despawned` | `game_object, network_id, owner_id` / `network_id` | Сетевой объект появился или исчез на этом компьютере — а также способ получить объект, который запросил `spawn()` клиента. |

#### Пример использования

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.components.network_state import NetworkState
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.event_bus import EventBus
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.core.scene_manager import SceneManager
from engine.networking.network_manager import NetworkManager


def make_player(x, y, **kwargs):                  # ОДНА функция, зарегистрированная и на хосте, И на каждом клиенте
    go = GameObject(x, y, name="Player")
    go.add_component(BoxCollider2D(size=(32, 32)))
    go.add_component(Rigidbody2D(gravity=900))
    go.add_component(NetworkState({"hp": 100}))
    return go


SceneManager.change_scene(Scene("lobby"))         # сетевые объекты добавляются в активную сцену
NetworkManager.register_prefab("player", make_player)          # до host() / join()
NetworkManager.register_rpc("say", lambda sender_id, text: print(f"player {sender_id} says: {text}"))
EventBus.subscribe("network_player_joined", lambda player_id, name: print(name, "joined"))

# ---- на компьютере хоста ----
if NetworkManager.host(port=0, name="My game", player_name="Alice", discoverable=False):
    print("hosting at", NetworkManager.local_ip(), "port", NetworkManager.port)
    avatar = NetworkManager.spawn("player", 100, 100)         # собственный аватар хоста (здесь — настоящий GameObject)
    NetworkManager.send_rpc("say", "hello everyone", target="all")
    NetworkManager.update()                                   # Engine.run() делает это раз в кадр
    print([(p.id, p.name) for p in NetworkManager.players()])        # [(0, 'Alice')]
    print(len(NetworkManager.objects_owned_by()))                    # 1: аватар
    NetworkManager.disconnect()

# ---- на компьютере друга ----
#   NetworkManager.register_prefab("player", make_player)             # та же регистрация
#   EventBus.subscribe("network_connected", on_connected)             # затем:
#   NetworkManager.join("192.168.1.42")                               # IP хоста, его показывает local_ip()
# ---- или пусть игра сама найдёт хосты ----
#   NetworkManager.start_discovery()
#   for server in NetworkManager.discovered_servers():                # ServerInfo(name, address, port, ...)
#       print(server.name, server.address, server.port, f"{server.players}/{server.max_players}")
```

### 11.2. Сетевые компоненты (NetworkIdentity, NetworkTransform, NetworkState)

**Описание:** Три компонента делают объект сетевым. **`NetworkIdentity`** помечает `GameObject` как сетевой: все компьютеры согласны насчёт его `network_id`, и ровно один игрок (`owner_id`) обладает над ним авторитетом. Вы никогда не создаёте его сами — `NetworkManager` прикрепляет его при создании объекта. **`NetworkTransform`** реплицирует позицию (и, при желании, поворот): на компьютере владельца он отправляет трансформацию `send_rate` раз в секунду, но только если она изменилась; на всех остальных компьютерах он плавно подтягивает копию к последней полученной позиции (`smoothing_speed`) — и перескакивает прямо туда, если разрыв больше `snap_distance`, чтобы телепортация или портал не выглядели как скольжение через всю карту. Он добавляется автоматически, если ваша фабрика не добавила свой. **`NetworkState`** — небольшой набор именованных значений (здоровье, счёт, «открыта ли дверь»), которые все компьютеры видят для одного объекта: владелец вызывает `set()`, а все остальные — `get()`; изменения передаются небольшими дельтами не чаще `send_rate` раз в секунду; игрок, который подключается позже, получает текущие значения вместе с объектом.

> **Ограничения.** Только владелец может вызывать `NetworkState.set()` — на любом другом компьютере это пишет предупреждение в лог и ничего не делает; вместо этого отправьте владельцу RPC. Значения должны быть простыми данными, а то, что возвращает `get()`, — только для чтения: если изменить список «на месте», он никогда не будет отправлен — вызывайте `set()` с новым значением.

#### API и методы

| Метод / Свойство | Сигнатура / Параметры | Описание и использование |
| :--- | :--- | :--- |
| `NetworkIdentity(...)` | `network_id: int, owner_id: int, prefab_name: str, spawn_kwargs: dict = None` | Создаётся `NetworkManager`, но никогда не вручную (созданный вручную нёс бы id, которого никто больше не знает). |
| `NetworkIdentity.network_id` / `owner_id` / `prefab_name` / `spawn_kwargs` | `int` / `int` / `str` / `dict` | Общий id, id игрока-владельца, префаб, из которого построен объект, и именованные аргументы, с которыми он был создан. |
| `NetworkIdentity.is_owner` (псевдоним `is_mine`) | `bool` (свойство) | `True`, если локальный игрок обладает авторитетом над этим объектом — проверка «может ли мой ввод двигать это?»: `if not identity.is_owner: return`. |
| `NetworkTransform(...)` | `send_rate: float = 20, sync_rotation: bool = False, smoothing_speed: float = 15.0, snap_distance: float = 600.0` | `send_rate` — обновлений в секунду (отправляются, только если трансформация изменилась); `sync_rotation=True` реплицирует и поворот; чем выше `smoothing_speed`, тем быстрее копия догоняет; полученная позиция дальше чем на `snap_distance` px применяется мгновенно (`None` — всегда скользить). |
| `NetworkState(...)` | `initial: dict = None, send_rate: float = 10` | `initial` хранит начальные значения (простые данные); `send_rate` ограничивает число сообщений в секунду (значение, меняющееся каждый кадр, стоит одного сообщения за интервал, а не одного за кадр). |
| `NetworkState.set(key, value)` | `key: str, value` | **Только владелец.** Меняет значение и реплицирует его. |
| `NetworkState.get(key, default=None)` | `key: str, default=None` | Читает значение на любом компьютере. |
| `NetworkState.items()` / `snapshot()` | — | Свежий список пар `(key, value)` / глубокая копия всех значений в виде словаря. |
| `NetworkState.on_changed` | `a list of fn(key, value, is_local)` | Вызывается на каждом компьютере, когда значение действительно меняется; `is_local` равно `True` на том, кто вызвал `set()`: `state.on_changed.append(lambda key, value, is_local: ...)`. |

#### Пример использования

```python
from engine.components.box_collider2d import BoxCollider2D
from engine.components.component import Component
from engine.components.network_identity import NetworkIdentity
from engine.components.network_state import NetworkState
from engine.components.network_transform import NetworkTransform
from engine.components.rigidbody2d import Rigidbody2D
from engine.core.game_object import GameObject
from engine.core.scene import Scene
from engine.core.scene_manager import SceneManager
from engine.input.input_manager import Input
from engine.networking.network_manager import NetworkManager


class Move(Component):
    def update(self, delta_time):
        if not self.game_object.get_component(NetworkIdentity).is_owner:
            return                                  # копии других игроков двигает сеть, а не эта клавиатура
        self.game_object.get_component(Rigidbody2D).velocity.x = Input.get_axis("a", "d") * 220


def make_player(x, y, **kwargs):
    go = GameObject(x, y, name="Player")
    go.add_component(BoxCollider2D(size=(32, 32)))
    go.add_component(Rigidbody2D(gravity=900))
    go.add_component(NetworkTransform(send_rate=30, snap_distance=400))     # необязательно: иначе будет добавлен вариант по умолчанию
    go.add_component(NetworkState({"hp": 100}))
    go.add_component(Move())
    return go


SceneManager.change_scene(Scene("coop"))
NetworkManager.register_prefab("player", make_player)

if NetworkManager.host(port=0, discoverable=False):
    avatar = NetworkManager.spawn("player", 100, 100)
    identity = avatar.get_component(NetworkIdentity)
    print(identity.owner_id, identity.is_owner)             # 0 True: хост владеет собственным аватаром

    state = avatar.get_component(NetworkState)
    state.on_changed.append(lambda key, value, is_local: print("changed:", key, value, is_local))
    state.set("hp", 80)                                     # только владелец; каждый узел видит это чуть позже
    print(state.get("hp"))                                  # 80
    NetworkManager.disconnect()
```

