# ============================================================
# models.py — Estructuras de Datos, Entidades y Geometría
# ============================================================

from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from typing import Tuple, List, Dict, Optional, Deque, Any
import math
from config import GRID_SIZE, CELL_PX, INITIAL_FPS, INITIAL_SNAKE_LENGTH

# ============================================================
# Enumeraciones Principales
# ============================================================

class GameMode(Enum):
    BATTLE_ROYALE = "BATTLE_ROYALE" # 2 a 5 Serpientes personalizables
    DUEL_1V1 = "DUEL_1V1"           # Duelo directo Fénix vs Cobra
    HYPNOTIC = "HYPNOTIC"           # Espectáculo fluido de patrones zen
    SPEEDRUN = "SPEEDRUN"           # Caza voraz de alta velocidad (1P)

class FactionId(Enum):
    RED = "RED"       # Fénix Carmesí (#Rojo)
    GREEN = "GREEN"   # Cobra Esmeralda (#Verde)
    BLUE = "BLUE"     # Dragón Zafiro (#Azul)
    PURPLE = "PURPLE" # Víbora Amatista (#Morado)
    GOLD = "GOLD"     # Basilisco Ámbar (#Dorado)

class SnakeMode(Enum):
    NORMAL = "NORMAL"
    EXTASIS = "EXTASIS"
    GOLDEN = "GOLDEN"

# ============================================================
# Dominio Espacial y Geometría
# ============================================================

@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int

class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    @property
    def dx(self) -> int: return self.value[0]
    @property
    def dy(self) -> int: return self.value[1]

DIRS: Tuple[Direction, ...] = (Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT)

def in_bounds(p: Point, n: int) -> bool:
    return 0 <= p.x < n and 0 <= p.y < n

def wrap(p: Point, n: int) -> Point:
    return Point(p.x % n, p.y % n)

def manhattan_plane(a: Point, b: Point) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)

def manhattan_toroidal(a: Point, b: Point, n: int) -> int:
    dx = abs(a.x - b.x)
    dy = abs(a.y - b.y)
    return min(dx, n - dx) + min(dy, n - dy)

def dist_for_config(a: Point, b: Point, wall_col: bool, n: int) -> int:
    return manhattan_plane(a, b) if wall_col else manhattan_toroidal(a, b, n)

def layer_index(p: Point, n: int) -> int:
    return min(p.x, p.y, n - 1 - p.x, n - 1 - p.y)

def dir_from_to(a: Point, b: Point) -> Direction:
    dx, dy = b.x - a.x, b.y - a.y
    if dx == 1 and dy == 0: return Direction.RIGHT
    if dx == -1 and dy == 0: return Direction.LEFT
    if dx == 0 and dy == 1: return Direction.DOWN
    return Direction.UP

# ============================================================
# Entidades de Juego: Comida, Facciones y Partículas
# ============================================================

@dataclass(slots=True)
class Food:
    pos: Point
    value: int = 1
    golden: bool = True  # True: Manzana Dorada (respawnable); False: Manzana Normal (consumible no respawnable)

@dataclass
class FactionConfig:
    faction_id: FactionId
    name: str
    tag: str
    head_color: Tuple[int, int, int]
    body_color: Tuple[int, int, int]
    personality_title: str
    pattern_weight: float
    food_weight: float
    risk_tolerance: float
    tail_avoid_factor: float
    preferred_center_layer: bool = False

# Configuraciones evolutivas tras simulación de 7 horas
FACTION_CONFIGS: Dict[FactionId, FactionConfig] = {
    FactionId.RED: FactionConfig(
        faction_id=FactionId.RED,
        name="Fénix Carmesí",
        tag="#Rojo",
        head_color=(255, 80, 80),
        body_color=(215, 40, 45),
        personality_title="Voraz",
        pattern_weight=0.17,
        food_weight=2.71,
        risk_tolerance=0.85,
        tail_avoid_factor=1.46
    ),
    FactionId.GREEN: FactionConfig(
        faction_id=FactionId.GREEN,
        name="Cobra Esmeralda",
        tag="#Verde",
        head_color=(90, 240, 130),
        body_color=(45, 180, 90),
        personality_title="Zen",
        pattern_weight=1.40,
        food_weight=1.20,
        risk_tolerance=0.05,
        tail_avoid_factor=2.45
    ),
    FactionId.BLUE: FactionConfig(
        faction_id=FactionId.BLUE,
        name="Dragón Zafiro",
        tag="#Azul",
        head_color=(95, 195, 255),
        body_color=(45, 130, 230),
        personality_title="Territorial",
        pattern_weight=0.80,
        food_weight=0.60,
        risk_tolerance=0.30,
        tail_avoid_factor=1.56,
        preferred_center_layer=True
    ),
    FactionId.PURPLE: FactionConfig(
        faction_id=FactionId.PURPLE,
        name="Víbora Amatista",
        tag="#Morado",
        head_color=(220, 135, 255),
        body_color=(165, 70, 225),
        personality_title="Mística",
        pattern_weight=1.25,
        food_weight=1.02,
        risk_tolerance=0.60,
        tail_avoid_factor=0.55
    ),
    FactionId.GOLD: FactionConfig(
        faction_id=FactionId.GOLD,
        name="Basilisco Ámbar",
        tag="#Dorado",
        head_color=(255, 215, 60),
        body_color=(218, 165, 32),
        personality_title="Táctico",
        pattern_weight=1.10,
        food_weight=1.20,
        risk_tolerance=0.40,
        tail_avoid_factor=1.80,
        preferred_center_layer=True
    )
}

