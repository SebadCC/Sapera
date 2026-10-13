import os
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
pygame.init()

import importlib.util

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

print("--- Test 1.21.py ---")
m21 = load_module("mod_1_21", "1.21.py")
app21 = m21.App()
state21 = app21.new_game_state()
for tick in range(15):
    d = app21.bot.choose_direction(state21, app21.cfg, tick * 80)
    state21.direction = d
    app21.rules.step(state21, app21.cfg, tick * 80)
app21.udp.sock.close()
print("1.21.py ticks passed successfully!")

print("--- Test 1.22.py ---")
m22 = load_module("mod_1_22", "1.22.py")
app22 = m22.App()
state22 = app22.new_game_state()
for p_type in m22.PersonalityType:
    state22.personality = p_type
    for tick in range(5):
        d = app22.bot.choose_direction(state22, app22.cfg, tick * 80)
        state22.direction = d
        app22.rules.step(state22, app22.cfg, tick * 80)
app22.udp.sock.close()
print("1.22.py all personalities passed successfully!")

print("--- Test 2.0.py Ultimate ---")
m20 = load_module("mod_2_0", "2.0.py")
app20 = m20.ColosseumApp()

for mode in m20.GameMode:
    state20 = app20.create_initial_state(mode)
    state20.countdown_active = False # Saltear cuenta regresiva en test unitario
    for tick in range(20):
        app20.bot.decide_all(state20, tick * 80)
        app20.rules.step(state20, tick * 80)
    alive = sum(1 for s in state20.snakes if s.alive)
    print(f"2.0.py Mode [{mode.name}] passed! Snakes alive: {alive}/{len(state20.snakes)}")

print("--- Test ColosseumSetupScene UI & Transitions ---")
mode_scene = m20.ModeSelectScene(app20)
# Click en opcion 0 de ModeSelectScene
click_event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (200, 130)})
next_scene = mode_scene.handle([click_event])
assert isinstance(next_scene, m20.ColosseumSetupScene), f"Expected ColosseumSetupScene, got {type(next_scene)}"

setup_scene: m20.ColosseumSetupScene = next_scene
surf = pygame.Surface((648, 704))
setup_scene.render(surf, 0)
print("ColosseumSetupScene render passed!")

# Test seleccion de tamaño (32x32)
# Boton grid 2 (32x32): x = 34 + 2 * (136 + 12) = 330, y = 90
ev_grid = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (350, 100)})
setup_scene.handle([ev_grid])
assert setup_scene.selected_grid_idx == 2
assert setup_scene.grid_options[setup_scene.selected_grid_idx][0] == 32

# Test seleccion de contendientes (5 serpientes)
# Boton count 5: x = 34 + 3 * (136 + 12) = 478, y = 152
ev_cnt = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (500, 160)})
setup_scene.handle([ev_cnt])
assert setup_scene.selected_count == 5

# Test rotacion de faccion en slot 4 (Basilisco -> Fenix)
cur_f4 = setup_scene.slot_factions[4]
# Slot 4: by = 232 + 4 * 65 = 492, click flecha siguiente (x = 34 + 580 - 20 = 594, y = 506)
ev_slot = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (594, 506)})
setup_scene.handle([ev_slot])
assert setup_scene.slot_factions[4] != cur_f4

# Test volver con boton Volver
back_ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (30, 25)})
back_scene = setup_scene.handle([back_ev])
assert isinstance(back_scene, m20.ModeSelectScene)

# Test volver con tecla ESC
esc_ev = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_ESCAPE})
esc_scene = setup_scene.handle([esc_ev])
assert isinstance(esc_scene, m20.ModeSelectScene)

# Test iniciar partida desde SetupScene
ev_start = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (300, 595)})
play_scene = setup_scene.handle([ev_start])
assert isinstance(play_scene, m20.PlayScene), f"Expected PlayScene, got {type(play_scene)}"
assert play_scene.state.grid_size == 32
assert len(play_scene.state.snakes) == 5
print("ColosseumSetupScene interaction & launch passed!")

print("--- Test Custom Arenas & Gladiators Simulation ---")
test_configs = [
    (16, [m20.FactionId.RED, m20.FactionId.GREEN]),
    (16, [m20.FactionId.RED, m20.FactionId.GREEN, m20.FactionId.BLUE, m20.FactionId.PURPLE]),
    (22, [m20.FactionId.RED, m20.FactionId.GREEN, m20.FactionId.BLUE, m20.FactionId.PURPLE, m20.FactionId.GOLD]),
    (32, [m20.FactionId.RED, m20.FactionId.GREEN, m20.FactionId.BLUE, m20.FactionId.PURPLE, m20.FactionId.GOLD]),
    (48, [m20.FactionId.RED, m20.FactionId.GREEN, m20.FactionId.BLUE, m20.FactionId.PURPLE, m20.FactionId.GOLD]),
]

for g_size, f_list in test_configs:
    custom_setup = m20.ColosseumMatchSetup(grid_size=g_size, factions=f_list)
    state = app20.create_initial_state(m20.GameMode.BATTLE_ROYALE, setup=custom_setup)
    state.countdown_active = False
    assert state.grid_size == g_size
    assert len(state.snakes) == len(f_list)
    for tick in range(25):
        app20.bot.decide_all(state, tick * 80)
        app20.rules.step(state, tick * 80)
        app20.renderer.render(surf, state, tick * 80)
    alive_cnt = sum(1 for s in state.snakes if s.alive)
    print(f"Arena {g_size}x{g_size} with {len(f_list)} snakes passed! Alive: {alive_cnt}/{len(f_list)}")

app20.udp.sock.close()
print("=== ALL TEST SUITES PASSED ===")
