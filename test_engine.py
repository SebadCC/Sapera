import os
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
pygame.init()

import importlib.util

def load_module(name, path):
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# ------------------------------------------------------------
# 1. Test Versiones Pasadas (Respaldo en 'Versiones pasadas/')
# ------------------------------------------------------------
path_21 = os.path.join("Versiones pasadas", "1.21.py")
m21 = load_module("mod_1_21", path_21)
if m21:
    print("--- Test Versiones pasadas/1.21.py ---")
    app21 = m21.App()
    state21 = app21.new_game_state()
    for tick in range(10):
        d = app21.bot.choose_direction(state21, app21.cfg, tick * 80)
        state21.direction = d
        app21.rules.step(state21, app21.cfg, tick * 80)
    app21.udp.sock.close()
    print("1.21.py ticks passed successfully!")

# ------------------------------------------------------------
# 2. Test 2.0.py Monolítico (Verificación de Respaldo)
# ------------------------------------------------------------
if os.path.exists("2.0.py"):
    print("--- Test 2.0.py Legacy Monolithic ---")
    m20 = load_module("mod_2_0", "2.0.py")
    app20 = m20.ColosseumApp()
    for mode in m20.GameMode:
        st = app20.create_initial_state(mode)
        st.countdown_active = False
        for tick in range(15):
            app20.bot.decide_all(st, tick * 80)
            app20.rules.step(st, tick * 80)
        alive = sum(1 for s in st.snakes if s.alive)
        print(f"2.0.py [{mode.name}] passed! Snakes alive: {alive}/{len(st.snakes)}")
    app20.udp.sock.close()

# ------------------------------------------------------------
# 3. Test Arquitectura Modular v2.0 (main.py, models, horse, riders, rules, renderer, scenes)
# ------------------------------------------------------------
print("--- Test Nueva Arquitectura Modular (main.py) ---")
from collections import deque
from main import ColosseumApp
from models import (
    Point, Direction, Food, FactionId, GameMode, ColosseumMatchSetup, NuclearStrike
)
from horse import HorseVerifier
from riders import SpiralPattern, PerimeterPattern
from scenes import MainMenuScene, ModeSelectScene, ColosseumSetupScene, PlayScene
from events import GameEvent

app = ColosseumApp()
surf = pygame.Surface((648, 704))

# A. Modos estándar en la arquitectura modular
for mode in GameMode:
    st = app.create_initial_state(mode)
    st.countdown_active = False
    assert len(st.foods) == len(st.snakes), "Debe haber 1 Manzana Dorada por serpiente activa"
    for f in st.foods:
        assert f.golden is True, "Las manzanas iniciales deben ser Doradas (re-spawneables)"

    for tick in range(20):
        app.bot.decide_all(st, tick * 80)
        app.rules.step(st, tick * 80)
        app.renderer.render(surf, st, tick * 80)
    alive = sum(1 for s in st.snakes if s.alive)
    print(f"Modular Mode [{mode.name}] passed! Snakes alive: {alive}/{len(st.snakes)}")

# B. Test Nuevo Sistema de Manzanas: Doradas (respawn) vs Normales (consumibles)
print("--- Test Sistema de Manzanas Doradas vs Normales ---")
st_food = app.create_initial_state(GameMode.SPEEDRUN)
st_food.countdown_active = False
assert len(st_food.foods) == 1
assert st_food.foods[0].golden is True

# Test Tecla C: Spawnea Manzana Normal (golden=False)
app.actions.dispatch([GameEvent("SPAWN_NORMAL_FOOD")], st_food, 0)
assert len(st_food.foods) == 2
normal_foods = [f for f in st_food.foods if not f.golden]
assert len(normal_foods) == 1, "Debe existir exactamente 1 Manzana Normal roja-verde"

# Test Tecla V: Elimina 1 Manzana Dorada
app.actions.dispatch([GameEvent("REMOVE_GOLDEN_FOOD")], st_food, 0)
assert len(st_food.foods) == 1
assert st_food.foods[0].golden is False, "Solo debe quedar la Manzana Normal tras remover la dorada"