FACTION_TACTICAL_DESCS: Dict[FactionId, str] = {
    FactionId.RED: "Caza voraz de comida a máxima velocidad y presión frontal.",
    FactionId.GREEN: "Supervivencia zen: evasión geométrica perimetral y cero riesgo.",
    FactionId.BLUE: "Control territorial en espirales concéntricas y asfixia interna.",
    FactionId.PURPLE: "Víbora mística: patrones impredecibles, zigzag y riesgo audaz.",
    FactionId.GOLD: "Depredador táctico: emboscadas, centro y trampas de doble olla."
}

# Diálogos Temáticos de Personalidad por Facción (Ataque y Maniobras)
FACTION_OFFENSIVE_PHRASES: Dict[FactionId, List[str]] = {
    FactionId.RED: [
        "¡No escaparás de mi olla! 😈",
        "¡Caíste en la trampa! 🔥",
        "¡Huelo tu miedo! 🦅",
        "¡A la carga sin piedad! ⚔️"
    ],
    FactionId.GREEN: [
        "Paciencia y respiración... 🧘",
        "El bambú se dobla, no se quiebra 🎋",
        "Tu propia prisa será tu fin 🍃",
        "Fluyendo alrededor del caos ☯️"
    ],
    FactionId.BLUE: [
        "¡Mi territorio, mis reglas! 🐉",
        "El cerco se cierra sobre ti 🌊",
        "Asfixia calculada milimétricamente ❄️",
        "No hay escape de mi dominio 🏰"
    ],
    FactionId.PURPLE: [
        "¿Predecible? Jamás 🌀",
        "Los dados del destino ya rodaron 🔮",
        "Danza mística activada ✨",
        "Un toque de veneno ilusorio 👁️"
    ],
    FactionId.GOLD: [
        "Trampa de doble tenaza ejecutada 🎯",
        "Jaque mate en 3 movimientos ♟️",
        "Todo marcha según mi cálculo 👑",
        "Emboscada de oro perfecta 🏹"
    ]
}

# Diálogos Temáticos de Victoria / Eliminación de Rivales
FACTION_KILL_PHRASES: Dict[FactionId, List[str]] = {
    FactionId.RED: [
        "¡Uno menos! ¡A cenar! 💥",
        "¡Demasiado lento para el Fénix! 🦅",
        "¡Aplaste total! 🔥"
    ],
    FactionId.GREEN: [
        "El caos se destruye a sí mismo 🌿",
        "Paz restablecida en el tablero 🕊️",
        "La armonía prevalece 🍵"
    ],
    FactionId.BLUE: [
        "Coto de caza despejado 🐉",
        "Asfixiado por el dominio Zafiro 🌊",
        "Nadie desafía mi perímetro 🛡️"
    ],
    FactionId.PURPLE: [
        "Desvanecido en la niebla amatista 🔮",
        "Un truco de magia fatal 🎩",
        "Destino cumplido ✨"
    ],
    FactionId.GOLD: [
        "Ejecución táctica impecable ♟️",
        "Eliminación de alta precisión 🎯",
        "La realeza no perdona errores 👑"
    ]
}

# Frases de Alivio Inmediato al Consumir Comida tras Hambre
FOOD_RELIEF_PHRASES: List[str] = [
    "¡Por finnnnnn! 🤤",
    "¡Estamos salvados! 🙏",
    "¡Con esta aguanto unas vueltas más! 😎",
    "¡Ufff, qué delicia! 🍎",
    "¡Revivió el gladiador! ✨",
    "¡Energía recargada! ⚡"
]

