#!/usr/bin/env python3
"""
hive.py — 2D Bee Hive Simulation backend.

Provides a spatial simulation of a bee colony with:
  - A cell-based hive layout (food/brood cells, queen chamber, entrance)
  - Individual bees with position, movement, and multi-step tasks
  - Foragers that leave the hive, wait, and return with food
  - Construction that requires both delivered food and worker time
  - Fine-grained tick timing suitable for smooth visual rendering

Pure simulation logic and command handling — no UI dependencies.
Run directly (``python hive.py``) to launch the Tkinter frontend, or
import ``Hive`` / ``Simulator`` for headless use or testing.
"""

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple


# ============================================================================
# Grid Layout
# ============================================================================

GRID_WIDTH  = 40
GRID_HEIGHT = 25

QUEEN_START_POS    = (GRID_WIDTH // 2, GRID_HEIGHT // 2)
ENTRANCE_START_POS = (GRID_WIDTH // 2, GRID_HEIGHT - 1)

INITIAL_FOOD_CELL_OFFSETS:  List[Tuple[int, int]] = [(-3, 0), (3, 0)]
INITIAL_BROOD_CELL_OFFSETS: List[Tuple[int, int]] = [
    (-1, -2), (1, -2), (0, 2), (-2, 2), (2, 2),
]


class CellType(str, Enum):
    EMPTY       = 'empty'
    FOOD        = 'food'
    BROOD       = 'brood'
    QUEEN       = 'queen'
    ENTRANCE    = 'entrance'
    BUILD_FOOD  = 'build_food'
    BUILD_BROOD = 'build_brood'
    QUEEN_BROOD       = 'queen_brood'
    BUILD_QUEEN_BROOD = 'build_queen_brood'


# ============================================================================
# Cell Capacities
# ============================================================================

CELL_FOOD_CAPACITY  = 50   # food units stored per food cell
CELL_BROOD_CAPACITY = 8    # eggs + larvae per brood cell


# ============================================================================
# Timing — all durations are in ticks
# ============================================================================

# Life cycle
EGG_HATCH_TICKS  = 600
LARVA_GROW_TICKS = 800
WORKER_LIFESPAN  = 4000

# Queen
QUEEN_LAY_INTERVAL = 8
QUEEN_EAT_INTERVAL = 200

# Queen aging & succession
QUEEN_LIFESPAN           = 12000   # ticks until natural death
QUEEN_AGING_START        = 0.70    # fraction of lifespan when laying slows
QUEEN_AGING_LAY_SLOWDOWN = 4.0     # lay-interval multiplier at end of life
QUEEN_EGG_HATCH_TICKS    = EGG_HATCH_TICKS
QUEEN_LARVA_GROW_TICKS   = LARVA_GROW_TICKS * 2
QUEEN_LARVA_HUNGER_RATE  = 2       # 2x normal -> needs ~2x the food
QUEEN_BROOD_BUILDERS     = 2
QUEEN_LARVA_FEEDERS      = 1

# Hunger / feeding
BEE_EAT_INTERVAL            = 500
LARVA_FEED_HUNGER_THRESHOLD = 100
LARVA_STARVATION_THRESHOLD  = 600
WORKER_STARVATION_THRESHOLD = 600
WORKER_HUNGER_CRITICAL      = 400   # interrupt any task to go eat

# Foraging
FORAGE_TRIP_TICKS   = 300
FORAGE_DEATH_CHANCE = 0.08
FORAGE_FOOD_RETURN  = 10

# Construction
BUILD_WORK_TICKS        = 500    # cumulative work to finish a cell
BUILD_FOOD_REQUIRED     = 20     # food that must be deposited
ACTION_BUILD_STEP_TICKS = 10     # one work session at a build site

# Stationary (local) actions
ACTION_PICKUP_TICKS  = 10
ACTION_DEPOSIT_TICKS = 8
ACTION_FEED_TICKS    = 12

# Queen-death grace window: queen won't starve until this far past interval
QUEEN_STARVE_GRACE_MULTIPLIER = 2


# ============================================================================
# Movement
# ============================================================================

BEE_MOVE_SPEED_CELLS_PER_TICK = 0.15
BEE_IDLE_WANDER_THRESHOLD_SQ  = 2.0  # drift home if (dx^2+dy^2) exceeds this
QUEEN_MOVE_SPEED              = 0.08  # cells/tick the queen drifts toward brood
QUEEN_ATTENDANT_RANGE         = 1.0    # how close queen-feeders loiter


# ============================================================================
# Carrying
# ============================================================================

BEE_CARRY_CAPACITY      = 5  # generic internal carry
BEE_QUEEN_DELIVERY_LOAD = 1  # feeders of the queen fetch only 1 unit


# ============================================================================
# Starting State
# ============================================================================

STARTING_WORKERS = 20
STARTING_FOOD    = 100

INITIAL_SPAWN_RADIUS = 3.0


# ============================================================================
# Food Policy
# ============================================================================

QUEEN_FOOD_RESERVE = 15


# ============================================================================
# Auto-Allocation Tuning
# ============================================================================

MIN_FORAGERS                    = 3
MAX_BROOD_BUILDERS              = 3
MAX_FOOD_BUILDERS               = 2
FOOD_CRITICAL_MULTIPLIER        = 2
FOOD_LOW_MULTIPLIER             = 4
FOOD_GOOD_MINIMUM               = 80
FOOD_GOOD_CAPACITY_RATIO        = 0.4
FORAGER_SAFETY_FACTOR_LOW       = 2.0
FORAGER_SAFETY_FACTOR_NORMAL    = 1.5
BROOD_SPACE_BUFFER              = 6
FOOD_SPACE_EXPANSION_THRESHOLD  = 30
LARVA_FEEDERS_PER_LARVA_DIVISOR = 7


# ============================================================================
# Simulator Limits
# ============================================================================

MAX_TICK_RATE     = 60.0
MIN_TICK_RATE     = 0.0
DEFAULT_TICK_RATE = 15.0
MAX_LOG_ENTRIES   = 30


# ============================================================================
# Roles / Task Definitions
# ============================================================================

ROLE_NONE        = 'none'
ROLE_FEED_QUEEN  = 'feed_queen'
ROLE_FEED_LARVAE = 'feed_larvae'
ROLE_BUILD_FOOD  = 'build_food'
ROLE_BUILD_BROOD = 'build_brood'
ROLE_FORAGE      = 'forage'
ROLE_BUILD_QUEEN_BROOD = 'build_queen_brood'
ROLE_FEED_QUEEN_LARVA  = 'feed_queen_larva'

IN_HIVE_TASKS = [ROLE_FEED_QUEEN, ROLE_FEED_LARVAE, ROLE_FEED_QUEEN_LARVA,
                 ROLE_BUILD_FOOD, ROLE_BUILD_BROOD, ROLE_BUILD_QUEEN_BROOD]
ALL_TASKS     = IN_HIVE_TASKS + [ROLE_FORAGE]

TASK_ALIASES: Dict[str, str] = {
    'fq': ROLE_FEED_QUEEN,  'queen':  ROLE_FEED_QUEEN,
    'fl': ROLE_FEED_LARVAE, 'larvae': ROLE_FEED_LARVAE,
    'bf': ROLE_BUILD_FOOD,
    'bb': ROLE_BUILD_BROOD,
    'bq':  ROLE_BUILD_QUEEN_BROOD, 'queen_cell':  ROLE_BUILD_QUEEN_BROOD,
    'fql': ROLE_FEED_QUEEN_LARVA,  'queen_larva': ROLE_FEED_QUEEN_LARVA,
    'f':  ROLE_FORAGE,
}

DEFAULT_ALLOCATION: Dict[str, int] = {
    ROLE_FEED_QUEEN:  2,
    ROLE_FEED_LARVAE: 3,
    ROLE_BUILD_FOOD:  0,
    ROLE_BUILD_BROOD: 0,
    ROLE_BUILD_QUEEN_BROOD: 0,
    ROLE_FEED_QUEEN_LARVA:  0,
    ROLE_FORAGE:     16,
}


# ============================================================================
# Bee States & Sub-task Intents
# ============================================================================

class BeeState(str, Enum):
    IDLE    = 'idle'     # stationary, waiting for a task
    MOVING  = 'moving'   # travelling to target cell
    WORKING = 'working'  # stationary, performing an action
    OUTSIDE = 'outside'  # foraging away from the hive


# Intents describe the sub-task the bee is currently pursuing.
INTENT_NONE             = 'none'
INTENT_SELF_FEED        = 'self_feed'
INTENT_FETCH_FOOD_QUEEN = 'fetch_food_queen'
INTENT_DELIVER_QUEEN    = 'deliver_queen'
INTENT_FETCH_FOOD_LARVA = 'fetch_food_larva'
INTENT_DELIVER_LARVA    = 'deliver_larva'
INTENT_FETCH_FOOD_BUILD = 'fetch_food_build'
INTENT_DELIVER_BUILD    = 'deliver_build'
INTENT_WORK_BUILD       = 'work_build'
INTENT_GO_TO_ENTRANCE   = 'go_to_entrance'
INTENT_STORE_FORAGE     = 'store_forage'
INTENT_FETCH_FOOD_QLARVA = 'fetch_food_qlarva'
INTENT_DELIVER_QLARVA    = 'deliver_qlarva'


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class Egg:
    age: int = 0


@dataclass
class Larva:
    age: int = 0
    hunger: int = 0


@dataclass
class Cell:
    x: int
    y: int
    cell_type: CellType
    food: int = 0
    eggs:   List[Egg]   = field(default_factory=list)
    larvae: List[Larva] = field(default_factory=list)
    build_progress:  int = 0
    build_food_used: int = 0
    build_target: Optional[CellType] = None

    @property
    def pos(self) -> Tuple[int, int]:
        return (self.x, self.y)

    def brood_count(self) -> int:
        return len(self.eggs) + len(self.larvae)

    def brood_has_space(self) -> bool:
        return self.brood_count() < CELL_BROOD_CAPACITY

    def food_has_space(self) -> bool:
        return self.food < CELL_FOOD_CAPACITY


@dataclass
class Bee:
    x: float
    y: float
    age: int = 0
    hunger: int = 0
    role: str = ROLE_NONE
    state: BeeState = BeeState.IDLE
    intent: str = INTENT_NONE
    target_pos: Optional[Tuple[int, int]] = None
    action_timer: int = 0
    carrying: int = 0
    forage_timer: int = 0
    home_pos: Tuple[float, float] = (0.0, 0.0)

    @property
    def position(self) -> Tuple[float, float]:
        return (self.x, self.y)


# ============================================================================
# Exceptions
# ============================================================================

class SimulationCommandError(ValueError):
    """Raised when a user-entered command cannot be parsed or executed."""


# ============================================================================
# Hive Grid
# ============================================================================

class HiveGrid:
    """2D grid of cells representing the hive's internal structure."""

    def __init__(self, width: int = GRID_WIDTH, height: int = GRID_HEIGHT):
        self.width         = width
        self.height        = height
        self.cells: Dict[Tuple[int, int], Cell] = {}
        self.queen_pos     = QUEEN_START_POS
        self.entrance_pos  = ENTRANCE_START_POS
        self._build_initial_layout()

    # ── Setup ──────────────────────────────────────────────────────

    def _build_initial_layout(self):
        for x in range(self.width):
            for y in range(self.height):
                self.cells[(x, y)] = Cell(x, y, CellType.EMPTY)

        self._replace_cell(self.queen_pos,    CellType.QUEEN)
        self._replace_cell(self.entrance_pos, CellType.ENTRANCE)

        qx, qy = self.queen_pos
        food_per_cell = STARTING_FOOD // max(1, len(INITIAL_FOOD_CELL_OFFSETS))
        for dx, dy in INITIAL_FOOD_CELL_OFFSETS:
            pos = (qx + dx, qy + dy)
            if self.in_bounds(pos):
                self._replace_cell(pos, CellType.FOOD, food=food_per_cell)

        for dx, dy in INITIAL_BROOD_CELL_OFFSETS:
            pos = (qx + dx, qy + dy)
            if self.in_bounds(pos):
                self._replace_cell(pos, CellType.BROOD)

    def _replace_cell(self, pos: Tuple[int, int], cell_type: CellType, **kwargs):
        x, y = pos
        self.cells[pos] = Cell(x, y, cell_type, **kwargs)

    # ── Lookups ────────────────────────────────────────────────────

    def in_bounds(self, pos: Tuple[int, int]) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def cell_at(self, pos: Tuple[int, int]) -> Optional[Cell]:
        return self.cells.get(pos)

    @property
    def queen_cell(self) -> Cell:
        return self.cells[self.queen_pos]

    @property
    def entrance_cell(self) -> Cell:
        return self.cells[self.entrance_pos]

    def cells_of_type(self, *types: CellType) -> List[Cell]:
        type_set = set(types)
        return [c for c in self.cells.values() if c.cell_type in type_set]

    # ── Spatial queries ────────────────────────────────────────────

    def find_nearest(
        self,
        origin: Tuple[float, float],
        predicate: Callable[[Cell], bool],
    ) -> Optional[Cell]:
        best, best_d2 = None, float('inf')
        ox, oy = origin
        for cell in self.cells.values():
            if not predicate(cell):
                continue
            d2 = (cell.x - ox) ** 2 + (cell.y - oy) ** 2
            if d2 < best_d2:
                best_d2, best = d2, cell
        return best

    def nearest_food_source(self, origin) -> Optional[Cell]:
        return self.find_nearest(
            origin,
            lambda c: c.cell_type == CellType.FOOD and c.food > 0,
        )

    def nearest_food_storage_with_space(self, origin) -> Optional[Cell]:
        return self.find_nearest(
            origin,
            lambda c: c.cell_type == CellType.FOOD and c.food_has_space(),
        )

    def nearest_brood_with_hungry_larva(self, origin) -> Optional[Cell]:
        def pred(cell: Cell) -> bool:
            if cell.cell_type != CellType.BROOD:
                return False
            return any(
                larva.hunger >= LARVA_FEED_HUNGER_THRESHOLD
                for larva in cell.larvae
            )
        return self.find_nearest(origin, pred)

    def brood_cell_with_space(self) -> Optional[Cell]:
        for cell in self.cells_of_type(CellType.BROOD):
            if cell.brood_has_space():
                return cell
        return None

    _BUILD_TYPE_MAP = {
        CellType.FOOD:        CellType.BUILD_FOOD,
        CellType.BROOD:       CellType.BUILD_BROOD,
        CellType.QUEEN_BROOD: CellType.BUILD_QUEEN_BROOD,
    }

    def active_build_site(self, target_type: CellType) -> Optional[Cell]:
        build_type = self._BUILD_TYPE_MAP.get(target_type, CellType.BUILD_BROOD)
        sites = self.cells_of_type(build_type)
        return sites[0] if sites else None

    def queen_brood_cell(self) -> Optional[Cell]:
        cells = self.cells_of_type(CellType.QUEEN_BROOD)
        return cells[0] if cells else None

    def designate_build_site(self, target_type: CellType) -> Optional[Cell]:
        """Convert the nearest-to-queen empty cell into a construction site."""
        existing = self.active_build_site(target_type)
        if existing is not None:
            return existing
        if (target_type == CellType.QUEEN_BROOD
                and self.queen_brood_cell() is not None):
            return None  # only one queen cell at a time

        # Queen brood is always built in the central queen chamber.
        if target_type == CellType.QUEEN_BROOD:
            qcell = self.cells[self.queen_pos]
            if qcell.cell_type != CellType.QUEEN:
                return None
            qcell.cell_type       = CellType.BUILD_QUEEN_BROOD
            qcell.build_target    = target_type
            qcell.build_progress  = 0
            qcell.build_food_used = 0
            return qcell

        reserved = {self.queen_pos, self.entrance_pos}
        candidates = [c for c in self.cells_of_type(CellType.EMPTY)
                      if c.pos not in reserved]
        if not candidates:
            return None

        qx, qy = self.queen_pos
        candidates.sort(key=lambda c: (c.x - qx) ** 2 + (c.y - qy) ** 2)
        site = candidates[0]
        site.cell_type       = self._BUILD_TYPE_MAP.get(
            target_type, CellType.BUILD_BROOD)
        site.build_target    = target_type
        site.build_progress  = 0
        site.build_food_used = 0
        return site

    # ── Aggregates ─────────────────────────────────────────────────

    def total_food(self) -> int:
        return sum(c.food for c in self.cells_of_type(CellType.FOOD))

    def total_food_capacity(self) -> int:
        return CELL_FOOD_CAPACITY * len(self.cells_of_type(CellType.FOOD))

    def total_brood_capacity(self) -> int:
        return CELL_BROOD_CAPACITY * len(self.cells_of_type(CellType.BROOD))

    def total_brood_used(self) -> int:
        return sum(c.brood_count() for c in self.cells_of_type(CellType.BROOD))

    def total_eggs(self) -> int:
        return sum(len(c.eggs) for c in self.cells_of_type(CellType.BROOD))

    def total_larvae(self) -> int:
        return sum(len(c.larvae) for c in self.cells_of_type(CellType.BROOD))

    # ── Food operations ────────────────────────────────────────────

    def deposit_food_at(self, cell: Cell, amount: int) -> int:
        space = CELL_FOOD_CAPACITY - cell.food
        put = min(space, amount)
        cell.food += put
        return put

    def lay_egg(self) -> bool:
        cell = self.brood_cell_with_space()
        if cell is None:
            return False
        cell.eggs.append(Egg())
        return True


# ============================================================================
# Hive
# ============================================================================

class Hive:
    """Complete colony state with spatial simulation."""

    def __init__(self):
        self.tick_count: int = 0
        self.grid            = HiveGrid()

        self.queen_alive: bool    = True
        self.queen_hunger: int    = 0
        self.queen_lay_timer: int = 0
        self.queen_age: int       = 0

        # Succession state
        self.succession_started: bool = False
        self.queen_egg_laid:     bool = False
        self.old_queen: Optional[Dict[str, float]] = None  # {'x','y','hunger'}

        # Queen has a physical position and a target brood cell
        qx, qy = self.grid.queen_pos
        self.queen_x: float = float(qx)
        self.queen_y: float = float(qy)
        self.queen_target_cell: Optional[Tuple[int, int]] = None

        self.bees: List[Bee]           = self._spawn_initial_workers()
        self._dead_foragers: List[Bee] = []

        self.alloc: Dict[str, int] = dict(DEFAULT_ALLOCATION)
        self.log:   List[str]      = []

    def _spawn_initial_workers(self) -> List[Bee]:
        qx, qy = self.grid.queen_pos
        bees: List[Bee] = []
        for i in range(STARTING_WORKERS):
            angle = 2 * math.pi * i / STARTING_WORKERS
            dx, dy = math.cos(angle) * INITIAL_SPAWN_RADIUS, \
                     math.sin(angle) * INITIAL_SPAWN_RADIUS
            x, y = qx + dx, qy + dy
            bees.append(Bee(x=x, y=y, home_pos=(x, y)))
        return bees

    # ================================================================
    # Summary accessors (backwards-compatible with the old API)
    # ================================================================

    @property
    def food(self) -> int:               return self.grid.total_food()
    @property
    def food_blocks(self) -> int:        return len(self.grid.cells_of_type(CellType.FOOD))
    @property
    def brood_blocks(self) -> int:       return len(self.grid.cells_of_type(CellType.BROOD))

    def food_capacity(self) -> int:      return self.grid.total_food_capacity()
    def brood_capacity(self) -> int:     return self.grid.total_brood_capacity()
    def brood_used(self) -> int:         return self.grid.total_brood_used()
    def brood_space(self) -> int:        return self.brood_capacity() - self.brood_used()
    def food_space(self) -> int:         return self.food_capacity() - self.food

    @property
    def eggs(self) -> List[Egg]:
        return [e for c in self.grid.cells_of_type(CellType.BROOD) for e in c.eggs]

    @property
    def larvae(self) -> List[Larva]:
        return [l for c in self.grid.cells_of_type(CellType.BROOD) for l in c.larvae]

    @property
    def workers(self) -> List[Bee]:
        return [b for b in self.bees if b.state != BeeState.OUTSIDE]

    @property
    def foragers(self) -> List[Bee]:
        return [b for b in self.bees if b.state == BeeState.OUTSIDE]

    def total_workers(self) -> int:
        return len(self.bees)

    def idle_workers(self) -> int:
        return max(0, self.total_workers() - sum(self.alloc.values()))

    @property
    def build_progress(self) -> Dict[str, int]:
        out = {'food': 0, 'brood': 0, 'queen': 0}
        for label, target in (('food', CellType.FOOD), ('brood', CellType.BROOD),
                              ('queen', CellType.QUEEN_BROOD)):
            site = self.grid.active_build_site(target)
            if site is not None:
                out[label] = site.build_progress
        return out

    @property
    def build_food_used(self) -> Dict[str, int]:
        out = {'food': 0, 'brood': 0, 'queen': 0}
        for label, target in (('food', CellType.FOOD), ('brood', CellType.BROOD),
                              ('queen', CellType.QUEEN_BROOD)):
            site = self.grid.active_build_site(target)
            if site is not None:
                out[label] = site.build_food_used
        return out

    # ================================================================
    # Logging
    # ================================================================

    def _append_log(self, message: str):
        self.log.append(f"T{self.tick_count}: {message}")
        while len(self.log) > MAX_LOG_ENTRIES:
            self.log.pop(0)

    def _log_deaths(self, count: int, description: str):
        if count > 0:
            self._append_log(f"{count} {description}")

    def _log_block_completed(self, block_label: str):
        suffix = "cell" if block_label == "queen" else "storage block"
        self._append_log(f"{block_label.capitalize()} {suffix} completed")

    def _log_queen_death(self):
        self._append_log("*** THE QUEEN HAS STARVED ***")

    # ================================================================
    # Main tick
    # ================================================================

    def tick(self):
        self.tick_count += 1
        self._tick_queen()
        self._tick_old_queen()
        self._tick_brood()
        self._age_bees_and_cull()
        self._manage_succession()
        self._assign_roles()
        for bee in list(self.bees):
            self._update_bee(bee)
        self._remove_dead_foragers()
        self._check_starvation()

    # ----------------------------------------------------------------
    # Queen
    # ----------------------------------------------------------------

    def _effective_lay_interval(self) -> int:
        """Lay interval grows linearly once the queen passes QUEEN_AGING_START."""
        aging_at = QUEEN_LIFESPAN * QUEEN_AGING_START
        if self.queen_age < aging_at:
            return QUEEN_LAY_INTERVAL
        span = max(1.0, QUEEN_LIFESPAN - aging_at)
        frac = min(1.0, (self.queen_age - aging_at) / span)
        mult = 1.0 + (QUEEN_AGING_LAY_SLOWDOWN - 1.0) * frac
        return max(QUEEN_LAY_INTERVAL, int(round(QUEEN_LAY_INTERVAL * mult)))

    def _tick_queen(self):
        if not self.queen_alive:
            return
        self.queen_age       += 1
        self.queen_hunger    += 1
        self.queen_lay_timer += 1

        if self.queen_age >= QUEEN_LIFESPAN:
            self.queen_alive = False
            self._append_log("*** THE QUEEN HAS DIED OF OLD AGE ***")
            return

        lay_interval = self._effective_lay_interval()

        # Pick a destination: a built, empty queen cell takes absolute priority.
        if self.queen_target_cell is None:
            qcell = self.grid.queen_brood_cell()
            if (qcell is not None and not self.queen_egg_laid
                    and qcell.brood_count() == 0):
                self.queen_target_cell = qcell.pos
            else:
                brood = self.grid.brood_cell_with_space()
                if brood is not None:
                    self.queen_target_cell = brood.pos

        if self.queen_target_cell is not None:
            tx, ty = self.queen_target_cell
            dx = tx - self.queen_x
            dy = ty - self.queen_y
            dist = math.hypot(dx, dy)
            if dist <= QUEEN_MOVE_SPEED:
                self.queen_x = float(tx)
                self.queen_y = float(ty)
                if self.queen_lay_timer >= lay_interval:
                    self.queen_lay_timer = 0
                    cell = self.grid.cell_at(self.queen_target_cell)
                    if cell is not None:
                        if (cell.cell_type == CellType.QUEEN_BROOD
                                and cell.brood_count() == 0):
                            cell.eggs.append(Egg())
                            self.queen_egg_laid = True
                            self._append_log("Queen laid a successor egg")
                        elif (cell.cell_type == CellType.BROOD
                                and cell.brood_has_space()):
                            cell.eggs.append(Egg())
                    self.queen_target_cell = None
            else:
                self.queen_x += dx / dist * QUEEN_MOVE_SPEED
                self.queen_y += dy / dist * QUEEN_MOVE_SPEED
        elif self.queen_lay_timer >= lay_interval:
            self.queen_lay_timer = 0
            self.grid.lay_egg()

    def _tick_old_queen(self):
        """A superseded queen receives no care; she simply starves in place."""
        if self.old_queen is None:
            return
        self.old_queen['hunger'] += 1
        if self.old_queen['hunger'] > QUEEN_EAT_INTERVAL * QUEEN_STARVE_GRACE_MULTIPLIER:
            self._append_log("The old queen has died, abandoned by her attendants")
            self.old_queen = None

    # ----------------------------------------------------------------
    # Brood (eggs and larvae age in their cells)
    # ----------------------------------------------------------------

    def _tick_brood(self):
        matured_positions: List[Tuple[float, float]] = []
        for cell in self.grid.cells_of_type(CellType.BROOD):
            self._age_eggs_in_cell(cell)
            matured_positions.extend(self._age_larvae_in_cell(cell))
        for (mx, my) in matured_positions:
            self.bees.append(Bee(x=mx, y=my, home_pos=(mx, my)))
        self._tick_queen_brood()

    def _tick_queen_brood(self):
        cell = self.grid.queen_brood_cell()
        if cell is None:
            return
        # Egg -> larva
        remaining_eggs: List[Egg] = []
        for egg in cell.eggs:
            egg.age += 1
            if egg.age >= QUEEN_EGG_HATCH_TICKS:
                cell.larvae.append(Larva())
                self._append_log("Queen egg has hatched into a queen larva")
            else:
                remaining_eggs.append(egg)
        cell.eggs = remaining_eggs
        # Larva: 2x hunger rate, 2x development time
        remaining_larvae: List[Larva] = []
        for larva in cell.larvae:
            larva.age    += 1
            larva.hunger += QUEEN_LARVA_HUNGER_RATE
            if larva.hunger > LARVA_STARVATION_THRESHOLD:
                self._append_log("*** THE QUEEN LARVA HAS STARVED ***")
                self.queen_egg_laid = False  # allow another attempt
                continue
            if larva.age >= QUEEN_LARVA_GROW_TICKS:
                self._crown_new_queen(cell)
                return
            remaining_larvae.append(larva)
        cell.larvae = remaining_larvae

    def _crown_new_queen(self, cell: Cell):
        """A new queen emerges. If the old one still lives she is abandoned."""
        if self.queen_alive:
            self.old_queen = {
                'x': self.queen_x, 'y': self.queen_y,
                'hunger': float(self.queen_hunger),
            }
            self._append_log("A new queen has emerged; attendants abandon the old queen")
        else:
            self._append_log("A new queen has emerged")
        self.queen_alive       = True
        self.queen_x           = float(cell.x)
        self.queen_y           = float(cell.y)
        self.queen_hunger      = 0
        self.queen_age         = 0
        self.queen_lay_timer   = 0
        self.queen_target_cell = None
        # Single-use cell: revert to empty and reset succession.
        cell.eggs.clear()
        cell.larvae.clear()
        cell.cell_type = CellType.QUEEN
        self.succession_started = False
        self.queen_egg_laid     = False

    def _age_eggs_in_cell(self, cell: Cell):
        remaining: List[Egg] = []
        for egg in cell.eggs:
            egg.age += 1
            if egg.age >= EGG_HATCH_TICKS:
                cell.larvae.append(Larva())
            else:
                remaining.append(egg)
        cell.eggs = remaining

    def _age_larvae_in_cell(self, cell: Cell) -> List[Tuple[float, float]]:
        matured: List[Tuple[float, float]] = []
        remaining: List[Larva] = []
        for larva in cell.larvae:
            larva.age    += 1
            larva.hunger += 1
            if larva.age >= LARVA_GROW_TICKS:
                matured.append((float(cell.x), float(cell.y)))
            else:
                remaining.append(larva)
        cell.larvae = remaining
        return matured

    # ----------------------------------------------------------------
    # Aging & lifespan culling
    # ----------------------------------------------------------------

    def _age_bees_and_cull(self):
        survivors: List[Bee] = []
        for bee in self.bees:
            bee.age += 1
            if bee.state != BeeState.OUTSIDE:
                bee.hunger += 1  # outside bees feed themselves on the flowers
            if bee.age < WORKER_LIFESPAN:
                survivors.append(bee)
        self.bees = survivors

    # ----------------------------------------------------------------
    # Starvation
    # ----------------------------------------------------------------

    def _check_starvation(self):
        # Larvae
        starved_larvae = 0
        for cell in self.grid.cells_of_type(CellType.BROOD):
            before = len(cell.larvae)
            cell.larvae = [l for l in cell.larvae
                           if l.hunger <= LARVA_STARVATION_THRESHOLD]
            starved_larvae += before - len(cell.larvae)
        self._log_deaths(starved_larvae, "larva(e) starved")

        # Workers (inside the hive)
        before = len(self.bees)
        self.bees = [b for b in self.bees
                     if b.hunger <= WORKER_STARVATION_THRESHOLD]
        self._log_deaths(before - len(self.bees), "worker(s) starved")

        # Queen
        if (self.queen_alive
                and self.queen_hunger > QUEEN_EAT_INTERVAL * QUEEN_STARVE_GRACE_MULTIPLIER):
            self.queen_alive = False
            self._log_queen_death()

    # ================================================================
    # Role assignment
    # ================================================================

    def _assign_roles(self):
        counts: Dict[str, int] = {role: 0 for role in ALL_TASKS + [ROLE_NONE]}
        for bee in self.bees:
            counts[bee.role] = counts.get(bee.role, 0) + 1

        self._release_overallocated_roles(counts)
        self._recruit_idle_bees(counts)
        self._emergency_recruit_queen_feeders(counts)
        self._emergency_recruit_succession_roles(counts)

    def _manage_succession(self):
        if (self.queen_alive and not self.succession_started
                and self.queen_age >= QUEEN_LIFESPAN * QUEEN_AGING_START):
            self.succession_started = True
            self._append_log("Queen is aging; workers begin raising a successor")

        qcell     = self.grid.queen_brood_cell()
        building  = self.grid.active_build_site(CellType.QUEEN_BROOD)
        has_larva = qcell is not None and len(qcell.larvae) > 0

        need_builders = building is not None or (
            self.succession_started and qcell is None and building is None)
        self.alloc[ROLE_BUILD_QUEEN_BROOD] = (
            QUEEN_BROOD_BUILDERS if need_builders else 0)
        self.alloc[ROLE_FEED_QUEEN_LARVA] = (
            QUEEN_LARVA_FEEDERS if has_larva else 0)

    def _emergency_recruit_succession_roles(self, counts: Dict[str, int]):
        for role, anchor in (
            (ROLE_BUILD_QUEEN_BROOD, self.grid.queen_pos),
            (ROLE_FEED_QUEEN_LARVA,  self._queen_larva_anchor()),
        ):
            shortfall = self.alloc.get(role, 0) - counts.get(role, 0)
            if shortfall <= 0:
                continue
            ax, ay = anchor
            protected = {ROLE_FEED_QUEEN, ROLE_BUILD_QUEEN_BROOD,
                         ROLE_FEED_QUEEN_LARVA}
            candidates = sorted(
                (b for b in self.bees
                 if b.role not in protected and b.state != BeeState.OUTSIDE),
                key=lambda b: (b.x - ax) ** 2 + (b.y - ay) ** 2,
            )
            for bee in candidates[:shortfall]:
                if bee.carrying > 0:
                    self._return_carried_food(bee)
                bee.role         = role
                bee.intent       = INTENT_NONE
                bee.target_pos   = None
                bee.action_timer = 0
                bee.state        = BeeState.IDLE
                counts[role] = counts.get(role, 0) + 1

    def _queen_larva_anchor(self) -> Tuple[int, int]:
        qcell = self.grid.queen_brood_cell()
        return qcell.pos if qcell is not None else self.grid.queen_pos

    def _emergency_recruit_queen_feeders(self, counts: Dict[str, int]):
        """If queen-feeder slots are still unfilled after normal recruitment,
        forcibly reassign the nearest in-hive bee(s) regardless of state."""
        if not self.queen_alive:
            return
        shortfall = self.alloc[ROLE_FEED_QUEEN] - counts.get(ROLE_FEED_QUEEN, 0)
        if shortfall <= 0:
            return

        qx, qy = self.queen_x, self.queen_y
        protected = {ROLE_FEED_QUEEN, ROLE_FEED_QUEEN_LARVA,
                     ROLE_BUILD_QUEEN_BROOD}
        candidates = sorted(
            (b for b in self.bees
             if b.role not in protected and b.state != BeeState.OUTSIDE),
            key=lambda b: (b.x - qx) ** 2 + (b.y - qy) ** 2,
        )
        for bee in candidates[:shortfall]:
            if bee.carrying > 0:
                self._return_carried_food(bee)
            bee.role         = ROLE_FEED_QUEEN
            bee.intent       = INTENT_NONE
            bee.target_pos   = None
            bee.action_timer = 0
            bee.state        = BeeState.IDLE
            counts[ROLE_FEED_QUEEN] = counts.get(ROLE_FEED_QUEEN, 0) + 1
            self._append_log("Emergency: nearest worker reassigned to feed queen")

    def _release_overallocated_roles(self, counts: Dict[str, int]):
        for role in ALL_TASKS:
            excess = counts[role] - self.alloc[role]
            if excess <= 0:
                continue
            for bee in self.bees:
                if excess <= 0:
                    break
                if bee.role == role and self._can_assign_role(bee):
                    bee.role = ROLE_NONE
                    counts[role]      -= 1
                    counts[ROLE_NONE] += 1
                    excess            -= 1

    def _recruit_idle_bees(self, counts: Dict[str, int]):
        for role in ALL_TASKS:
            needed = self.alloc[role] - counts[role]
            if needed <= 0:
                continue
            for bee in self.bees:
                if needed <= 0:
                    break
                if bee.role == ROLE_NONE and self._can_assign_role(bee):
                    bee.role = role
                    counts[ROLE_NONE] -= 1
                    counts[role]      += 1
                    needed            -= 1

    @staticmethod
    def _can_assign_role(bee: Bee) -> bool:
        return (bee.state != BeeState.OUTSIDE
                and bee.carrying == 0
                and bee.action_timer == 0)

    # ================================================================
    # Per-bee update dispatch
    # ================================================================

    def _update_bee(self, bee: Bee):
        if bee.state == BeeState.OUTSIDE:
            self._update_outside_bee(bee)
            return

        # --- Self-feeding: prevent starvation for every in-hive bee ---
        if bee.hunger >= BEE_EAT_INTERVAL and bee.intent != INTENT_SELF_FEED:
            if bee.carrying > 0:
                # Snack from whatever we're hauling instant, no trip needed
                bee.carrying -= 1
                bee.hunger    = 0
            elif bee.hunger >= WORKER_HUNGER_CRITICAL:
                # Critical: abandon current task and rush to nearest food
                food_cell = self.grid.nearest_food_source((bee.x, bee.y))
                if food_cell is not None:
                    bee.action_timer = 0
                    self._send_to(bee, food_cell.pos, INTENT_SELF_FEED)
            elif bee.state == BeeState.IDLE:
                # Normal hungry + idle: go eat before taking a new job
                self._start_self_feed(bee)

        if bee.state == BeeState.MOVING:
            self._update_moving_bee(bee)
        elif bee.state == BeeState.WORKING:
            self._update_working_bee(bee)
        else:
            self._update_idle_bee(bee)

    # ─── Outside ───────────────────────────────────────────────────

    def _update_outside_bee(self, bee: Bee):
        if bee.forage_timer > 0:
            bee.forage_timer -= 1
            return
        if random.random() < FORAGE_DEATH_CHANCE:
            self._dead_foragers.append(bee)
            return
        # Returned safely — appear back at the entrance with nectar.
        bee.carrying = FORAGE_FOOD_RETURN
        ex, ey = self.grid.entrance_pos
        bee.x, bee.y = float(ex), float(ey)
        bee.state  = BeeState.IDLE
        bee.intent = INTENT_NONE

    def _remove_dead_foragers(self):
        if not self._dead_foragers:
            return
        dead_ids = {id(b) for b in self._dead_foragers}
        self.bees = [b for b in self.bees if id(b) not in dead_ids]
        self._dead_foragers.clear()

    # ─── Movement ──────────────────────────────────────────────────

    def _update_moving_bee(self, bee: Bee):
        if bee.target_pos is None:
            bee.state = BeeState.IDLE
            return
        if self._step_toward(bee, bee.target_pos):
            self._on_arrive(bee)

    def _step_toward(self, bee: Bee, target: Tuple[int, int]) -> bool:
        tx, ty = target
        dx, dy = tx - bee.x, ty - bee.y
        dist = math.hypot(dx, dy)
        if dist <= BEE_MOVE_SPEED_CELLS_PER_TICK:
            bee.x, bee.y = float(tx), float(ty)
            return True
        bee.x += dx / dist * BEE_MOVE_SPEED_CELLS_PER_TICK
        bee.y += dy / dist * BEE_MOVE_SPEED_CELLS_PER_TICK
        return False

    # ─── Working ───────────────────────────────────────────────────

    def _update_working_bee(self, bee: Bee):
        bee.action_timer -= 1
        if bee.action_timer <= 0:
            bee.action_timer = 0
            self._finish_work(bee)

    # ─── Idle / planning ───────────────────────────────────────────

    def _update_idle_bee(self, bee: Bee):
        planners: Dict[str, Callable[[Bee], None]] = {
            ROLE_FEED_QUEEN:  self._plan_feed_queen,
            ROLE_FEED_LARVAE: self._plan_feed_larvae,
            ROLE_BUILD_FOOD:  lambda b: self._plan_build(b, CellType.FOOD),
            ROLE_BUILD_BROOD: lambda b: self._plan_build(b, CellType.BROOD),
            ROLE_BUILD_QUEEN_BROOD: lambda b: self._plan_build(b, CellType.QUEEN_BROOD),
            ROLE_FEED_QUEEN_LARVA:  self._plan_feed_queen_larva,
            ROLE_FORAGE:      self._plan_forage,
        }
        planner = planners.get(bee.role)
        if planner is not None:
            planner(bee)
        else:
            self._idle_wander(bee)

    def _idle_wander(self, bee: Bee):
        hx, hy = bee.home_pos
        dx, dy = hx - bee.x, hy - bee.y
        if dx * dx + dy * dy > BEE_IDLE_WANDER_THRESHOLD_SQ:
            bee.target_pos = (int(round(hx)), int(round(hy)))
            bee.intent     = INTENT_NONE
            bee.state      = BeeState.MOVING

    # ================================================================
    # Task planners
    # ================================================================

    def _start_self_feed(self, bee: Bee) -> bool:
        food_cell = self.grid.nearest_food_source((bee.x, bee.y))
        if food_cell is None:
            return False
        self._send_to(bee, food_cell.pos, INTENT_SELF_FEED)
        return True

    def _plan_feed_queen(self, bee: Bee):
        if not self.queen_alive:
            if bee.carrying > 0:
                self._return_carried_food(bee)
            self._idle_wander(bee)
            return
        # Self-feed if hungry: keep carrying queen food while eating
        if bee.hunger >= BEE_EAT_INTERVAL:
            food_cell = self.grid.nearest_food_source((bee.x, bee.y))
            if food_cell is not None:
                self._send_to(bee, food_cell.pos, INTENT_SELF_FEED)
                return
        if bee.carrying > 0:
            # Food in hand: feed her if she's hungry, otherwise wait nearby.
            if self.queen_hunger >= QUEEN_EAT_INTERVAL:
                self._send_to(bee, self._queen_tile(), INTENT_DELIVER_QUEEN)
            else:
                self._move_near_queen(bee)
            return
        # Not carrying: proactively fetch food so it's ready when she needs it.
        food_cell = self.grid.nearest_food_source((bee.x, bee.y))
        if food_cell is None:
            self._move_near_queen(bee)
            return
        self._send_to(bee, food_cell.pos, INTENT_FETCH_FOOD_QUEEN)

    def _queen_tile(self) -> Tuple[int, int]:
        return (int(round(self.queen_x)), int(round(self.queen_y)))

    def _move_near_queen(self, bee: Bee):
        qx, qy = self.queen_x, self.queen_y
        if math.hypot(bee.x - qx, bee.y - qy) > QUEEN_ATTENDANT_RANGE:
            self._send_to(bee, self._queen_tile(), INTENT_NONE)

    def _plan_feed_queen_larva(self, bee: Bee):
        qcell = self.grid.queen_brood_cell()
        if qcell is None or not qcell.larvae:
            self._idle_wander(bee)
            return
        if bee.carrying > 0:
            larva = qcell.larvae[0]
            if larva.hunger >= LARVA_FEED_HUNGER_THRESHOLD:
                self._send_to(bee, qcell.pos, INTENT_DELIVER_QLARVA)
            elif math.hypot(bee.x - qcell.x, bee.y - qcell.y) > 1.0:
                self._send_to(bee, qcell.pos, INTENT_NONE)
            return
        food_cell = self.grid.nearest_food_source((bee.x, bee.y))
        if food_cell is None:
            return
        self._send_to(bee, food_cell.pos, INTENT_FETCH_FOOD_QLARVA)

    def _plan_feed_larvae(self, bee: Bee):
        if self.food <= QUEEN_FOOD_RESERVE:
            return
        if self.grid.nearest_brood_with_hungry_larva((bee.x, bee.y)) is None:
            return
        food_cell = self.grid.nearest_food_source((bee.x, bee.y))
        if food_cell is None:
            return
        self._send_to(bee, food_cell.pos, INTENT_FETCH_FOOD_LARVA)

    def _plan_build(self, bee: Bee, target: CellType):
        site = (self.grid.active_build_site(target)
                or self.grid.designate_build_site(target))
        if site is None:
            return

        needs_food = site.build_food_used < BUILD_FOOD_REQUIRED
        if needs_food and self.food > QUEEN_FOOD_RESERVE:
            food_cell = self.grid.nearest_food_source((bee.x, bee.y))
            if food_cell is not None:
                self._send_to(bee, food_cell.pos, INTENT_FETCH_FOOD_BUILD)
                return

        self._send_to(bee, site.pos, INTENT_WORK_BUILD)

    def _plan_forage(self, bee: Bee):
        if bee.carrying > 0:
            self._plan_store_forage(bee)
            return
        self._send_to(bee, self.grid.entrance_pos, INTENT_GO_TO_ENTRANCE)

    def _plan_store_forage(self, bee: Bee):
        storage = self.grid.nearest_food_storage_with_space((bee.x, bee.y))
        if storage is None:
            bee.carrying = 0  # no storage anywhere — discarded
            return
        self._send_to(bee, storage.pos, INTENT_STORE_FORAGE)

    def _send_to(self, bee: Bee, target: Tuple[int, int], intent: str):
        bee.target_pos = target
        bee.intent     = intent
        bee.state      = BeeState.MOVING

    # ================================================================
    # Arrival handlers
    # ================================================================

    def _on_arrive(self, bee: Bee):
        cell = self.grid.cell_at(bee.target_pos) if bee.target_pos else None
        bee.target_pos = None

        handlers: Dict[str, Callable[[Bee, Optional[Cell]], None]] = {
            INTENT_SELF_FEED:        self._arrive_pickup,
            INTENT_FETCH_FOOD_QUEEN: self._arrive_pickup,
            INTENT_FETCH_FOOD_LARVA: self._arrive_pickup,
            INTENT_FETCH_FOOD_BUILD: self._arrive_pickup,
            INTENT_FETCH_FOOD_QLARVA: self._arrive_pickup,
            INTENT_DELIVER_QUEEN:    self._arrive_feed_action,
            INTENT_DELIVER_QLARVA:   self._arrive_feed_action,
            INTENT_DELIVER_LARVA:    self._arrive_feed_action,
            INTENT_DELIVER_BUILD:    self._arrive_deposit_build,
            INTENT_WORK_BUILD:       self._arrive_work_build,
            INTENT_GO_TO_ENTRANCE:   self._arrive_entrance,
            INTENT_STORE_FORAGE:     self._arrive_store_forage,
        }
        handlers.get(bee.intent, self._arrive_idle)(bee, cell)

    def _arrive_idle(self, bee: Bee, _cell: Optional[Cell]):
        bee.intent = INTENT_NONE
        bee.state  = BeeState.IDLE

    def _arrive_pickup(self, bee: Bee, cell: Optional[Cell]):
        if cell and cell.cell_type == CellType.FOOD and cell.food > 0:
            bee.action_timer = ACTION_PICKUP_TICKS
            bee.state        = BeeState.WORKING
        else:
            self._arrive_idle(bee, cell)

    def _arrive_feed_action(self, bee: Bee, _cell: Optional[Cell]):
        bee.action_timer = ACTION_FEED_TICKS
        bee.state        = BeeState.WORKING

    def _arrive_deposit_build(self, bee: Bee, _cell: Optional[Cell]):
        bee.action_timer = ACTION_DEPOSIT_TICKS
        bee.state        = BeeState.WORKING

    def _arrive_work_build(self, bee: Bee, cell: Optional[Cell]):
        if cell and cell.cell_type in (CellType.BUILD_FOOD,
                                       CellType.BUILD_BROOD,
                                       CellType.BUILD_QUEEN_BROOD):
            bee.action_timer = ACTION_BUILD_STEP_TICKS
            bee.state        = BeeState.WORKING
        else:
            self._arrive_idle(bee, cell)

    def _arrive_entrance(self, bee: Bee, _cell: Optional[Cell]):
        bee.state        = BeeState.OUTSIDE
        bee.forage_timer = FORAGE_TRIP_TICKS
        bee.intent       = INTENT_NONE

    def _arrive_store_forage(self, bee: Bee, _cell: Optional[Cell]):
        bee.action_timer = ACTION_DEPOSIT_TICKS
        bee.state        = BeeState.WORKING

    # ================================================================
    # Work completion handlers
    # ================================================================

    def _finish_work(self, bee: Bee):
        handlers: Dict[str, Callable[[Bee], None]] = {
            INTENT_SELF_FEED:        self._complete_self_feed,
            INTENT_FETCH_FOOD_QUEEN: self._complete_pickup_for_queen,
            INTENT_FETCH_FOOD_LARVA: self._complete_pickup_for_larva,
            INTENT_FETCH_FOOD_BUILD: self._complete_pickup_for_build,
            INTENT_FETCH_FOOD_QLARVA: self._complete_pickup_for_qlarva,
            INTENT_DELIVER_QUEEN:    self._complete_deliver_queen,
            INTENT_DELIVER_QLARVA:   self._complete_deliver_qlarva,
            INTENT_DELIVER_LARVA:    self._complete_deliver_larva,
            INTENT_DELIVER_BUILD:    self._complete_deliver_build,
            INTENT_WORK_BUILD:       self._complete_work_build,
            INTENT_STORE_FORAGE:     self._complete_store_forage,
        }
        handlers.get(bee.intent, self._complete_idle)(bee)

    def _complete_idle(self, bee: Bee):
        bee.intent = INTENT_NONE
        bee.state  = BeeState.IDLE

    def _bee_cell(self, bee: Bee) -> Optional[Cell]:
        return self.grid.cell_at((int(round(bee.x)), int(round(bee.y))))

    # ─── Self-feed ─────────────────────────────────────────────────

    def _complete_self_feed(self, bee: Bee):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type == CellType.FOOD and cell.food > 0:
            cell.food -= 1
            bee.hunger = 0
        self._complete_idle(bee)

    # ─── Pickups ───────────────────────────────────────────────────

    def _complete_pickup_for_queen(self, bee: Bee):
        self._pick_up_food(bee, BEE_QUEEN_DELIVERY_LOAD)
        if bee.carrying > 0:
            self._send_to(bee, self._queen_tile(), INTENT_DELIVER_QUEEN)
        else:
            self._complete_idle(bee)

    def _complete_pickup_for_qlarva(self, bee: Bee):
        self._pick_up_food(bee, BEE_CARRY_CAPACITY)
        qcell = self.grid.queen_brood_cell()
        if bee.carrying > 0 and qcell is not None:
            self._send_to(bee, qcell.pos, INTENT_DELIVER_QLARVA)
        else:
            if bee.carrying > 0:
                self._return_carried_food(bee)
            self._complete_idle(bee)

    def _complete_deliver_qlarva(self, bee: Bee):
        cell = self._bee_cell(bee)
        if (cell and cell.cell_type == CellType.QUEEN_BROOD
                and cell.larvae and bee.carrying > 0):
            larva = cell.larvae[0]
            if larva.hunger >= LARVA_FEED_HUNGER_THRESHOLD:
                larva.hunger  = 0
                bee.carrying -= 1
        # Keep any leftover food and wait beside the cell (planner handles it).
        self._complete_idle(bee)

    def _complete_pickup_for_larva(self, bee: Bee):
        self._pick_up_food(bee, BEE_CARRY_CAPACITY)
        if bee.carrying <= 0:
            self._complete_idle(bee)
            return
        target = self.grid.nearest_brood_with_hungry_larva((bee.x, bee.y))
        if target is None:
            self._return_carried_food(bee)
            self._complete_idle(bee)
            return
        self._send_to(bee, target.pos, INTENT_DELIVER_LARVA)

    def _complete_pickup_for_build(self, bee: Bee):
        site = self._current_build_site_for_bee(bee)
        remaining_food = (BUILD_FOOD_REQUIRED - site.build_food_used
                          if site else 0)
        if remaining_food > 0:
            self._pick_up_food(bee, min(BEE_CARRY_CAPACITY, remaining_food))
        if site is None or bee.carrying <= 0:
            if bee.carrying > 0:
                self._return_carried_food(bee)
            self._complete_idle(bee)
            return
        self._send_to(bee, site.pos, INTENT_DELIVER_BUILD)

    def _pick_up_food(self, bee: Bee, desired: int):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type == CellType.FOOD and cell.food > 0:
            take = min(cell.food, desired)
            cell.food    -= take
            bee.carrying += take

    # ─── Deliveries ────────────────────────────────────────────────

    def _complete_deliver_queen(self, bee: Bee):
        if (self.queen_alive
                and self.queen_hunger >= QUEEN_EAT_INTERVAL
                and bee.carrying > 0):
            bee.carrying     -= 1
            self.queen_hunger = 0
        if bee.carrying > 0 and not self.queen_alive:
            self._return_carried_food(bee)
        # If still carrying (queen not hungry yet), keep it and go idle;
        # the planner will have us loiter near her until she needs it.
        self._complete_idle(bee)

    def _complete_deliver_larva(self, bee: Bee):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type == CellType.BROOD and bee.carrying > 0:
            hungriest = sorted(cell.larvae, key=lambda l: -l.hunger)
            for larva in hungriest:
                if bee.carrying <= 0:
                    break
                if larva.hunger < LARVA_FEED_HUNGER_THRESHOLD:
                    break
                larva.hunger  = 0
                bee.carrying -= 1
        # Still carrying? Try another cell with hungry larvae.
        if bee.carrying > 0:
            next_brood = self.grid.nearest_brood_with_hungry_larva(
                (bee.x, bee.y))
            if next_brood is not None:
                self._send_to(bee, next_brood.pos, INTENT_DELIVER_LARVA)
                return
            self._return_carried_food(bee)
        self._complete_idle(bee)

    def _complete_deliver_build(self, bee: Bee):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type in (CellType.BUILD_FOOD,
                                       CellType.BUILD_BROOD,
                                       CellType.BUILD_QUEEN_BROOD):
            while (bee.carrying > 0
                   and cell.build_food_used < BUILD_FOOD_REQUIRED):
                cell.build_food_used += 1
                bee.carrying         -= 1
        if bee.carrying > 0:
            self._return_carried_food(bee)
        self._complete_idle(bee)

    # ─── Build work ────────────────────────────────────────────────

    def _complete_work_build(self, bee: Bee):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type in (CellType.BUILD_FOOD,
                                       CellType.BUILD_BROOD,
                                       CellType.BUILD_QUEEN_BROOD):
            cell.build_progress += ACTION_BUILD_STEP_TICKS
            self._check_build_complete(cell)
        self._complete_idle(bee)

    def _check_build_complete(self, cell: Cell):
        if (cell.build_progress >= BUILD_WORK_TICKS
                and cell.build_food_used >= BUILD_FOOD_REQUIRED):
            target = cell.build_target or CellType.FOOD
            cell.cell_type       = target
            cell.build_progress  = 0
            cell.build_food_used = 0
            cell.build_target    = None
            label = {CellType.FOOD: 'food', CellType.BROOD: 'brood',
                     CellType.QUEEN_BROOD: 'queen'}.get(target, 'brood')
            self._log_block_completed(label)

    # ─── Forage storage ────────────────────────────────────────────

    def _complete_store_forage(self, bee: Bee):
        cell = self._bee_cell(bee)
        if cell and cell.cell_type == CellType.FOOD and bee.carrying > 0:
            stored = self.grid.deposit_food_at(cell, bee.carrying)
            bee.carrying -= stored
        if bee.carrying > 0:
            other = self.grid.nearest_food_storage_with_space((bee.x, bee.y))
            if other is not None:
                self._send_to(bee, other.pos, INTENT_STORE_FORAGE)
                return
            bee.carrying = 0  # overflow — discarded
        self._complete_idle(bee)

    # ─── Helpers ───────────────────────────────────────────────────

    def _return_carried_food(self, bee: Bee):
        while bee.carrying > 0:
            cell = self.grid.nearest_food_storage_with_space((bee.x, bee.y))
            if cell is None:
                bee.carrying = 0
                return
            stored = self.grid.deposit_food_at(cell, bee.carrying)
            if stored == 0:
                bee.carrying = 0
                return
            bee.carrying -= stored

    def _current_build_site_for_bee(self, bee: Bee) -> Optional[Cell]:
        if bee.role == ROLE_BUILD_FOOD:
            target = CellType.FOOD
        elif bee.role == ROLE_BUILD_BROOD:
            target = CellType.BROOD
        elif bee.role == ROLE_BUILD_QUEEN_BROOD:
            target = CellType.QUEEN_BROOD
        else:
            return None
        return (self.grid.active_build_site(target)
                or self.grid.designate_build_site(target))

    # ================================================================
    # Auto-Allocation
    # ================================================================

    def _compute_consumption_rates(self) -> Tuple[float, float, float]:
        queen_rate  = (1.0 / QUEEN_EAT_INTERVAL) if self.queen_alive else 0.0
        larvae_rate = len(self.larvae)       / BEE_EAT_INTERVAL
        worker_rate = self.total_workers()   / BEE_EAT_INTERVAL
        return queen_rate, larvae_rate, worker_rate

    @staticmethod
    def _income_per_forager() -> float:
        return (FORAGE_FOOD_RETURN * (1.0 - FORAGE_DEATH_CHANCE)
                / max(1, FORAGE_TRIP_TICKS))

    def _assess_food_state(self) -> Tuple[bool, bool, bool]:
        critical_threshold = QUEEN_FOOD_RESERVE * FOOD_CRITICAL_MULTIPLIER
        low_threshold      = QUEEN_FOOD_RESERVE * FOOD_LOW_MULTIPLIER
        good_threshold     = max(
            FOOD_GOOD_MINIMUM, self.food_capacity() * FOOD_GOOD_CAPACITY_RATIO
        )
        return (self.food < critical_threshold,
                self.food < low_threshold,
                self.food > good_threshold)

    def auto_allocate(self):
        total = self.total_workers()
        alloc = {task: 0 for task in ALL_TASKS}
        if total <= 0:
            self.alloc = alloc
            return

        remaining = total
        queen_rate, larvae_rate, worker_rate = self._compute_consumption_rates()
        income_pf = self._income_per_forager()
        food_critical, food_low, food_good = self._assess_food_state()

        if self.queen_alive and remaining >= 2:
            alloc[ROLE_FEED_QUEEN] = 2
            remaining -= 2
        elif self.queen_alive and remaining > 0:
            alloc[ROLE_FEED_QUEEN] = 1
            remaining -= 1

        if food_critical:
            alloc[ROLE_FORAGE] = remaining
            self.alloc = alloc
            return

        if food_low:
            target_rate = queen_rate + worker_rate
            safety      = FORAGER_SAFETY_FACTOR_LOW
        else:
            target_rate = queen_rate + worker_rate + larvae_rate
            safety      = FORAGER_SAFETY_FACTOR_NORMAL

        if income_pf > 0:
            foragers_needed = math.ceil(target_rate * safety / income_pf)
        else:
            foragers_needed = MIN_FORAGERS
        foragers_needed = max(MIN_FORAGERS, foragers_needed)
        foragers_needed = min(foragers_needed, remaining)
        alloc[ROLE_FORAGE] = foragers_needed
        remaining -= foragers_needed

        remaining = self._allocate_larvae_feeders(alloc, remaining, food_low)
        remaining = self._allocate_builders(alloc, remaining, food_good)

        alloc[ROLE_FORAGE] += remaining
        self.alloc = alloc

    def _allocate_larvae_feeders(
        self, alloc: dict, remaining: int, food_low: bool,
    ) -> int:
        if remaining <= 0 or food_low:
            return remaining
        larva_count = len(self.larvae)
        if larva_count == 0:
            return remaining
        needed  = max(1, math.ceil(larva_count / LARVA_FEEDERS_PER_LARVA_DIVISOR))
        feeders = min(needed, remaining)
        alloc[ROLE_FEED_LARVAE] = feeders
        return remaining - feeders

    def _allocate_builders(
        self, alloc: dict, remaining: int, food_good: bool,
    ) -> int:
        if remaining <= 0 or not food_good:
            return remaining
        if self.brood_space() < BROOD_SPACE_BUFFER:
            brood_builders = min(MAX_BROOD_BUILDERS, remaining)
            alloc[ROLE_BUILD_BROOD] = brood_builders
            remaining -= brood_builders
        if remaining > 0 and self.food_space() < FOOD_SPACE_EXPANSION_THRESHOLD:
            food_builders = min(MAX_FOOD_BUILDERS, remaining)
            alloc[ROLE_BUILD_FOOD] = food_builders
            remaining -= food_builders
        return remaining


# ============================================================================
# Simulator (command handling + run-state)
# ============================================================================

class Simulator:
    """Wraps a Hive with playback controls and a text command interface."""

    def __init__(self):
        self.hive: Hive
        self.tick_rate: float
        self.paused: bool
        self.auto_mode: bool
        self.should_quit: bool
        self.status_message: str
        self.reset()

    def reset(self):
        self.hive           = Hive()
        self.tick_rate      = DEFAULT_TICK_RATE
        self.paused         = False
        self.auto_mode      = False
        self.should_quit    = False
        self.status_message = ""

    def step(self):
        if self.auto_mode:
            self.hive.auto_allocate()
        self.hive.tick()

    # ── Command handlers ───────────────────────────────────────────

    def _handle_quit(self, _args):
        self.should_quit = True

    def _handle_pause(self, _args):
        self.paused = True
        self.status_message = "Simulation paused."

    def _handle_resume(self, _args):
        self.paused = False
        self.status_message = "Simulation resumed."

    def _handle_step(self, _args):
        self.step()
        self.status_message = "Stepped one tick."

    def _handle_rate(self, args):
        if not args:
            raise SimulationCommandError(
                f"Usage: rate <{MIN_TICK_RATE}-{MAX_TICK_RATE}>")
        try:
            raw = float(args[0])
        except ValueError:
            raise SimulationCommandError(f"Invalid rate value: '{args[0]}'")
        self.tick_rate = max(MIN_TICK_RATE, min(MAX_TICK_RATE, raw))
        if self.tick_rate == MIN_TICK_RATE:
            self.paused = True
        self.status_message = f"Tick rate: {self.tick_rate} ticks/sec."

    def _handle_auto(self, args):
        if args:
            self.auto_mode = args[0] in ('on', '1', 'true', 'yes')
        else:
            self.auto_mode = not self.auto_mode
        state = 'ON' if self.auto_mode else 'OFF'
        self.status_message = f"Auto mode {state}."

    def _handle_set(self, args):
        if self.auto_mode:
            self.status_message = (
                "Auto mode is ON; 'set' is ignored. Use 'auto off'.")
            return
        if len(args) < 2:
            raise SimulationCommandError("Usage: set <task> <n>")
        key  = args[0]
        task = TASK_ALIASES.get(key, key)
        if task not in ALL_TASKS:
            raise SimulationCommandError(f"Unknown task '{key}'.")
        try:
            count = int(args[1])
        except ValueError:
            raise SimulationCommandError(f"Invalid worker count: '{args[1]}'")
        self.hive.alloc[task] = max(0, count)
        self.status_message = f"Assigned {count} workers to {task}."

    def _handle_help(self, _args):
        self.status_message = (
            f"set <task> <n> | auto [on|off] | "
            f"rate <{MIN_TICK_RATE}-{MAX_TICK_RATE}> | "
            "pause | resume | step | quit")

    _COMMAND_MAP: Dict[str, str] = {
        'q': '_handle_quit',   'quit': '_handle_quit',   'exit': '_handle_quit',
        'p': '_handle_pause',  'pause': '_handle_pause',
        'r': '_handle_resume', 'resume': '_handle_resume', 'play': '_handle_resume',
        's': '_handle_step',   'step': '_handle_step',
        'rate': '_handle_rate',
        'auto': '_handle_auto',
        'set':  '_handle_set',
        'h': '_handle_help', 'help': '_handle_help', '?': '_handle_help',
    }

    def handle_command(self, raw_input: str):
        parts = raw_input.strip().lower().split()
        if not parts:
            return
        command, args = parts[0], parts[1:]
        handler = self._COMMAND_MAP.get(command)
        if handler is None:
            self.status_message = f"Unknown command: '{raw_input}'"
            return
        try:
            getattr(self, handler)(args)
        except SimulationCommandError as err:
            self.status_message = f"Error: {err}"


# ============================================================================
# Entry Point
# ============================================================================

def main():
    """Create a Simulator and launch the UI frontend."""
    from ui import launch as launch_ui
    simulator = Simulator()
    launch_ui(simulator)


if __name__ == '__main__':
    main()