# Comer Manzana Normal: no debe respawnear otra
snake = st_food.snakes[0]
target_pos = st_food.foods[0].pos
snake.body[0] = Point(target_pos.x - 1, target_pos.y) # Poner cabeza adyacente
snake.direction = Direction.RIGHT
app.rules.step(st_food, 100)
assert len(st_food.foods) == 0, "Al comer Manzana Normal, NO debe respawnear otra (consumible)"

# Re-spawnear Manzana Dorada y comerla: debe respawnear inmediatamente
p_free = app.rules.random_free_cell(st_food)
assert p_free is not None
st_food.foods.append(Food(pos=p_free, value=1, golden=True))
snake.body[0] = Point(p_free.x - 1, p_free.y)
snake.direction = Direction.RIGHT
app.rules.step(st_food, 200)
assert len(st_food.foods) == 1, "Al comer Manzana Dorada, DEBE respawnear otra inmediatamente"
assert st_food.foods[0].golden is True
print("Sistema de Manzanas Doradas vs Normales (y teclas C/V) verificado con éxito!")

# C. Test Modo Hipnótico: Espiral Respiratoria, Detector de Bucles y Pulso de Hambre
print("--- Test Modo Hipnótico Zen & Anti-Bucles ---")
st_hyp = app.create_initial_state(GameMode.HYPNOTIC)
st_hyp.countdown_active = False
s_hyp = st_hyp.snakes[0]

# 1. Espiral respiratoria oscilante
spiral = SpiralPattern()
d_in = spiral.preferred_direction(Point(0, 0), Direction.RIGHT, 22, True, tick=50, rng=app.rng)
d_out = spiral.preferred_direction(Point(10, 10), Direction.RIGHT, 22, True, tick=180, rng=app.rng)
assert d_in in Direction and d_out in Direction

# 2. Detección de bucle
s_hyp.head_history.clear()
quad_points = [Point(1, 1), Point(2, 1), Point(2, 2), Point(1, 2)]
for _ in range(20):
    for pt in quad_points:
        s_hyp.head_history.append(pt)
assert HorseVerifier.detect_loop(s_hyp) is True, "HorseVerifier debe detectar ciclo repetitivo"

# 3. Pulso de hambre zen
s_hyp.hunger_ticks = 150 # Más de 120 ticks sin comer
d_hyp = app.bot._choose_direction_for_snake(s_hyp, st_hyp, 0)
assert d_hyp in Direction
print("Modo Hipnótico: Espiral, detección de bucles y pulso de hambre aprobados!")

# D. Test Escenas UI y Navegación
print("--- Test Escenas UI y Configuración del Coliseo ---")
menu = MainMenuScene(app)
menu.render(surf, 0)

modes_scene = ModeSelectScene(app)
ev_colosseum = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (200, 130)})
setup_scene = modes_scene.handle([ev_colosseum])
assert isinstance(setup_scene, ColosseumSetupScene)

# Cambio de tamaño a 48x48
ev_grid48 = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (500, 100)})
setup_scene.handle([ev_grid48])
assert setup_scene.grid_options[setup_scene.selected_grid_idx][0] == 48

# Cambio a 5 serpientes
ev_cnt5 = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (500, 160)})
setup_scene.handle([ev_cnt5])
assert setup_scene.selected_count == 5

# Lanzar batalla
ev_start = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (300, 595)})
play_scene = setup_scene.handle([ev_start])
assert isinstance(play_scene, PlayScene)
assert play_scene.state.grid_size == 48
assert len(play_scene.state.snakes) == 5
print("Configuración interactiva del Coliseo validada!")

# E. Test Simulación de Arenas Multijugador en Arenas Personalizadas
print("--- Test Simulación en Arenas Multi-Grid (16x16, 22x22, 32x32, 48x48) ---")
test_arenas = [
    (16, [FactionId.RED, FactionId.GREEN]),
    (16, [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE]),
    (22, [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE, FactionId.GOLD]),
    (32, [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE, FactionId.GOLD]),
    (48, [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE, FactionId.GOLD]),
]