# Frases de Hambre Escalonadas (Solo en momentos de verdadera inanición)
HUNGER_TIER1_PHRASES: List[str] = [
    "¡El estómago me ruge... 🦁!",
    "¿Alguien vio una manzana? 👀",
    "¡Modo espagueti activado 🍝!",
    "¡Una manzanita por piedad! 🍎",
    "¿Esto era un juego de comer, no? 🤔"
]

HUNGER_TIER2_PHRASES: List[str] = [
    "¡Ayudaaaaaaaaaa! 😭",
    "¡Me muero de hambreeee! 🍖",
    "¡Socorro, me estoy desvaneciendo! 😵",
    "¡Si no como ahora, me como mi cola! 😱",
    "¡Por favor, una manzana de caridad! 🥺"
]

# Gritos Dramáticos de Muerte Inminente (Alarma del Caballo)
PRE_DEATH_CRIES: List[str] = [
    "¡Fue un honor... 💀!",
    "¡Noooo, acorralado! 😱",
    "¡Maldición, no hay salida! ⚡",
    "¡Me atrapaste...! 💥",
    "¡Hasta aquí llegué! 🕊️",
    "¡Adiós, mundo cruel! 🥀"
]

# Diálogos Específicos para Choque Frontal de Cabezas (Duelo de Titanes)
HEAD_ON_CLASH_CHALLENGES: List[str] = [
    "¡Duelo de cabezas! 💥",
    "¡Prepárate pal choque! ⚡",
    "¡Mi masa te aplastará! ⚔️",
    "¡Abran paso que no freno! 🔥",
    "¡A ver quién tiene más peso! 💣"
]

HEAD_ON_CLASH_PANIC: List[str] = [
    "¡Demasiada masa enfrente! 😱",
    "¡Impacto frontal inminente! 🚨",
    "¡No puedo esquivar! 💥",
    "¡Frenos rotos, vamos a chocar! 💥",
    "¡Socorro, es gigantesco! 💀"
]

HEAD_ON_CRUSH_VICTORY: List[str] = [
    "¡Masa superior! ¡Aplastado! 💪",
    "¡Te pasé por encima! 💥",
    "¡El más grande manda! 👑",
    "¡Pura potencia y tonelaje! ⚡"
]

WALL_CRASH_PANIC: List[str] = [
    "¡La pared está encima! 🧱",
    "¡No giran los frenos! 🚨",
    "¡Impacto contra el muro! 💥"
]

@dataclass
class VisualParticle:
    x: float
    y: float
    vx: float
    vy: float
    color: Tuple[int, int, int]
    radius: float
    life_ms: int
    max_life_ms: int

@dataclass
class NuclearStrike:
    center: Point
    state: str = "FALLING"  # FALLING -> IMPACT_FLASH -> SHOCKWAVE -> FINISHED
    start_ms: int = 0
    impact_ms: int = 0
    fall_y: float = -140.0
    blast_radius: int = 5
    fall_duration_ms: int = 900
    affected_cells: Dict[Point, Tuple[str, int]] = field(default_factory=dict)
    radius: float = 0.0

@dataclass
class ColosseumMatchSetup:
    grid_size: int = 22
    factions: List[FactionId] = field(default_factory=lambda: [FactionId.RED, FactionId.GREEN, FactionId.BLUE, FactionId.PURPLE])

@dataclass
class ColosseumSnake:
    snake_id: int
    faction: FactionConfig
    body: Deque[Point]
    direction: Direction
    alive: bool = True
    score: int = 0
    wins: int = 0
    grow_pending: int = 0
    mode: SnakeMode = SnakeMode.NORMAL
    mode_until_ms: int = 0
    
    # Expresiones y animaciones
    blink_timer: int = 0
    tongue_timer: int = 0
    head_history: Deque[Point] = field(default_factory=lambda: deque(maxlen=160))
    cycle_penalty_until: int = 0
    pattern_idx: int = 0
    last_switch_tick: int = 0
    hunger_ticks: int = 0       # Ticks transcurridos desde la última manzana comida
    speech_text: Optional[str] = None     # Frase cómica de globo de diálogo
    speech_until_ms: int = 0              # Expiración del globo de diálogo
    imminent_death: bool = False          # El caballo detectó muerte inevitable sin movimientos seguros
    last_speech_tick: int = 0

    def clone(self) -> 'ColosseumSnake':
        return ColosseumSnake(
            snake_id=self.snake_id,
            faction=self.faction,
            body=deque(self.body),
            direction=self.direction,
            alive=self.alive,
            score=self.score,
            wins=self.wins,
            grow_pending=self.grow_pending,
            mode=self.mode,
            mode_until_ms=self.mode_until_ms,
            blink_timer=self.blink_timer,
            tongue_timer=self.tongue_timer,
            head_history=deque(self.head_history, maxlen=160),
            cycle_penalty_until=self.cycle_penalty_until,
            pattern_idx=self.pattern_idx,
            last_switch_tick=self.last_switch_tick,
            hunger_ticks=self.hunger_ticks,
            speech_text=self.speech_text,
            speech_until_ms=self.speech_until_ms,
            imminent_death=self.imminent_death,
            last_speech_tick=self.last_speech_tick
        )

