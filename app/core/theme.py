"""
All visual constants for the 480x800 portrait display.
Import from here — never hardcode colours or sizes in UI widgets.
"""

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
SCREEN_W = 480
SCREEN_H = 800

# ---------------------------------------------------------------------------
# Colours  (hex strings for use in Qt stylesheets)
# ---------------------------------------------------------------------------
COLOR_BACKGROUND        = "#0a0a0a"
COLOR_PRIMARY_BLUE      = "#1565C0"
COLOR_ACCENT_RED        = "#C62828"
COLOR_CONFIRM_GREEN     = "#2E7D32"
COLOR_DENY_RED          = "#C62828"
COLOR_TEXT_WHITE        = "#FFFFFF"
COLOR_TEXT_SECONDARY    = "#BDBDBD"
COLOR_SURFACE           = "#1E1E1E"   # card / panel background
COLOR_BORDER            = "#333333"
COLOR_TAB_ACTIVE        = "#1565C0"
COLOR_TAB_INACTIVE      = "#2A2A2A"

# ---------------------------------------------------------------------------
# Ripple animation
# ---------------------------------------------------------------------------
RIPPLE_CIRCLE_RADIUS    = 100        # px — radius of solid blue centre circle
RIPPLE_RING_COLOR_R     = 200        # RGB components of expanding rings
RIPPLE_RING_COLOR_G     = 30
RIPPLE_RING_COLOR_B     = 30
RIPPLE_RING_WIDTH       = 2          # pen width in px
RIPPLE_EXPAND_PX        = 4          # px added to radius per timer tick
RIPPLE_FADE_STEP        = 0.03       # opacity subtracted per tick
RIPPLE_SPAWN_TICKS      = 20         # spawn a new ring every N ticks (~600 ms at 30 fps)
RIPPLE_TIMER_MS         = 30         # timer interval in ms (~33 fps)

# ---------------------------------------------------------------------------
# Font sizes  (pt)
# ---------------------------------------------------------------------------
FONT_TITLE  = 28
FONT_BODY   = 18
FONT_SMALL  = 13
FONT_BUTTON = 16
FONT_TABLE  = 14

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
MARGIN          = 16    # px — standard outer margin
PADDING         = 12    # px — inner padding for panels
BUTTON_HEIGHT   = 64    # px — minimum touch target height
BUTTON_RADIUS   = 8     # px — border-radius for buttons
TAB_HEIGHT      = 48    # px — location tab bar height
STATUS_BAR_H    = 32    # px — optional status bar at bottom

# ---------------------------------------------------------------------------
# Stylesheets  (reusable Qt stylesheet fragments)
# ---------------------------------------------------------------------------
STYLE_CONFIRM_BUTTON = f"""
    QPushButton {{
        background-color: {COLOR_CONFIRM_GREEN};
        color: {COLOR_TEXT_WHITE};
        font-size: {FONT_BUTTON}pt;
        font-weight: bold;
        border-radius: {BUTTON_RADIUS}px;
        min-height: {BUTTON_HEIGHT}px;
    }}
    QPushButton:pressed {{
        background-color: #1B5E20;
    }}
"""

STYLE_DENY_BUTTON = f"""
    QPushButton {{
        background-color: {COLOR_DENY_RED};
        color: {COLOR_TEXT_WHITE};
        font-size: {FONT_BUTTON}pt;
        font-weight: bold;
        border-radius: {BUTTON_RADIUS}px;
        min-height: {BUTTON_HEIGHT}px;
    }}
    QPushButton:pressed {{
        background-color: #B71C1C;
    }}
"""

STYLE_NEUTRAL_BUTTON = f"""
    QPushButton {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT_WHITE};
        font-size: {FONT_BUTTON}pt;
        border: 1px solid {COLOR_BORDER};
        border-radius: {BUTTON_RADIUS}px;
        min-height: {BUTTON_HEIGHT}px;
    }}
    QPushButton:pressed {{
        background-color: #3A3A3A;
    }}
"""

STYLE_MAIN_WINDOW = f"""
    QMainWindow, QWidget#root {{
        background-color: {COLOR_BACKGROUND};
    }}
"""

STYLE_TABLE = f"""
    QTableWidget {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT_WHITE};
        font-size: {FONT_TABLE}pt;
        gridline-color: {COLOR_BORDER};
        border: none;
    }}
    QTableWidget::item {{
        padding: 8px;
    }}
    QTableWidget::item:selected {{
        background-color: {COLOR_PRIMARY_BLUE};
    }}
    QHeaderView::section {{
        background-color: {COLOR_BACKGROUND};
        color: {COLOR_TEXT_SECONDARY};
        font-size: {FONT_SMALL}pt;
        padding: 6px;
        border: none;
        border-bottom: 1px solid {COLOR_BORDER};
    }}
"""