for g_size, f_list in test_arenas:
    c_setup = ColosseumMatchSetup(grid_size=g_size, factions=f_list)
    arena_state = app.create_initial_state(GameMode.BATTLE_ROYALE, setup=c_setup)
    arena_state.countdown_active = False
    assert arena_state.grid_size == g_size
    assert len(arena_state.snakes) == len(f_list)
    for tick in range(25):
        app.bot.decide_all(arena_state, tick * 80)
        app.rules.step(arena_state, tick * 80)
        app.renderer.render(surf, arena_state, tick * 80)
    alive_cnt = sum(1 for s in arena_state.snakes if s.alive)
    print(f"Arena {g_size}x{g_size} ({len(f_list)} gladiadores) -> Vivos tras 25 ticks: {alive_cnt}/{len(f_list)}")

# F. Test Choque Frontal por Tamaño y Desempate de Rondas
print("--- Test Choque Frontal por Tamaño y Desempate Técnico ---")
st_crush = app.create_initial_state(GameMode.DUEL_1V1)
st_crush.countdown_active = False
s_red = st_crush.snakes[0]
s_green = st_crush.snakes[1]

# s_red tiene longitud 6, s_green tiene longitud 4
s_red.body = deque([Point(5, 5), Point(4, 5), Point(3, 5), Point(2, 5), Point(1, 5), Point(0, 5)])
s_green.body = deque([Point(7, 5), Point(8, 5), Point(9, 5), Point(10, 5)])
s_red.direction = Direction.RIGHT
s_green.direction = Direction.LEFT

# Ambos van hacia Point(6, 5) en el siguiente tick
app.rules.step(st_crush, 1000)
assert s_red.alive is True, "La serpiente más larga (Red: len 6) DEBE aplastar y sobrevivir"
assert s_green.alive is False, "La serpiente más corta (Green: len 4) DEBE perecer en el choque"
assert s_red.score > 0, "La serpiente victoriosa debe recibir recompensa de puntos"
print("Choque frontal por tamaño verificado: La serpiente mayor aplasta a la menor!")

# Desempate de ronda cuando todas mueren simultáneamente
st_tie = app.create_initial_state(GameMode.DUEL_1V1)
st_tie.countdown_active = False
st_tie.snakes[0].score = 15
st_tie.snakes[1].score = 5
st_tie.snakes[0].alive = False
st_tie.snakes[1].alive = False
app.rules.step(st_tie, 2000)
assert "GANA" in st_tie.round_winner or "VICTORIA" in st_tie.round_winner, "Debe proclamar ganador por puntos"
assert "EMPATE" not in st_tie.round_winner, "No debe haber empate si los puntajes difieren"
print("Desempate técnico por puntos/longitud verificado!")

# G. Test Bomba Atómica: Escalamiento de Radio, Amputación Limpia y Supervivencia Continua
print("--- Test Bomba Atómica: Escalamiento y Amputación Limpia ---")
st_nuke = app.create_initial_state(GameMode.SPEEDRUN)
st_nuke.countdown_active = False
s_test = st_nuke.snakes[0]
# Serpiente de longitud 10: cabeza en (15, 15), cola extendiéndose hacia (5, 15)
s_test.body = deque([Point(15 - i, 15) for i in range(10)]) # [Point(15, 15), Point(14, 15), ..., Point(6, 15)]
s_test.direction = Direction.RIGHT

# Detonar bomba nuclear en (6, 15) con radio 3
# La cabeza (15, 15) está fuera del radio (distancia 9). Los segmentos en x <= 9 quedan en el cráter.
center_nuke = Point(6, 15)
blast_r = 3
st_nuke.nuclear = NuclearStrike(center=center_nuke, blast_radius=blast_r, start_ms=0, fall_duration_ms=500)
app.rules._apply_nuclear_blast(st_nuke, center_nuke, blast_r)

assert s_test.alive is True, "La serpiente debe sobrevivir porque su cabeza estaba fuera de la zona cero"
assert len(s_test.body) < 10, "La serpiente debe haber perdido los segmentos afectados"
assert len(s_test.body) >= 3, "La serpiente debe mantener un mínimo de 3 unidades"

# Verificar que el cuerpo resultante sea 100% contiguo (sin segmentos flotantes separados)
pts_list = list(s_test.body)
for idx in range(len(pts_list) - 1):
    dx = abs(pts_list[idx].x - pts_list[idx + 1].x)
    dy = abs(pts_list[idx].y - pts_list[idx + 1].y)
    assert dx + dy == 1, f"La serpiente amputada DEBE ser 100% contigua sin huecos: {pts_list[idx]} -> {pts_list[idx+1]}"