@dataclass
class ColosseumState:
    game_mode: GameMode
    snakes: List[ColosseumSnake]
    foods: List[Food]
    bombs: Dict[Point, int]
    grid_size: int = GRID_SIZE
    cell_px: int = CELL_PX
    tick: int = 0
    round_number: int = 1
    round_winner: Optional[str] = None
    round_reset_ms: int = 0
    paused: bool = False
    
    wall_collision: bool = True
    wrap_mode_until_ms: int = 0
    
    fps_base: int = INITIAL_FPS
    last_donor: str = "Esperando Donación"
    last_udp_ms: int = 0
    particles: List[VisualParticle] = field(default_factory=list)
    nuclear: Optional[NuclearStrike] = None
    
    countdown_active: bool = True
    countdown_start_ms: int = 0

    # Dramatismo de Arena: Slow Motion y Kill Camera
    slow_mo_until_ms: int = 0
    slow_mo_factor: float = 1.0
    slow_mo_cooldown_until_ms: int = 0
    kill_cam_target_id: Optional[int] = None
    kill_cam_focus_pt: Optional[Point] = None
    kill_cam_victim_name: Optional[str] = None
    kill_cam_anticipation_until_ms: int = 0

    # Modo Director de Retransmisión (Broadcast Lookahead Buffer)
    director_banner_text: Optional[str] = None
    director_banner_until_ms: int = 0
    director_stage: str = "NORMAL"

    def clone(self) -> 'ColosseumState':
        nuke_copy = None
        if self.nuclear:
            nuke_copy = NuclearStrike(
                center=self.nuclear.center,
                state=self.nuclear.state,
                start_ms=self.nuclear.start_ms,
                impact_ms=self.nuclear.impact_ms,
                fall_y=self.nuclear.fall_y,
                blast_radius=self.nuclear.blast_radius,
                fall_duration_ms=self.nuclear.fall_duration_ms,
                affected_cells=dict(self.nuclear.affected_cells),
                radius=self.nuclear.radius
            )

        return ColosseumState(
            game_mode=self.game_mode,
            snakes=[s.clone() for s in self.snakes],
            foods=[Food(f.pos, f.value, getattr(f, "golden", True)) for f in self.foods],
            bombs=dict(self.bombs),
            grid_size=self.grid_size,
            cell_px=self.cell_px,
            tick=self.tick,
            round_number=self.round_number,
            round_winner=self.round_winner,
            round_reset_ms=self.round_reset_ms,
            paused=self.paused,
            wall_collision=self.wall_collision,
            wrap_mode_until_ms=self.wrap_mode_until_ms,
            fps_base=self.fps_base,
            last_donor=self.last_donor,
            last_udp_ms=self.last_udp_ms,
            particles=[VisualParticle(p.x, p.y, p.vx, p.vy, p.color, p.radius, p.life_ms, p.max_life_ms) for p in self.particles],
            nuclear=nuke_copy,
            countdown_active=self.countdown_active,
            countdown_start_ms=self.countdown_start_ms,
            slow_mo_until_ms=self.slow_mo_until_ms,
            slow_mo_factor=self.slow_mo_factor,
            slow_mo_cooldown_until_ms=self.slow_mo_cooldown_until_ms,
            kill_cam_target_id=self.kill_cam_target_id,
            kill_cam_focus_pt=self.kill_cam_focus_pt,
            kill_cam_victim_name=self.kill_cam_victim_name,
            kill_cam_anticipation_until_ms=self.kill_cam_anticipation_until_ms,
            director_banner_text=self.director_banner_text,
            director_banner_until_ms=self.director_banner_until_ms,
            director_stage=self.director_stage
        )

