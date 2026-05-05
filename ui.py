#!/usr/bin/env python3
"""
ui.py — Tkinter frontend for the 2D Bee Hive Simulator.

Renders the spatial hive grid as a tile-and-sprite canvas alongside
statistics panels, worker-allocation controls, and an event log.

All visual tuning lives in named constants at the top of this file.
The canvas uses three item layers managed via tags:

  * **cell tiles** — created once, colours updated only when changed
  * ``'overlay'`` — food-level fills, brood dots, build indicators
    (deleted and recreated each frame)
  * ``'sprite'`` — bee circles, queen marker
    (deleted and recreated each frame)
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from hive import Bee, Cell, Hive, Simulator

from hive import (
    ALL_TASKS,
    BeeState,
    BUILD_FOOD_REQUIRED,
    BUILD_WORK_TICKS,
    CELL_BROOD_CAPACITY,
    CELL_FOOD_CAPACITY,
    CellType,
    GRID_HEIGHT,
    GRID_WIDTH,
    MAX_TICK_RATE,
    MIN_TICK_RATE,
    QUEEN_EAT_INTERVAL,
    QUEEN_EGG_HATCH_TICKS,
    QUEEN_LARVA_GROW_TICKS,
    QUEEN_LIFESPAN,
    ROLE_BUILD_BROOD,
    ROLE_BUILD_FOOD,
    ROLE_BUILD_QUEEN_BROOD,
    ROLE_FEED_LARVAE,
    ROLE_FEED_QUEEN_LARVA,
    ROLE_FEED_QUEEN,
    ROLE_FORAGE,
    ROLE_NONE,
)


# ============================================================================
# Timer
# ============================================================================

TICK_POLL_INTERVAL_MS = 25
"""Milliseconds between ``after()`` polls for the next simulation tick."""

MAX_TICKS_PER_POLL = 4
"""Cap on simulation steps executed in a single poll, so the UI stays
responsive at high tick rates."""


# ============================================================================
# Window
# ============================================================================

WINDOW_TITLE      = "Bee Hive Simulator"
WINDOW_MIN_WIDTH  = 1060
WINDOW_MIN_HEIGHT = 750


# ============================================================================
# Fonts
# ============================================================================

FONT_HEADER       = ("Helvetica", 14, "bold")
FONT_SECTION      = ("Helvetica", 11, "bold")
FONT_BODY         = ("Helvetica", 10)
FONT_BODY_BOLD    = ("Helvetica", 10, "bold")
FONT_MONO         = ("Courier",   10)
FONT_STATUS       = ("Helvetica",  9, "italic")
FONT_LEGEND       = ("Helvetica",  8)
FONT_CANVAS_SMALL = ("Helvetica",  7, "bold")


# ============================================================================
# Spacing (pixels)
# ============================================================================

PAD_FRAME      = 8
PAD_SECTION    = 6
PAD_LABEL      = 2
PAD_INNER      = 4
PAD_HEADER_GAP = 16


# ============================================================================
# Widget sizes (characters unless noted)
# ============================================================================

LABEL_COL_WIDTH          = 12
VALUE_COL_WIDTH          = 6
STATUS_VALUE_WIDTH       = 28
CONSTRUCTION_LABEL_WIDTH = 6
LOG_VISIBLE_LINES        = 10
LOG_WIDGET_CHARS         = 60
CAPACITY_BAR_LENGTH      = 140   # px
CONSTRUCTION_BAR_LENGTH  = 80    # px
MIN_PROGRESS_MAXIMUM     = 1

SPINBOX_WIDTH     = 6
ALLOC_SPINBOX_MIN = 0

RATE_SLIDER_LENGTH   = 180  # px
RATE_PRECISION       = 1
RATE_LABEL_WIDTH     = 10
CONTROL_BUTTON_WIDTH = 8


# ============================================================================
# Canvas — cell tiles
# ============================================================================

CELL_SIZE_PX  = 18
CANVAS_WIDTH  = GRID_WIDTH  * CELL_SIZE_PX
CANVAS_HEIGHT = GRID_HEIGHT * CELL_SIZE_PX
CANVAS_BG     = '#d7ccc8'

CELL_BORDER_WIDTH  = 1
CELL_BORDER_COLOR  = '#bcaaa4'
DEFAULT_CELL_COLOR = '#e8e0d4'

CELL_COLORS: Dict[str, str] = {
    CellType.EMPTY:       '#e8e0d4',
    CellType.FOOD:        '#fff8e1',
    CellType.BROOD:       '#efebe9',
    CellType.QUEEN:       '#e1bee7',
    CellType.ENTRANCE:    '#c8e6c9',
    CellType.BUILD_FOOD:  '#fff3e0',
    CellType.BUILD_BROOD: '#d7ccc8',
    CellType.QUEEN_BROOD:       '#f8bbd0',
    CellType.BUILD_QUEEN_BROOD: '#f3e5f5',
}


# ============================================================================
# Canvas — food-fill overlay
# ============================================================================

COLOR_FOOD_FILL = '#ffb300'
FOOD_FILL_INSET = 2          # px inset from tile edge


# ============================================================================
# Canvas — brood-dot overlay
# ============================================================================

COLOR_EGG_DOT    = '#ffffff'
COLOR_LARVA_DOT  = '#ffe0b2'
EGG_DOT_RADIUS   = 1
LARVA_DOT_RADIUS = 2
BROOD_DOT_COLS   = 3         # dots are arranged in an NxM micro-grid


# ============================================================================
# Canvas — build-site overlay
# ============================================================================

COLOR_BUILD_MARKER   = '#78909c'
BUILD_MARKER_WIDTH   = 2
BUILD_MARKER_DASH    = (3, 2)
COLOR_BUILD_PROGRESS = '#81c784'


# ============================================================================
# Canvas — bee sprites
# ============================================================================

BEE_SPRITE_RADIUS = 3
BEE_OUTLINE_WIDTH = 1
BEE_OUTLINE_COLOR = '#5d4037'

ROLE_BEE_COLORS: Dict[str, str] = {
    ROLE_NONE:        '#fdd835',
    ROLE_FEED_QUEEN:  '#66bb6a',
    ROLE_FEED_LARVAE: '#42a5f5',
    ROLE_BUILD_FOOD:  '#90a4ae',
    ROLE_BUILD_BROOD: '#90a4ae',
    ROLE_BUILD_QUEEN_BROOD: '#ab47bc',
    ROLE_FEED_QUEEN_LARVA:  '#ec407a',
    ROLE_FORAGE:      '#ffa726',
}

COLOR_BEE_CARRYING = '#e65100'


# ============================================================================
# Canvas — queen sprite
# ============================================================================

QUEEN_SPRITE_RADIUS  = 5
QUEEN_SPRITE_FILL    = '#ce93d8'
QUEEN_SPRITE_OUTLINE = '#6a1b9a'
QUEEN_SPRITE_WIDTH   = 2
QUEEN_DEAD_FILL      = '#616161'


# ============================================================================
# Canvas — entrance marker
# ============================================================================

ENTRANCE_ARROW_COLOR = '#2e7d32'
ENTRANCE_ARROW_SCALE = 3     # px half-size of the directional triangle
FORAGER_COUNT_COLOR  = '#1b5e20'
FORAGER_COUNT_OFFSET = 3     # px above the arrow


# ============================================================================
# Canvas — legend strip
# ============================================================================

LEGEND_SWATCH_SIZE  = 10     # px square
LEGEND_SWATCH_GAP   = 2     # px between swatch and label
LEGEND_ITEM_SPACING = 8     # px between items

LEGEND_ITEMS: List[Tuple[str, str]] = [
    ("Queen",    QUEEN_SPRITE_FILL),
    ("Feed Q",   ROLE_BEE_COLORS[ROLE_FEED_QUEEN]),
    ("Feed L",   ROLE_BEE_COLORS[ROLE_FEED_LARVAE]),
    ("Build",    ROLE_BEE_COLORS[ROLE_BUILD_FOOD]),
    ("Q Cell",   ROLE_BEE_COLORS[ROLE_BUILD_QUEEN_BROOD]),
    ("Feed QL",  ROLE_BEE_COLORS[ROLE_FEED_QUEEN_LARVA]),
    ("Forage",   ROLE_BEE_COLORS[ROLE_FORAGE]),
    ("Idle",     ROLE_BEE_COLORS[ROLE_NONE]),
    ("Carrying", COLOR_BEE_CARRYING),
]


# ============================================================================
# Panel colours
# ============================================================================

COLOR_HEADER_BG   = "#37474f"
COLOR_HEADER_FG   = "#eceff1"
COLOR_QUEEN_ALIVE = "#2e7d32"
COLOR_QUEEN_DEAD  = "#c62828"
COLOR_MODE_AUTO   = "#1565c0"
COLOR_MODE_MANUAL = "#78909c"
COLOR_PAUSED      = "#e65100"
COLOR_LOG_BG      = "#fafafa"
COLOR_LOG_FG      = "#212121"
COLOR_STATUS_FG   = "#616161"


# ============================================================================
# Static text / labels
# ============================================================================

TEXT_START_INDEX = "1.0"

LABEL_PAUSE  = "Pause"
LABEL_RESUME = "Resume"
LABEL_STEP   = "Step"
LABEL_RESET  = "Reset"
LABEL_AUTO   = "Auto Allocate"
LABEL_RATE   = "Rate:"

STATUS_INITIAL       = "Ready.  Hover over the hive to inspect cells."
STATUS_PAUSED        = "Simulation paused."
STATUS_RESUMED       = "Simulation running."
STATUS_STEPPED       = "Advanced one tick."
STATUS_RESET         = "Simulation reset to initial state."
STATUS_AUTO_ON       = "Auto allocation ON \u2014 spinboxes locked."
STATUS_AUTO_OFF      = "Auto allocation OFF \u2014 set workers manually."
STATUS_ALLOC_INVALID = "Invalid input; reverted to previous value."
STATUS_ALLOC_CAPPED  = (
    "Capped {task} at {value} \u2014 "
    "{available} workers available for this task."
)
INFO_DEFAULT = "Hover over the hive to inspect cells."


# ============================================================================
# Hive Canvas
# ============================================================================

class HiveCanvas:
    """Renders the 2D hive grid with cell tiles, overlays, and bee sprites.

    Three visual layers, from back to front:

    1. **Cell tiles** — one rectangle per grid cell, created once in
       ``__init__`` and colour-updated only when a cell's type changes.
    2. ``TAG_OVERLAY`` — food-level fills, brood dots, build-progress
       bars, entrance arrow.  Deleted and redrawn every frame.
    3. ``TAG_SPRITE`` — bee circles and the queen marker.  Deleted
       and redrawn every frame.
    """

    TAG_OVERLAY = 'overlay'
    TAG_SPRITE  = 'sprite'

    def __init__(self, parent: tk.Widget) -> None:
        self._canvas = tk.Canvas(
            parent,
            width=CANVAS_WIDTH,
            height=CANVAS_HEIGHT,
            bg=CANVAS_BG,
            highlightthickness=0,
        )
        # Per-cell rectangle item ids and cached fill colours.
        self._cell_items:  Dict[Tuple[int, int], int] = {}
        self._cell_colors: Dict[Tuple[int, int], str] = {}
        self._init_cell_tiles()

    @property
    def widget(self) -> tk.Canvas:
        return self._canvas

    def reset(self) -> None:
        """Clear the colour cache so the next update repaints every tile."""
        self._cell_colors.clear()

    # ── Setup ──────────────────────────────────────────────────────

    def _init_cell_tiles(self) -> None:
        for y in range(GRID_HEIGHT):
            for x in range(GRID_WIDTH):
                px1, py1 = x * CELL_SIZE_PX, y * CELL_SIZE_PX
                px2, py2 = px1 + CELL_SIZE_PX, py1 + CELL_SIZE_PX
                item = self._canvas.create_rectangle(
                    px1, py1, px2, py2,
                    fill=DEFAULT_CELL_COLOR,
                    outline=CELL_BORDER_COLOR,
                    width=CELL_BORDER_WIDTH,
                )
                self._cell_items[(x, y)] = item
                self._cell_colors[(x, y)] = DEFAULT_CELL_COLOR

    # ── Per-frame entry point ──────────────────────────────────────

    def update(self, hive) -> None:
        """Redraw every dynamic element to reflect current hive state."""
        self._update_cell_backgrounds(hive)

        self._canvas.delete(self.TAG_OVERLAY)
        self._draw_food_fills(hive)
        self._draw_brood_contents(hive)
        self._draw_build_indicators(hive)
        self._draw_entrance(hive)

        self._canvas.delete(self.TAG_SPRITE)
        self._draw_bees(hive)
        self._draw_queen(hive)               # queen drawn last → on top

    # ── Cell backgrounds ───────────────────────────────────────────

    def _update_cell_backgrounds(self, hive) -> None:
        for pos, cell in hive.grid.cells.items():
            color = CELL_COLORS.get(cell.cell_type, DEFAULT_CELL_COLOR)
            if self._cell_colors.get(pos) != color:
                self._canvas.itemconfig(self._cell_items[pos], fill=color)
                self._cell_colors[pos] = color

    # ── Geometry helpers ───────────────────────────────────────────

    @staticmethod
    def _inner_rect(cell) -> Tuple[int, int, int, int]:
        """Pixel bbox inset from the tile edge (for overlays)."""
        p = FOOD_FILL_INSET
        x1 = cell.x * CELL_SIZE_PX + p
        y1 = cell.y * CELL_SIZE_PX + p
        x2 = (cell.x + 1) * CELL_SIZE_PX - p
        y2 = (cell.y + 1) * CELL_SIZE_PX - p
        return x1, y1, x2, y2

    @staticmethod
    def _cell_center_px(x: int, y: int) -> Tuple[int, int]:
        return (x * CELL_SIZE_PX + CELL_SIZE_PX // 2,
                y * CELL_SIZE_PX + CELL_SIZE_PX // 2)

    # ── Food fills ─────────────────────────────────────────────────

    def _draw_food_fills(self, hive) -> None:
        for cell in hive.grid.cells_of_type(CellType.FOOD):
            if cell.food <= 0:
                continue
            x1, y1, x2, y2 = self._inner_rect(cell)
            inner_h = y2 - y1
            fill_h = max(1, int(inner_h * cell.food / CELL_FOOD_CAPACITY))
            self._canvas.create_rectangle(
                x1, y2 - fill_h, x2, y2,
                fill=COLOR_FOOD_FILL, outline='',
                tags=self.TAG_OVERLAY,
            )

    # ── Brood dots ─────────────────────────────────────────────────

    def _draw_brood_contents(self, hive) -> None:
        for cell in hive.grid.cells_of_type(CellType.BROOD, CellType.QUEEN_BROOD):
            n_eggs   = len(cell.eggs)
            n_larvae = len(cell.larvae)
            total    = n_eggs + n_larvae
            if total == 0:
                continue

            x1, y1, x2, y2 = self._inner_rect(cell)
            w, h = x2 - x1, y2 - y1
            n    = min(total, CELL_BROOD_CAPACITY)
            cols = BROOD_DOT_COLS
            rows = max(1, (n + cols - 1) // cols)
            dx   = w / (cols + 1)
            dy   = h / (rows + 1)

            for idx in range(n):
                is_egg = idx < n_eggs
                cx = x1 + dx * (idx % cols + 1)
                cy = y1 + dy * (idx // cols + 1)
                radius = EGG_DOT_RADIUS if is_egg else LARVA_DOT_RADIUS
                color  = COLOR_EGG_DOT  if is_egg else COLOR_LARVA_DOT
                self._canvas.create_oval(
                    cx - radius, cy - radius, cx + radius, cy + radius,
                    fill=color, outline='',
                    tags=self.TAG_OVERLAY,
                )

    # ── Build-site indicators ──────────────────────────────────────

    def _draw_build_indicators(self, hive) -> None:
        for cell in hive.grid.cells_of_type(
            CellType.BUILD_FOOD, CellType.BUILD_BROOD,
            CellType.BUILD_QUEEN_BROOD,
        ):
            x1, y1, x2, y2 = self._inner_rect(cell)

            # Green fill from the bottom proportional to progress
            if cell.build_progress > 0:
                frac = min(1.0,
                           cell.build_progress / max(1, BUILD_WORK_TICKS))
                fh = max(1, int((y2 - y1) * frac))
                self._canvas.create_rectangle(
                    x1, y2 - fh, x2, y2,
                    fill=COLOR_BUILD_PROGRESS, outline='',
                    tags=self.TAG_OVERLAY,
                )

            # Dashed border to mark the site
            self._canvas.create_rectangle(
                x1, y1, x2, y2,
                fill='', outline=COLOR_BUILD_MARKER,
                width=BUILD_MARKER_WIDTH, dash=BUILD_MARKER_DASH,
                tags=self.TAG_OVERLAY,
            )

    # ── Entrance ───────────────────────────────────────────────────

    def _draw_entrance(self, hive) -> None:
        ex, ey = hive.grid.entrance_pos
        cx, cy = self._cell_center_px(ex, ey)
        s = ENTRANCE_ARROW_SCALE

        # Downward-pointing triangle
        self._canvas.create_polygon(
            cx, cy + s,
            cx - s, cy - s,
            cx + s, cy - s,
            fill=ENTRANCE_ARROW_COLOR, outline='',
            tags=self.TAG_OVERLAY,
        )

        # Show how many foragers are currently outside
        n_out = len(hive.foragers)
        if n_out > 0:
            self._canvas.create_text(
                cx, cy - s - FORAGER_COUNT_OFFSET,
                text=str(n_out),
                font=FONT_CANVAS_SMALL,
                fill=FORAGER_COUNT_COLOR,
                tags=self.TAG_OVERLAY,
            )

    # ── Queen sprite ───────────────────────────────────────────────

    def _draw_queen(self, hive) -> None:
        half = CELL_SIZE_PX / 2
        r    = QUEEN_SPRITE_RADIUS
        # Old (superseded) queen drawn first so the new one renders on top.
        if hive.old_queen is not None:
            ox = hive.old_queen['x'] * CELL_SIZE_PX + half
            oy = hive.old_queen['y'] * CELL_SIZE_PX + half
            self._canvas.create_oval(
                ox - r, oy - r, ox + r, oy + r,
                fill=QUEEN_DEAD_FILL, outline=QUEEN_SPRITE_OUTLINE,
                width=QUEEN_SPRITE_WIDTH,
                tags=self.TAG_SPRITE,
            )
        cx = hive.queen_x * CELL_SIZE_PX + half
        cy = hive.queen_y * CELL_SIZE_PX + half
        fill = QUEEN_SPRITE_FILL if hive.queen_alive else QUEEN_DEAD_FILL
        self._canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=fill, outline=QUEEN_SPRITE_OUTLINE,
            width=QUEEN_SPRITE_WIDTH,
            tags=self.TAG_SPRITE,
        )

    # ── Bee sprites ────────────────────────────────────────────────

    def _draw_bees(self, hive) -> None:
        half = CELL_SIZE_PX / 2
        r    = BEE_SPRITE_RADIUS
        for bee in hive.bees:
            if bee.state == BeeState.OUTSIDE:
                continue
            px = bee.x * CELL_SIZE_PX + half
            py = bee.y * CELL_SIZE_PX + half
            color = self._bee_color(bee)
            self._canvas.create_oval(
                px - r, py - r, px + r, py + r,
                fill=color, outline=BEE_OUTLINE_COLOR,
                width=BEE_OUTLINE_WIDTH,
                tags=self.TAG_SPRITE,
            )

    @staticmethod
    def _bee_color(bee) -> str:
        if bee.carrying > 0:
            return COLOR_BEE_CARRYING
        return ROLE_BEE_COLORS.get(bee.role, ROLE_BEE_COLORS[ROLE_NONE])

    # ── Mouse hover ────────────────────────────────────────────────

    def bind_hover(self, callback) -> None:
        """Register *callback(gx, gy)* for mouse-motion events."""
        self._canvas.bind(
            '<Motion>',
            lambda e: self._on_motion(e, callback),
        )

    @staticmethod
    def _on_motion(event: tk.Event, callback) -> None:
        gx = event.x // CELL_SIZE_PX
        gy = event.y // CELL_SIZE_PX
        if 0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT:
            callback(gx, gy)


# ============================================================================
# Main UI
# ============================================================================

class HiveUI:
    """Tkinter frontend bound to a single :class:`Simulator` instance.

    Layout (top to bottom)::

        ┌─────────────────────────────────────────────┐
        │ Header  (tick counter · rate · mode · state) │
        ├──────────────────────┬──────────────────────┤
        │                      │ Hive Status          │
        │  Hive Canvas         │ Worker Allocation    │
        │  + info bar          │ Construction         │
        │  + legend            │ Event Log            │
        ├──────────────────────┴──────────────────────┤
        │ [Pause][Step][Reset]  Rate: [══════] 15 tps │
        │ Status: Ready…                              │
        └─────────────────────────────────────────────┘
    """

    def __init__(self, simulator: Simulator) -> None:
        self._sim = simulator
        self._running = True
        self._last_tick_time = time.time()
        self._last_log_snapshot: List[str] = []

        self._root = tk.Tk()
        self._build_ui()
        self.refresh_display()
        self._schedule_tick()

    # ── Public interface ───────────────────────────────────────────

    def launch(self) -> None:
        """Enter the Tk main loop.  Blocks until the window is closed."""
        self._root.mainloop()

    def refresh_display(self) -> None:
        """Pull current state from the Simulator and repaint everything."""
        self._refresh_header()
        self._refresh_status()
        self._refresh_allocation()
        self._refresh_construction()
        self._refresh_controls()
        self._sync_log()
        self._hive_canvas.update(self._sim.hive)

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    # ================================================================
    # UI construction
    # ================================================================

    def _build_ui(self) -> None:
        self._configure_root()

        header = self._build_header(self._root)
        header.grid(row=0, column=0, sticky="ew")

        body = self._build_body(self._root)
        body.grid(row=1, column=0, sticky="nsew",
                  padx=PAD_FRAME, pady=PAD_SECTION)

        controls = self._build_controls_panel(self._root)
        controls.grid(row=2, column=0, sticky="ew",
                      padx=PAD_FRAME, pady=(PAD_SECTION, PAD_FRAME))

    def _configure_root(self) -> None:
        self._root.title(WINDOW_TITLE)
        self._root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(1, weight=1)          # body stretches

    # ── Header ─────────────────────────────────────────────────────

    def _build_header(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent, bg=COLOR_HEADER_BG,
                         padx=PAD_FRAME, pady=PAD_FRAME)

        tk.Label(
            frame, text="Bee Hive Simulator",
            font=FONT_HEADER, bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG,
        ).pack(side=tk.LEFT, padx=(0, PAD_HEADER_GAP))

        self._tick_var = tk.StringVar()
        tk.Label(
            frame, textvariable=self._tick_var, font=FONT_BODY,
            bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG,
        ).pack(side=tk.LEFT, padx=(0, PAD_HEADER_GAP))

        self._rate_header_var = tk.StringVar()
        tk.Label(
            frame, textvariable=self._rate_header_var, font=FONT_BODY,
            bg=COLOR_HEADER_BG, fg=COLOR_HEADER_FG,
        ).pack(side=tk.LEFT, padx=(0, PAD_HEADER_GAP))

        self._mode_var = tk.StringVar()
        self._mode_label = tk.Label(
            frame, textvariable=self._mode_var,
            font=FONT_BODY_BOLD, bg=COLOR_HEADER_BG,
        )
        self._mode_label.pack(side=tk.LEFT, padx=(0, PAD_INNER))

        self._state_var = tk.StringVar()
        self._state_label = tk.Label(
            frame, textvariable=self._state_var,
            font=FONT_BODY_BOLD, bg=COLOR_HEADER_BG,
        )
        self._state_label.pack(side=tk.LEFT)

        return frame

    # ── Body (canvas | right panel) ────────────────────────────────

    def _build_body(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent)
        frame.columnconfigure(0, weight=0)            # canvas: fixed
        frame.columnconfigure(1, weight=1)            # right: stretches
        frame.rowconfigure(0, weight=1)

        canvas_panel = self._build_canvas_panel(frame)
        canvas_panel.grid(row=0, column=0, sticky="ns",
                          padx=(0, PAD_SECTION))

        right = self._build_right_panel(frame)
        right.grid(row=0, column=1, sticky="nsew")

        return frame

    # ── Canvas panel (left) ────────────────────────────────────────

    def _build_canvas_panel(self, parent: tk.Widget) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent, text=" Hive View ",
            font=FONT_SECTION, padx=PAD_INNER, pady=PAD_INNER,
        )

        self._hive_canvas = HiveCanvas(frame)
        self._hive_canvas.widget.pack()
        self._hive_canvas.bind_hover(self._on_cell_hover)

        # Info bar — shows details of the cell under the cursor
        self._cell_info_var = tk.StringVar(value=INFO_DEFAULT)
        tk.Label(
            frame, textvariable=self._cell_info_var,
            font=FONT_MONO, anchor=tk.W,
        ).pack(fill=tk.X, pady=(PAD_LABEL, 0))

        self._build_legend(frame)

        # Event log beneath the legend, inside canvas panel
        log_panel = self._build_log_panel(frame)
        log_panel.pack(fill=tk.BOTH, expand=True, pady=(PAD_SECTION, 0))

        return frame

    def _build_legend(self, parent: tk.Widget) -> None:
        strip = tk.Frame(parent)
        strip.pack(fill=tk.X, pady=(PAD_LABEL, 0))
        for text, color in LEGEND_ITEMS:
            item = tk.Frame(strip)
            item.pack(side=tk.LEFT, padx=(0, LEGEND_ITEM_SPACING))
            swatch = tk.Canvas(
                item,
                width=LEGEND_SWATCH_SIZE,
                height=LEGEND_SWATCH_SIZE,
                highlightthickness=0,
            )
            swatch.create_rectangle(
                0, 0, LEGEND_SWATCH_SIZE, LEGEND_SWATCH_SIZE,
                fill=color, outline='#555',
            )
            swatch.pack(side=tk.LEFT, padx=(0, LEGEND_SWATCH_GAP))
            tk.Label(item, text=text, font=FONT_LEGEND).pack(side=tk.LEFT)

    # ── Right panel (stacked sections) ─────────────────────────────

    def _build_right_panel(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._build_status_panel(frame).grid(
            row=0, column=0, columnspan=2, sticky="new")

        self._build_allocation_panel(frame).grid(
            row=1, column=0, sticky="new", pady=(PAD_SECTION, 0))

        self._build_construction_panel(frame).grid(
            row=1, column=1, sticky="new",
            pady=(PAD_SECTION, 0), padx=(PAD_SECTION, 0))

        return frame

    # ── Status panel ───────────────────────────────────────────────

    def _build_status_panel(self, parent: tk.Widget) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent, text=" Hive Status ",
            font=FONT_SECTION, padx=PAD_FRAME, pady=PAD_FRAME,
        )

        self._queen_var = tk.StringVar()
        self._queen_value_label = self._add_stat_row(
            frame, "Queen:", self._queen_var, bold_value=True,
        )

        self._eggs_var    = tk.StringVar()
        self._larvae_var  = tk.StringVar()
        self._workers_var = tk.StringVar()
        self._blocks_var  = tk.StringVar()

        for label_text, var in (
            ("Eggs:",    self._eggs_var),
            ("Larvae:",  self._larvae_var),
            ("Workers:", self._workers_var),
            ("Blocks:",  self._blocks_var),
        ):
            self._add_stat_row(frame, label_text, var)

        # Food bar
        self._food_text_var = tk.StringVar()
        self._add_stat_row(frame, "Food:", self._food_text_var)
        self._food_bar = ttk.Progressbar(
            frame, length=CAPACITY_BAR_LENGTH, mode="determinate",
        )
        self._food_bar.pack(fill=tk.X, pady=PAD_LABEL)

        # Brood bar
        self._brood_text_var = tk.StringVar()
        self._add_stat_row(frame, "Brood:", self._brood_text_var)
        self._brood_bar = ttk.Progressbar(
            frame, length=CAPACITY_BAR_LENGTH, mode="determinate",
        )
        self._brood_bar.pack(fill=tk.X, pady=PAD_LABEL)

        self._succession_var = tk.StringVar(value="\u2014")
        self._add_stat_row(frame, "Succession:", self._succession_var)
        self._succession_bar = ttk.Progressbar(
            frame, length=CAPACITY_BAR_LENGTH, mode="determinate",
        )
        self._succession_bar.pack(fill=tk.X, pady=PAD_LABEL)

        return frame

    @staticmethod
    def _add_stat_row(
        parent: tk.Widget,
        label_text: str,
        variable: tk.StringVar,
        *,
        bold_value: bool = False,
    ) -> tk.Label:
        row = tk.Frame(parent)
        row.pack(fill=tk.X, pady=PAD_LABEL)
        tk.Label(
            row, text=label_text, font=FONT_BODY_BOLD,
            width=LABEL_COL_WIDTH, anchor=tk.W,
        ).pack(side=tk.LEFT)
        value_font = FONT_BODY_BOLD if bold_value else FONT_BODY
        value_label = tk.Label(
            row, textvariable=variable, font=value_font,
            width=STATUS_VALUE_WIDTH, anchor=tk.W,
        )
        value_label.pack(side=tk.LEFT)
        return value_label

    # ── Allocation panel ───────────────────────────────────────────

    def _build_allocation_panel(
        self, parent: tk.Widget,
    ) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent, text=" Worker Allocation ",
            font=FONT_SECTION, padx=PAD_FRAME, pady=PAD_FRAME,
        )

        self._auto_var = tk.BooleanVar(value=self._sim.auto_mode)
        self._auto_check = ttk.Checkbutton(
            frame, text=LABEL_AUTO, variable=self._auto_var,
            command=self._on_auto_toggled,
        )
        self._auto_check.pack(anchor=tk.W, pady=(0, PAD_SECTION))

        self._alloc_vars:      Dict[str, tk.StringVar] = {}
        self._alloc_spinboxes: Dict[str, ttk.Spinbox]  = {}

        for task in ALL_TASKS:
            var = tk.StringVar(value=str(self._sim.hive.alloc[task]))
            spinbox = self._add_alloc_spinbox_row(frame, task, var)
            self._alloc_vars[task]      = var
            self._alloc_spinboxes[task] = spinbox

        # Idle count (read-only)
        self._idle_var = tk.StringVar()
        idle_row = tk.Frame(frame)
        idle_row.pack(fill=tk.X, pady=PAD_LABEL)
        tk.Label(
            idle_row, text="(idle):", font=FONT_BODY,
            width=LABEL_COL_WIDTH, anchor=tk.W,
        ).pack(side=tk.LEFT)
        tk.Label(
            idle_row, textvariable=self._idle_var, font=FONT_BODY_BOLD,
            width=SPINBOX_WIDTH, anchor=tk.E,
        ).pack(side=tk.LEFT)

        return frame

    def _add_alloc_spinbox_row(
        self,
        parent: tk.Widget,
        task: str,
        variable: tk.StringVar,
    ) -> ttk.Spinbox:
        row = tk.Frame(parent)
        row.pack(fill=tk.X, pady=PAD_LABEL)
        tk.Label(
            row, text=f"{task}:", font=FONT_BODY,
            width=LABEL_COL_WIDTH, anchor=tk.W,
        ).pack(side=tk.LEFT)
        spinbox = ttk.Spinbox(
            row,
            from_=ALLOC_SPINBOX_MIN,
            to=self._sim.hive.total_workers(),
            textvariable=variable,
            width=SPINBOX_WIDTH,
            command=lambda: self._on_alloc_changed(task),
        )
        spinbox.bind("<Return>",   lambda _: self._on_alloc_changed(task))
        spinbox.bind("<FocusOut>", lambda _: self._on_alloc_changed(task))
        spinbox.pack(side=tk.LEFT)
        return spinbox

    # ── Construction panel ─────────────────────────────────────────

    def _build_construction_panel(
        self, parent: tk.Widget,
    ) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent, text=" Construction ",
            font=FONT_SECTION, padx=PAD_FRAME, pady=PAD_FRAME,
        )

        self._cwork_vars: Dict[str, tk.StringVar]    = {}
        self._cfood_vars: Dict[str, tk.StringVar]    = {}
        self._cwork_bars: Dict[str, ttk.Progressbar] = {}
        self._cfood_bars: Dict[str, ttk.Progressbar] = {}

        for block_type in ("food", "brood", "queen"):
            self._add_construction_block(frame, block_type)

        return frame

    def _add_construction_block(
        self, parent: tk.Widget, block_type: str,
    ) -> None:
        display_name = {'queen': 'Queen Cell'}.get(
            block_type, f"{block_type.capitalize()} Block")
        tk.Label(
            parent, text=display_name,
            font=FONT_BODY_BOLD,
        ).pack(anchor=tk.W, pady=(PAD_LABEL, 0))

        wv, wb = self._add_progress_row(parent, "Work:", BUILD_WORK_TICKS)
        fv, fb = self._add_progress_row(parent, "Food:", BUILD_FOOD_REQUIRED)

        self._cwork_vars[block_type] = wv
        self._cwork_bars[block_type] = wb
        self._cfood_vars[block_type] = fv
        self._cfood_bars[block_type] = fb

    @staticmethod
    def _add_progress_row(
        parent: tk.Widget, label_text: str, maximum: int,
    ) -> Tuple[tk.StringVar, ttk.Progressbar]:
        row = tk.Frame(parent)
        row.pack(fill=tk.X, pady=PAD_LABEL, padx=(PAD_FRAME, 0))
        tk.Label(
            row, text=label_text, font=FONT_BODY,
            width=CONSTRUCTION_LABEL_WIDTH, anchor=tk.W,
        ).pack(side=tk.LEFT)
        var = tk.StringVar()
        tk.Label(
            row, textvariable=var, font=FONT_BODY,
            width=VALUE_COL_WIDTH,
        ).pack(side=tk.LEFT)
        bar = ttk.Progressbar(
            row, length=CONSTRUCTION_BAR_LENGTH,
            mode="determinate", maximum=maximum,
        )
        bar.pack(side=tk.LEFT, padx=PAD_INNER)
        return var, bar

    # ── Event log panel ────────────────────────────────────────────

    def _build_log_panel(self, parent: tk.Widget) -> tk.LabelFrame:
        frame = tk.LabelFrame(
            parent, text=" Event Log ",
            font=FONT_SECTION, padx=PAD_FRAME, pady=PAD_FRAME,
        )

        self._log_text = tk.Text(
            frame,
            height=LOG_VISIBLE_LINES,
            width=LOG_WIDGET_CHARS,
            font=FONT_MONO,
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_FG,
            state=tk.DISABLED,
            wrap=tk.NONE,
        )
        scrollbar = ttk.Scrollbar(
            frame, orient=tk.VERTICAL, command=self._log_text.yview,
        )
        self._log_text.configure(yscrollcommand=scrollbar.set)

        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        return frame

    # ── Controls panel (bottom) ────────────────────────────────────

    def _build_controls_panel(self, parent: tk.Widget) -> tk.Frame:
        frame = tk.Frame(parent)

        controls_row = tk.Frame(frame)
        controls_row.pack(fill=tk.X, pady=(0, PAD_LABEL))

        self._pause_button = ttk.Button(
            controls_row, text=LABEL_PAUSE,
            width=CONTROL_BUTTON_WIDTH, command=self._on_toggle_pause,
        )
        self._pause_button.pack(side=tk.LEFT, padx=(0, PAD_INNER))

        ttk.Button(
            controls_row, text=LABEL_STEP,
            width=CONTROL_BUTTON_WIDTH, command=self._on_step,
        ).pack(side=tk.LEFT, padx=(0, PAD_INNER))

        ttk.Button(
            controls_row, text=LABEL_RESET,
            width=CONTROL_BUTTON_WIDTH, command=self._on_reset,
        ).pack(side=tk.LEFT, padx=(0, PAD_HEADER_GAP))

        tk.Label(
            controls_row, text=LABEL_RATE, font=FONT_BODY_BOLD,
        ).pack(side=tk.LEFT, padx=(0, PAD_INNER))

        self._rate_value_var = tk.StringVar(
            value=self._format_rate(self._sim.tick_rate),
        )

        self._rate_scale = ttk.Scale(
            controls_row,
            from_=MIN_TICK_RATE,
            to=MAX_TICK_RATE,
            orient=tk.HORIZONTAL,
            length=RATE_SLIDER_LENGTH,
            command=self._on_rate_changed,
        )
        self._rate_scale.set(self._sim.tick_rate)
        self._rate_scale.pack(side=tk.LEFT, padx=(0, PAD_INNER))

        tk.Label(
            controls_row, textvariable=self._rate_value_var,
            font=FONT_BODY, width=RATE_LABEL_WIDTH, anchor=tk.W,
        ).pack(side=tk.LEFT)

        # Status bar
        self._status_var = tk.StringVar(value=STATUS_INITIAL)
        tk.Label(
            frame, textvariable=self._status_var, font=FONT_STATUS,
            anchor=tk.W, fg=COLOR_STATUS_FG,
        ).pack(fill=tk.X)

        return frame

    # ================================================================
    # Refresh helpers
    # ================================================================

    def _refresh_header(self) -> None:
        hive = self._sim.hive
        self._tick_var.set(f"Tick: {hive.tick_count}")
        self._rate_header_var.set(self._format_rate(self._sim.tick_rate))

        if self._sim.auto_mode:
            self._mode_var.set("[AUTO]")
            self._mode_label.config(fg=COLOR_MODE_AUTO)
        else:
            self._mode_var.set("[MANUAL]")
            self._mode_label.config(fg=COLOR_MODE_MANUAL)

        if self._sim.paused:
            self._state_var.set("[PAUSED]")
            self._state_label.config(fg=COLOR_PAUSED)
        else:
            self._state_var.set("")

    def _refresh_status(self) -> None:
        hive = self._sim.hive

        if hive.queen_alive:
            age_pct = int(100 * hive.queen_age / QUEEN_LIFESPAN)
            queen_text = (
                f"ALIVE  age {age_pct}%  "
                f"(hunger {hive.queen_hunger}/{QUEEN_EAT_INTERVAL})"
            )
            self._queen_value_label.config(fg=COLOR_QUEEN_ALIVE)
        else:
            queen_text = "*** DEAD ***"
            self._queen_value_label.config(fg=COLOR_QUEEN_DEAD)
        self._queen_var.set(queen_text)

        self._eggs_var.set(str(len(hive.eggs)))
        self._larvae_var.set(str(len(hive.larvae)))
        self._workers_var.set(
            f"{hive.total_workers()}  "
            f"({len(hive.workers)} in, {len(hive.foragers)} out)"
        )
        self._blocks_var.set(
            f"{hive.food_blocks} food + {hive.brood_blocks} brood"
        )

        food_cap = hive.food_capacity()
        self._food_text_var.set(
            f"{hive.food} / {food_cap}  ({hive.food_space()} free)"
        )
        self._food_bar.config(
            maximum=max(food_cap, MIN_PROGRESS_MAXIMUM), value=hive.food,
        )

        brood_cap = hive.brood_capacity()
        self._brood_text_var.set(
            f"{hive.brood_used()} / {brood_cap}  "
            f"({hive.brood_space()} free)"
        )
        self._brood_bar.config(
            maximum=max(brood_cap, MIN_PROGRESS_MAXIMUM),
            value=hive.brood_used(),
        )

        # Succession
        succ_val, succ_max = 0, 1
        if hive.old_queen is not None:
            self._succession_var.set("Old queen abandoned")
        elif hive.succession_started:
            qcell = hive.grid.queen_brood_cell()
            building = hive.grid.active_build_site(CellType.QUEEN_BROOD)
            if qcell and qcell.larvae:
                larva = qcell.larvae[0]
                succ_val, succ_max = larva.age, QUEEN_LARVA_GROW_TICKS
                pct = int(100 * succ_val / max(1, succ_max))
                self._succession_var.set(
                    f"Queen larva developing  ({pct}%)")
            elif qcell and qcell.eggs:
                egg = qcell.eggs[0]
                succ_val, succ_max = egg.age, QUEEN_EGG_HATCH_TICKS
                pct = int(100 * succ_val / max(1, succ_max))
                self._succession_var.set(
                    f"Queen egg incubating  ({pct}%)")
            elif qcell:
                self._succession_var.set("Awaiting queen egg")
            elif building:
                self._succession_var.set("Building queen cell")
            else:
                self._succession_var.set("Preparing succession")
        else:
            self._succession_var.set("\u2014")
        self._succession_bar.config(
            maximum=max(succ_max, MIN_PROGRESS_MAXIMUM), value=succ_val,
        )

    def _refresh_allocation(self) -> None:
        hive = self._sim.hive

        if self._sim.auto_mode:
            for task in ALL_TASKS:
                self._alloc_vars[task].set(str(hive.alloc[task]))

        self._idle_var.set(str(hive.idle_workers()))
        self._update_alloc_limits()

        spin_state = "disabled" if self._sim.auto_mode else "normal"
        for spinbox in self._alloc_spinboxes.values():
            spinbox.config(state=spin_state)

        self._auto_var.set(self._sim.auto_mode)

    def _update_alloc_limits(self) -> None:
        hive = self._sim.hive
        total = hive.total_workers()
        for task in ALL_TASKS:
            other_sum = sum(hive.alloc[t] for t in ALL_TASKS if t != task)
            upper = max(ALLOC_SPINBOX_MIN, total - other_sum)
            self._alloc_spinboxes[task].config(to=upper)

    def _refresh_construction(self) -> None:
        hive = self._sim.hive
        for block_type in ("food", "brood", "queen"):
            work_done  = hive.build_progress[block_type]
            food_spent = hive.build_food_used[block_type]
            self._cwork_vars[block_type].set(
                f"{work_done}/{BUILD_WORK_TICKS}")
            self._cfood_vars[block_type].set(
                f"{food_spent}/{BUILD_FOOD_REQUIRED}")
            self._cwork_bars[block_type].config(value=work_done)
            self._cfood_bars[block_type].config(value=food_spent)

    def _refresh_controls(self) -> None:
        pause_text = LABEL_RESUME if self._sim.paused else LABEL_PAUSE
        self._pause_button.config(text=pause_text)
        self._rate_value_var.set(self._format_rate(self._sim.tick_rate))

    def _sync_log(self) -> None:
        hive_log = self._sim.hive.log
        if hive_log == self._last_log_snapshot:
            return
        self._last_log_snapshot = list(hive_log)
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete(TEXT_START_INDEX, tk.END)
        for entry in hive_log:
            self._log_text.insert(tk.END, entry + "\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ================================================================
    # Formatting helpers
    # ================================================================

    @staticmethod
    def _format_rate(rate: float) -> str:
        rounded = round(rate, RATE_PRECISION)
        return f"{rounded:.{RATE_PRECISION}f} tps"

    def _clear_log_widget(self) -> None:
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete(TEXT_START_INDEX, tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ================================================================
    # Canvas hover
    # ================================================================

    def _on_cell_hover(self, gx: int, gy: int) -> None:
        cell = self._sim.hive.grid.cell_at((gx, gy))
        if cell is None:
            self._cell_info_var.set(INFO_DEFAULT)
            return

        parts: List[str] = [f"({gx},{gy}) {cell.cell_type.value}"]

        if cell.cell_type == CellType.FOOD:
            parts.append(f"food: {cell.food}/{CELL_FOOD_CAPACITY}")
        elif cell.cell_type in (CellType.BROOD, CellType.QUEEN_BROOD):
            prefix = "queen " if cell.cell_type == CellType.QUEEN_BROOD else ""
            parts.append(
                f"{prefix}eggs: {len(cell.eggs)}  "
                f"{prefix}larvae: {len(cell.larvae)}")
        elif cell.cell_type in (CellType.BUILD_FOOD, CellType.BUILD_BROOD,
                                CellType.BUILD_QUEEN_BROOD):
            parts.append(
                f"work: {cell.build_progress}/{BUILD_WORK_TICKS}")
            parts.append(
                f"food: {cell.build_food_used}/{BUILD_FOOD_REQUIRED}")
        elif cell.cell_type == CellType.ENTRANCE:
            parts.append(f"{len(self._sim.hive.foragers)} foragers out")
        elif cell.cell_type == CellType.QUEEN:
            hive = self._sim.hive
            alive = "alive" if hive.queen_alive else "DEAD"
            age_pct = int(100 * hive.queen_age / QUEEN_LIFESPAN)
            parts.append(
                f"{alive}  age: {age_pct}%  hunger: {hive.queen_hunger}")

        bees_here = sum(
            1 for b in self._sim.hive.bees
            if b.state != BeeState.OUTSIDE
            and int(round(b.x)) == gx
            and int(round(b.y)) == gy
        )
        if bees_here > 0:
            parts.append(f"bees: {bees_here}")

        self._cell_info_var.set("  \u2502  ".join(parts))

    # ================================================================
    # Timer
    # ================================================================

    def _schedule_tick(self) -> None:
        self._root.after(TICK_POLL_INTERVAL_MS, self._on_tick_timer)

    def _on_tick_timer(self) -> None:
        if not self._running:
            return

        if not self._sim.paused and self._sim.tick_rate > 0:
            now = time.time()
            interval = 1.0 / self._sim.tick_rate
            ticks_done = 0
            while (now - self._last_tick_time >= interval
                   and ticks_done < MAX_TICKS_PER_POLL):
                self._sim.step()
                self._last_tick_time += interval
                ticks_done += 1
            if ticks_done > 0:
                self.refresh_display()
        else:
            # Reset so un-pausing doesn't cause a burst of catch-up.
            self._last_tick_time = time.time()

        self._schedule_tick()

    # ================================================================
    # Control callbacks
    # ================================================================

    def _on_toggle_pause(self) -> None:
        self._sim.paused = not self._sim.paused
        self._refresh_controls()
        self.set_status(STATUS_PAUSED if self._sim.paused else STATUS_RESUMED)

    def _on_step(self) -> None:
        self._sim.step()
        self.refresh_display()
        self.set_status(STATUS_STEPPED)

    def _on_reset(self) -> None:
        self._sim.reset()
        self._last_tick_time = time.time()
        self._last_log_snapshot = []
        self._clear_log_widget()
        self._rate_scale.set(self._sim.tick_rate)
        self._hive_canvas.reset()
        for task in ALL_TASKS:
            self._alloc_vars[task].set(str(self._sim.hive.alloc[task]))
        self.refresh_display()
        self.set_status(STATUS_RESET)

    def _on_rate_changed(self, value_str: str) -> None:
        try:
            raw = float(value_str)
        except ValueError:
            return
        self._sim.tick_rate = round(raw, RATE_PRECISION)
        self._rate_value_var.set(self._format_rate(self._sim.tick_rate))
        self._rate_header_var.set(self._format_rate(self._sim.tick_rate))

    def _on_auto_toggled(self) -> None:
        self._sim.auto_mode = self._auto_var.get()
        self._refresh_allocation()
        self.set_status(
            STATUS_AUTO_ON if self._sim.auto_mode else STATUS_AUTO_OFF,
        )

    def _on_alloc_changed(self, task: str) -> None:
        if self._sim.auto_mode:
            return

        raw = self._alloc_vars[task].get()
        try:
            desired = int(raw)
        except ValueError:
            self._alloc_vars[task].set(str(self._sim.hive.alloc[task]))
            self.set_status(STATUS_ALLOC_INVALID)
            return

        desired = max(ALLOC_SPINBOX_MIN, desired)

        hive = self._sim.hive
        other_sum = sum(hive.alloc[t] for t in ALL_TASKS if t != task)
        available = max(ALLOC_SPINBOX_MIN, hive.total_workers() - other_sum)
        clamped = min(desired, available)

        hive.alloc[task] = clamped
        self._alloc_vars[task].set(str(clamped))
        self._idle_var.set(str(hive.idle_workers()))
        self._update_alloc_limits()

        if clamped < desired:
            self.set_status(STATUS_ALLOC_CAPPED.format(
                task=task, value=clamped, available=available,
            ))

    # ── Window lifecycle ───────────────────────────────────────────

    def _on_window_close(self) -> None:
        self._running = False
        self._sim.should_quit = True
        self._root.destroy()


# ============================================================================
# Module-level entry point
# ============================================================================

def launch(simulator: Simulator) -> None:
    """Create a :class:`HiveUI` and enter the Tk main loop.

    This is the single entry point called by ``hive.main()``.
    """
    app = HiveUI(simulator)
    app.launch()