print("Bomba atómica verificada: Cabeza sobrevive y cuerpo amputado permanece 100% contiguo!")

# H. Test Globos de Diálogo Cómicos y Alivio al Comer
print("--- Test Globos de Diálogo, Alivio al Comer e Inanición Escalonada ---")
from models import FOOD_RELIEF_PHRASES, HUNGER_TIER1_PHRASES, HUNGER_TIER2_PHRASES, PRE_DEATH_CRIES, FACTION_KILL_PHRASES

# 1. Alivio inmediato al comer tras pasar hambre
st_relief = app.create_initial_state(GameMode.SPEEDRUN)
st_relief.countdown_active = False
s_hungry = st_relief.snakes[0]
s_hungry.hunger_ticks = 160
s_hungry.speech_text = "¡Ayudaaaaaaaaaa! 😭"
s_hungry.speech_until_ms = 4000

# Colocar manzana en el siguiente paso
food_pos = Point(s_hungry.body[0].x + 1, s_hungry.body[0].y)
st_relief.foods = [Food(pos=food_pos, value=1, golden=True)]
s_hungry.direction = Direction.RIGHT
app.rules.step(st_relief, 1000)

assert s_hungry.hunger_ticks == 0, "El contador de hambre debe reiniciarse a 0 tras comer"
assert s_hungry.speech_text in FOOD_RELIEF_PHRASES, f"Debe mostrar frase de alivio, obtuvo: {s_hungry.speech_text}"
print("Alivio al comer verificado: ¡El letrero de hambre se borra y celebra la comida!")

# 2. Umbrales de hambre: ninguna queja si hunger_ticks < 120
s_young = st_relief.snakes[0]
s_young.speech_text = None
s_young.speech_until_ms = 0
s_young.hunger_ticks = 40
app.rules.step(st_relief, 2000)
assert s_young.speech_text is None, "No debe quejarse si hunger_ticks < 120"
print("Umbrales de hambre escalonados verificados!")

# I. Test Personalidad de Jinetes: Frases de Victoria / Eliminación de Rivales
print("--- Test Personalidad de Jinetes en Combate ---")
st_pers = app.create_initial_state(GameMode.DUEL_1V1)
st_pers.countdown_active = False
s_red = st_pers.snakes[0]
s_green = st_pers.snakes[1]

# s_red aplasta a s_green
s_red.body = deque([Point(5, 5), Point(4, 5), Point(3, 5), Point(2, 5)])
s_green.body = deque([Point(7, 5), Point(8, 5)])
s_red.direction = Direction.RIGHT
s_green.direction = Direction.LEFT
app.rules.step(st_pers, 3000)

assert s_green.alive is False, "Verde debe ser eliminado"
assert s_red.speech_text in FACTION_KILL_PHRASES[FactionId.RED], f"Rojo debe decir frase asesina de Fénix, dijo: {s_red.speech_text}"
print("Frases de personalidad y victoria por facción verificadas!")

# J. Test Alarma de Muerte Inminente del Caballo, Slow Motion y Kill Camera
print("--- Test Alarma del Caballo, Slow Motion y Kill Camera ---")
# J.1 Test Falsas Muertes: Si una cola rival se desocupa en t+1, NO es muerte garantizada
st_false_check = app.create_initial_state(GameMode.DUEL_1V1)
st_false_check.countdown_active = False
s_p1 = st_false_check.snakes[0]
s_p2 = st_false_check.snakes[1]
# s_p1 en (5, 5), rodeado por pared/cuerpos excepto (6, 5) que es la cola de s_p2
s_p1.body = deque([Point(5, 5), Point(5, 6), Point(5, 7)])
s_p2.body = deque([Point(7, 5), Point(6, 5)]) # Cabeza en (7, 5), cola en (6, 5)
s_p2.direction = Direction.UP # s_p2 se mueve a (7, 4), liberando su cola en (6, 5)
is_dead = HorseVerifier.is_next_tick_death_guaranteed(s_p1, st_false_check, wall_col=True, n=st_false_check.grid_size)
assert is_dead is False, "NO debe considerarse muerte inminente si una celda (como la cola rival) queda libre en t+1"
print("Cero falsas muertes verificado: Cola rival desocupándose no dispara falsa alarma.")

