# ============================================================
# config.py — Configuración Global y Parámetros del Coliseo
# ============================================================

GRID_SIZE = 22                  # Cuadrícula base (22x22 casillas)
CELL_PX = 28                    # 22 * 28 = 616 px de tablero base
MARGIN_PX = 16                  # 16 px de margen lateral -> 616 + 32 = 648 px ancho
HUD_HEIGHT = 56                 # Altura reservada para el HUD estricto superior

WINDOW_WIDTH = GRID_SIZE * CELL_PX + 2 * MARGIN_PX     # 648 px
WINDOW_HEIGHT = GRID_SIZE * CELL_PX + 2 * MARGIN_PX + HUD_HEIGHT  # 704 px

INITIAL_SNAKE_LENGTH = 5        # Longitud inicial de cada gladiador
INITIAL_FPS = 12                # Velocidad estándar de combate
BOMB_DURATION_MS = 5000         # Duración de mecha de bombas normales

UDP_HOST = "127.0.0.1"          # Host para recepción de eventos TikTok Live
UDP_PORT = 8765                 # Puerto UDP unificado

EXTASIS_DURATION_MS = 8_000     # Duración del Modo Éxtasis (2x velocidad, arcoíris)
GOLDEN_DURATION_MS = 6_000      # Duración del Modo Dorado (3x velocidad, invulnerable)
WRAP_EVENT_DURATION_MS = 7_000  # Duración del Modo Trascendente (sin paredes)
WRAP_SAFE_WARNING_MS = 1_500    # Margen de seguridad del Caballo antes de reactivar muros

# Paletas de Colores de Interfaz (Consolas Theme)
COLOR_BG = (12, 12, 16)
COLOR_PANEL_BG = (22, 23, 31)
COLOR_PANEL_BORDER = (55, 60, 75)
COLOR_GOLD = (255, 215, 80)
COLOR_GOLD_DARK = (215, 155, 25)
COLOR_TEXT_WHITE = (245, 245, 245)
COLOR_TEXT_MUTED = (160, 165, 180)