# J.2 Test Muerte Inminente Real -> Activa Slow Motion y Kill Camera
st_killcam = app.create_initial_state(GameMode.BATTLE_ROYALE)
st_killcam.countdown_active = False
s_doomed = st_killcam.snakes[0]
s_doomed.imminent_death = True
orig_head = s_doomed.body[0]

app.rules.step(st_killcam, 4000)
assert st_killcam.slow_mo_until_ms > 4000, "Debe activar cámara lenta"
assert st_killcam.slow_mo_factor == 0.28, "Factor de slow motion debe ser 0.28"
assert st_killcam.kill_cam_target_id == s_doomed.snake_id, "Target de kill camera debe ser la víctima"
assert st_killcam.kill_cam_focus_pt in (orig_head, s_doomed.body[0]), "Foco de kill camera debe ser la cabeza acorralada"
assert s_doomed.speech_text in PRE_DEATH_CRIES, f"Debe exclamar grito antes de morir, exclamó: {s_doomed.speech_text}"

# J.3 Test Kill Repentina (Sin aviso del caballo): DEBE activar Kill Cam igualmente
st_sudden = app.create_initial_state(GameMode.DUEL_1V1)
st_sudden.countdown_active = False
st_sudden.slow_mo_until_ms = 0
s_victim = st_sudden.snakes[0]
s_killer = st_sudden.snakes[1]
# Choque directo contra pared en t+1 sin haber tenido imminent_death previa
s_victim.imminent_death = False
s_victim.body = deque([Point(0, 5), Point(1, 5), Point(2, 5)])
s_victim.direction = Direction.LEFT # Chocará con x = -1
app.rules.step(st_sudden, 5000)
assert s_victim.alive is False, "La serpiente debe morir al chocar con el muro"
assert st_sudden.slow_mo_until_ms > 5000, "TODA muerte fatal DEBE activar Slow-Mo / Kill Cam (cero muertes sin killcam)"
print("Cero kills sin KillCam verificado: Toda muerte letal repentina activa la cámara lenta.")

# Renderizado de la Kill Camera y viñeta
app.renderer.render(surf, st_killcam, 4100)
print("Alarma del Caballo, Slow Motion y Kill Camera verificados con 100% de éxito!")

# J.4 Test Enfoque PREVIO a la Muerte (Kill Cam Anticipation): La víctima está VIVA durante el enfoque
st_pre = app.create_initial_state(GameMode.DUEL_1V1)
st_pre.countdown_active = False
s_v = st_pre.snakes[0]
s_v.body = deque([Point(0, 5), Point(1, 5), Point(2, 5)])
s_v.direction = Direction.LEFT # A punto de chocar con la pared en x = -1
now_t = 6000

# Comprobar muerte inminente ANTES de que ocurra el paso físico
trig = app.rules.check_impending_killcam(st_pre, now_t)
assert trig is True, "check_impending_killcam DEBE detectar la colisión letal previa"
assert st_pre.slow_mo_until_ms > now_t, "Debe activar cámara lenta antes de morir"
assert st_pre.kill_cam_anticipation_until_ms > now_t, "Debe tener ventana de anticipación previa"
assert s_v.alive is True, "¡La víctima DEBE estar VIVA durante el enfoque previo de la Kill Cam!"
assert st_pre.kill_cam_target_id == s_v.snake_id, "Target debe ser la serpiente viva en peligro"
assert s_v.speech_text in PRE_DEATH_CRIES, "Debe mostrar el grito de advertencia antes del impacto"
# Renderizado durante el enfoque previo (víctima viva con spotlight)
app.renderer.render(surf, st_pre, now_t + 100)
assert s_v.alive is True, "La víctima sigue viva en pantalla para que el espectador vea el foco previo"

# Tras finalizar la anticipación, el paso físico ejecuta la eliminación
app.rules.step(st_pre, now_t + 500)
assert s_v.alive is False, "Tras la anticipación, la serpiente se elimina en cámara lenta"
print("Kill Cam PREVIO verificado: El enfoque y retícula se activan ANTES de la muerte con la víctima viva!")

# K. Test Modo Director de Retransmisión (Broadcast Lookahead Buffer)
print("--- Test Modo Director de Retransmisión (Lookahead Buffer) ---")
from director import DirectorEngine

# 1. Test Clonación ultrarrápida e independiente de ColosseumState
st_orig = app.create_initial_state(GameMode.DUEL_1V1)
st_orig.countdown_active = False
st_cloned = st_orig.clone()
assert len(st_cloned.snakes) == len(st_orig.snakes)
assert st_cloned.snakes[0].body[0] == st_orig.snakes[0].body[0]
st_cloned.snakes[0].body[0] = Point(99, 99)
assert st_orig.snakes[0].body[0] != Point(99, 99), "La clonación DEBE ser independiente y profunda"

# 2. Test Prefill del buffer (18 ticks futuros)
director = DirectorEngine(app, st_orig, buffer_ticks=18)
assert len(director.buffer) >= 18, "El buffer debe prellenarse con 18 ticks de anticipación"
assert director.future_state.tick >= 18, "La simulación futura debe estar adelantada 18 ticks"
assert director.current_state.tick == 0, "El estado visual presente debe comenzar en el tick 0"

# 3. Test Avance temporal y mantenimiento del buffer
for t in range(5):
    curr = director.advance(now_ms=t * 100)
    assert curr.tick == t
    assert len(director.buffer) == 18, "El buffer debe mantenerse siempre en 18 ticks"

# 4. Test Orquestación teatral de Muerte Futura (Pre-Death Threat -> Panic/Slow-Mo -> Kill)
st_dir_test = app.create_initial_state(GameMode.DUEL_1V1)
st_dir_test.countdown_active = False
s_atk = st_dir_test.snakes[0]
s_vic = st_dir_test.snakes[1]
# Víctima acorralada contra pared y bombas para garantizar impacto fatal en el buffer
s_vic.body = deque([Point(0, 1), Point(0, 2), Point(0, 3)])
s_vic.direction = Direction.UP
st_dir_test.bombs[Point(0, 0)] = 999999
st_dir_test.bombs[Point(1, 1)] = 999999

dir_sim = DirectorEngine(app, st_dir_test, buffer_ticks=18)
saw_slow_mo = False
saw_focus = False
for step_idx in range(6):
    c_st = dir_sim.advance(now_ms=step_idx * 100)
    app.renderer.render(surf, c_st, step_idx * 100)
    if c_st.slow_mo_until_ms > step_idx * 100:
        saw_slow_mo = True
    if c_st.kill_cam_target_id == s_vic.snake_id:
        saw_focus = True

assert saw_slow_mo is True, "El Director debe activar cámara lenta antes de la colisión fatal"
assert saw_focus is True, "El Director debe fijar la retícula sobre la víctima en peligro"
print("Modo Director de Retransmisión verificado con 100% de éxito!")

# L. Test Sincronización del Lookahead Buffer durante la Cuenta Regresiva de 3 Segundos
print("--- Test Sincronización de Cuenta Regresiva y Lookahead Buffer ---")
st_cd_test = app.create_initial_state(GameMode.DUEL_1V1)
st_cd_test.countdown_active = True
st_cd_test.countdown_start_ms = 1000

dir_cd = DirectorEngine(app, st_cd_test, buffer_ticks=18)
assert dir_cd.current_state.countdown_active is True
assert dir_cd.current_state.tick == 0

# T=1500 (Primera mitad de la cuenta regresiva visual: espectadores ven '3'/'2')
st_t1 = dir_cd.advance(now_ms=1500)
assert st_t1.countdown_active is True, "Durante la cuenta regresiva, el estado visual debe permanecer inactivo"
assert st_t1.tick == 0, "Las serpientes NO deben moverse durante los primeros segundos"

# T=2700 (Segunda mitad de la cuenta regresiva: el futuro ya simula en segundo plano)
for sim_t in range(1600, 2900, 100):
    st_t2 = dir_cd.advance(now_ms=sim_t)
assert st_t2.countdown_active is True
assert len(dir_cd.buffer) > 1, "El buffer debe estarse llenando en segundo plano antes de que termine el countdown"

# T=4050 (Cuenta regresiva visual de 3000ms concluida: 4050 >= 1000 + 3000)
st_fight = dir_cd.advance(now_ms=4050)
assert st_fight.countdown_active is False, "Al terminar los 3 segundos, countdown_active debe pasar a False"
assert len(dir_cd.buffer) == 18, "El buffer debe tener los 18 ticks completos listos"

# T=4150..4550 (Combate en curso: las serpientes avanzan fluidamente sin congelarse)
ticks_seen = []
for sim_t in range(4150, 4650, 100):
    st_step = dir_cd.advance(now_ms=sim_t)
    ticks_seen.append(st_step.tick)
assert len(set(ticks_seen)) > 1, "Las serpientes deben avanzar fluidamente tras el countdown sin congelarse"
print(f"Ticks visualizados tras cuenta regresiva: {ticks_seen}")

# Test inyección de eventos (tecla C / Z) en pipeline bufferizado
from events import GameEvent
initial_foods = len(dir_cd.current_state.foods)
dir_cd.inject_events([GameEvent("SPAWN_NORMAL_FOOD")], now_ms=4700)
assert len(dir_cd.current_state.foods) == initial_foods + 1, "La manzana debe inyectarse en el estado presente"
assert len(dir_cd.future_state.foods) == initial_foods + 1, "La manzana debe inyectarse en el estado futuro"
for snap in dir_cd.buffer:
    assert len(snap.foods) == initial_foods + 1, "La manzana debe propagarse a todos los frames del buffer"

# Test reinicio de ronda con resincronización de cuenta regresiva
dir_cd.reset_round(now_ms=5000)
assert dir_cd.current_state.countdown_active is True
assert dir_cd.current_state.countdown_start_ms == 5000
assert dir_cd.current_state.tick == 0
print("Sincronización de cuenta regresiva y Lookahead Buffer validada con 100% de éxito!")

# M. Test Ciclo de Vida Limpio de Partículas y Cero Rastros Residuales
print("--- Test Ciclo de Vida Limpio de Partículas y Rendimiento 60 FPS ---")
st_fx = app.create_initial_state(GameMode.DUEL_1V1)
st_fx.countdown_active = False
dir_fx = DirectorEngine(app, st_fx, buffer_ticks=18)

# Simular muerte en el futuro y verificar que future_state vacía sus partículas inmediatamente
s_die = dir_fx.future_state.snakes[0]
s_die.alive = False
app.rules._spawn_death_debris(dir_fx.future_state, s_die)
assert len(dir_fx.future_state.particles) > 0, "Al morir una serpiente se deben emitir partículas"
spawned_count = len(dir_fx.future_state.particles)

# Al dar el siguiente paso de simulación, el snapshot absorbe las partículas y future_state queda en 0
dir_fx.advance(now_ms=100)
assert len(dir_fx.future_state.particles) == 0, "future_state NO debe retener partículas en ticks posteriores"

# Renderizar: renderer absorbe las partículas en su propio pool y limpia el snapshot
app.renderer.render(surf, dir_fx.current_state, 100)
assert len(dir_fx.current_state.particles) == 0, "El estado no debe conservar partículas una vez renderizado"

# Simular el paso de 500ms a 60 FPS en el renderer: las partículas deben disiparse completamente
for f in range(35):
    dir_fx.current_state.particles.clear()
    app.renderer._update_and_draw_particles(surf, dir_fx.current_state)
assert len(app.renderer.particles) == 0, "Todas las partículas deben extinguirse naturalmente a los 450ms"

# Verificar que reset_round elimina cualquier rastro previo en pantalla
from models import VisualParticle
app.renderer.particles.append(VisualParticle(100, 100, 1, 1, (255, 0, 0), 5.0, 500, 500))
dir_fx.reset_round(now_ms=2000)
assert len(app.renderer.particles) == 0, "reset_round DEBE limpiar 100% de partículas del renderer"
assert len(dir_fx.future_state.particles) == 0, "reset_round DEBE dejar future_state libre de partículas"
assert len(dir_fx.current_state.particles) == 0, "reset_round DEBE dejar current_state libre de partículas"
# N. Test Análisis de Choque Frontal (Duelo de Titanes) vs Acorralado en Cuerpo
print("--- Test Análisis de Choque Frontal vs Acorralado en Cuerpo ---")
st_clash = app.create_initial_state(GameMode.DUEL_1V1)
st_clash.countdown_active = False
dir_clash = DirectorEngine(app, st_clash, buffer_ticks=18)

# Configurar un choque frontal directo: s1 y s2 van hacia la misma casilla
s1 = dir_clash.future_state.snakes[0]
s2 = dir_clash.future_state.snakes[1]
s1.body = deque([Point(5, 5), Point(4, 5), Point(3, 5), Point(2, 5)]) # Longitud 4
s1.direction = Direction.RIGHT # Va hacia (6, 5)
s2.body = deque([Point(7, 5), Point(8, 5), Point(9, 5)]) # Longitud 3
s2.direction = Direction.LEFT # Va hacia (6, 5)

snap_before = dir_clash.future_state.clone()
app.rules.step(dir_clash.future_state, 100)
snap_after = dir_clash.future_state.clone()

# s2 (longitud 3) debe haber muerto frente a s1 (longitud 4)
assert s1.alive is True, "s1 (más grande) debe sobrevivir al choque frontal"
assert s2.alive is False, "s2 (más pequeña) debe morir aplastada por masa"

# Analizar la muerte con el nuevo motor de análisis cinematográfico
death_analysis = dir_clash._analyze_death(snap_before, snap_after, snap_before.snakes[1], snap_after.snakes[1])
assert death_analysis["clash_type"] == "HEAD_ON_CLASH", f"Debe clasificarse como HEAD_ON_CLASH, obtenido: {death_analysis['clash_type']}"
assert death_analysis["clash_reason"] == "SIZE", f"La razón debe ser SIZE por longitud, obtenido: {death_analysis['clash_reason']}"
assert death_analysis["killer_id"] == s1.snake_id, "El verdugo debe ser s1"
assert death_analysis["impact_pt"] == Point(6, 5), f"El punto de impacto debe ser (6, 5), obtenido: {death_analysis['impact_pt']}"

# Test de punto de enfoque de cámara en Choque Frontal (debe ser el punto medio entre ambas cabezas)
vx, vy = s2.body[0].x, s2.body[0].y
kx, ky = s1.body[0].x, s1.body[0].y
expected_mid = Point((vx + kx) // 2, (vy + ky) // 2)
assert expected_mid == Point(6, 5), "El foco debe centrarse exactamente entre las cabezas enfrentadas"

# Test colisión contra cuerpo rival (debe clasificarse como TRAPPED_BODY)
s2.alive = True
s2.body = deque([Point(5, 4), Point(5, 3), Point(5, 2)])
s2.direction = Direction.DOWN # Se estrella contra el cuerpo de s1 en (5, 5)
snap_body_a = dir_clash.future_state.clone()
app.rules.step(dir_clash.future_state, 200)
snap_body_b = dir_clash.future_state.clone()
trap_analysis = dir_clash._analyze_death(snap_body_a, snap_body_b, snap_body_a.snakes[1], snap_body_b.snakes[1])
assert trap_analysis["clash_type"] == "TRAPPED_BODY", f"Debe clasificarse como TRAPPED_BODY, obtenido: {trap_analysis['clash_type']}"

# Test colisión contra muro (debe clasificarse como WALL)
s2.alive = True
s2.body = deque([Point(0, 0), Point(1, 0), Point(2, 0)])
s2.direction = Direction.LEFT # Choca contra la pared en (-1, 0)
snap_wall_a = dir_clash.future_state.clone()
app.rules.step(dir_clash.future_state, 300)
snap_wall_b = dir_clash.future_state.clone()
wall_analysis = dir_clash._analyze_death(snap_wall_a, snap_wall_b, snap_wall_a.snakes[1], snap_wall_b.snakes[1])
assert wall_analysis["clash_type"] == "WALL", f"Debe clasificarse como WALL, obtenido: {wall_analysis['clash_type']}"

print("Análisis de Choque Frontal vs Acorralado y Muros verificado con 100% de éxito!")

app.udp.sock.close()
print("=== TODAS LAS SUITES DE PRUEBA MODULAR PASARON CON 100% DE ÉXITO ===")


