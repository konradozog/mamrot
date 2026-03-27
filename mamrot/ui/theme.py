"""Mamrot – Qt dark theme stylesheet & color constants (v4 design)."""

# ── Color palette (from mamrot-ui-v4.jsx) ─────────────────────
BG        = "#0F0F0F"
SURFACE   = "#181818"
SURFACE2  = "#1F1F1F"
SURFACE3  = "#262626"
ELEVATED  = "#2C2C2C"

BORDER       = "rgba(255, 255, 255, 18)"   # ~0.07 alpha
BORDER_HOVER = "rgba(255, 255, 255, 36)"   # ~0.14 alpha
BORDER_FOCUS = "rgba(245, 166, 35, 128)"   # ~0.5 alpha

ACCENT       = "#F5A623"
ACCENT_LIGHT = "#FBC96C"
ACCENT_DIM   = "rgba(245, 166, 35, 26)"    # 0.10 alpha
ACCENT_GLOW  = "rgba(245, 166, 35, 46)"    # 0.18 alpha
ACCENT_TEXT  = "#FCEBD3"

TEXT         = "#E2DDD5"
TEXT2        = "#9B9590"
TEXT3        = "#5C5752"

SUCCESS     = "#7DD3A0"
SUCCESS_DIM = "rgba(125, 211, 160, 26)"
ERROR       = "#E87171"
ERROR_DIM   = "rgba(232, 113, 113, 26)"

HIGHLIGHT_BG = "rgba(245, 166, 35, 46)"   # search highlight
SELECTED_BG  = "rgba(245, 166, 35, 26)"   # queued row

# ── Spacing ───────────────────────────────────────────────────
SP_XS, SP_SM, SP_MD, SP_LG, SP_XL, SP_XXL = 4, 8, 12, 16, 20, 24

# ── Radius ────────────────────────────────────────────────────
R_SM, R_MD, R_LG, R_XL = 6, 8, 10, 12

# ── Legacy aliases (used in existing tab code) ────────────────
BG_DARK = BG
BG_SURFACE = SURFACE
BG_CARD = SURFACE3
BG_ELEVATED = ELEVATED
TEXT_PRIMARY = TEXT
TEXT_SECONDARY = TEXT2
TEXT_MUTED = TEXT3
ACCENT_DIM_SOLID = "#92400E"    # for selection-background fallback

# ── Font family ───────────────────────────────────────────────
FONT_FAMILY = '"DM Sans", "Segoe UI", "SF Pro Text", system-ui, sans-serif'
MONO_FAMILY = '"DM Mono", "SF Mono", Consolas, monospace'


def build_stylesheet() -> str:
    return f"""
    /* ── Base ──────────────────────────────────────── */
    QMainWindow, QWidget {{
        background-color: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}

    /* ── Tab bar (pill-style) ─────────────────────── */
    QTabWidget::pane {{
        border: none;
        background: {BG};
        border-top: 1px solid {BORDER};
    }}
    QTabBar {{
        background: {SURFACE};
        border-bottom: 1px solid {BORDER};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {TEXT3};
        padding: 10px 22px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT_TEXT};
        background: {SURFACE3};
        border-bottom: 2px solid {ACCENT};
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT2};
        background: {SURFACE2};
    }}

    /* ── Group box ────────────────────────────────── */
    QGroupBox {{
        background: {SURFACE2};
        border: 1px solid {BORDER};
        border-radius: {R_XL}px;
        margin-top: 14px;
        padding: 18px 16px 14px 16px;
        font-weight: 600;
        font-size: 11px;
        color: {TEXT3};
        letter-spacing: 1.5px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
    }}

    /* ── Label ────────────────────────────────────── */
    QLabel {{
        color: {TEXT};
        background: transparent;
    }}

    /* ── Input fields ─────────────────────────────── */
    QLineEdit, QComboBox, QSpinBox {{
        background: {SURFACE3};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {R_MD}px;
        padding: 7px 12px;
        font-family: {FONT_FAMILY};
        font-size: 12px;
        selection-background-color: {ACCENT_GLOW};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit::placeholder {{
        color: {TEXT3};
    }}

    /* ── SpinBox arrows ───────────────────────────── */
    QSpinBox {{
        padding-right: 22px;
    }}
    QSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 20px;
        border: none;
        border-left: 1px solid {BORDER};
        border-top-right-radius: {R_MD}px;
        background: {SURFACE3};
    }}
    QSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 20px;
        border: none;
        border-left: 1px solid {BORDER};
        border-bottom-right-radius: {R_MD}px;
        background: {SURFACE3};
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {ELEVATED};
    }}
    QSpinBox::up-arrow {{
        image: none;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-bottom: 4px solid {TEXT2};
        width: 0; height: 0;
    }}
    QSpinBox::down-arrow {{
        image: none;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-top: 4px solid {TEXT2};
        width: 0; height: 0;
    }}

    /* ── ComboBox dropdown ────────────────────────── */
    QComboBox::drop-down {{
        border: none;
        width: 26px;
        padding-right: 4px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT2};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {ELEVATED};
        color: {TEXT};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
        border: 1px solid {BORDER_HOVER};
        border-radius: {R_MD}px;
        padding: 4px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 10px;
        border-radius: {R_SM}px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {SURFACE3};
    }}

    /* ── Buttons ──────────────────────────────────── */
    QPushButton {{
        background: {SURFACE2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {R_MD}px;
        padding: 8px 18px;
        font-weight: 500;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: {SURFACE3};
        border-color: {BORDER_HOVER};
        color: {TEXT};
    }}
    QPushButton:pressed {{
        background: {ELEVATED};
    }}
    QPushButton:disabled {{
        color: {TEXT3};
        background: {SURFACE};
        border-color: {BORDER};
        opacity: 0.4;
    }}
    QPushButton:focus {{
        border-color: {ACCENT};
    }}

    /* ── Primary button ───────────────────────────── */
    QPushButton[accent="true"] {{
        background: {ACCENT};
        color: {BG};
        border: none;
        font-weight: 600;
        padding: 10px 22px;
        border-radius: {R_LG}px;
    }}
    QPushButton[accent="true"]:hover {{
        background: {ACCENT_LIGHT};
    }}
    QPushButton[accent="true"]:pressed {{
        background: {ACCENT};
    }}
    QPushButton[accent="true"]:disabled {{
        background: {TEXT3};
        color: {TEXT3};
    }}

    /* ── Ghost button ─────────────────────────────── */
    QPushButton[ghost="true"] {{
        background: transparent;
        border: none;
        color: {TEXT2};
        padding: 6px 14px;
    }}
    QPushButton[ghost="true"]:hover {{
        background: {SURFACE2};
        color: {TEXT};
    }}

    /* ── Progress bar ─────────────────────────────── */
    QProgressBar {{
        background: {SURFACE3};
        border: none;
        border-radius: 3px;
        height: 5px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT}, stop:1 {ACCENT_LIGHT});
        border-radius: 3px;
    }}

    /* ── Table ────────────────────────────────────── */
    QTableView {{
        background: {SURFACE};
        color: {TEXT};
        border: none;
        gridline-color: transparent;
        selection-background-color: {SELECTED_BG};
        selection-color: {TEXT};
        outline: none;
    }}
    QTableView::item {{
        padding: 6px 10px;
        border-bottom: 1px solid {BORDER};
    }}
    QTableView::item:selected {{
        background: {SELECTED_BG};
    }}
    QTableView::item:hover {{
        background: {SURFACE2};
    }}
    QHeaderView::section {{
        background: {SURFACE};
        color: {TEXT3};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 8px 10px;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.5px;
    }}

    /* ── List widget ──────────────────────────────── */
    QListWidget {{
        background: {SURFACE2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: {R_XL}px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 8px 14px;
        border-radius: {R_MD}px;
    }}
    QListWidget::item:selected {{
        background: {ACCENT_DIM};
        color: {TEXT};
    }}
    QListWidget::item:hover:!selected {{
        background: {SURFACE3};
    }}

    /* ── Scrollbar ────────────────────────────────── */
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        border: none;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {SURFACE3};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {TEXT3};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 6px;
        border: none;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {SURFACE3};
        border-radius: 3px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {TEXT3};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ── Checkbox ─────────────────────────────────── */
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {BORDER_HOVER};
        border-radius: 4px;
        background: {SURFACE3};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:hover {{
        border-color: {TEXT2};
    }}

    /* ── Tooltip ──────────────────────────────────── */
    QToolTip {{
        background: {ELEVATED};
        color: {TEXT};
        border: 1px solid {BORDER_HOVER};
        padding: 6px 10px;
        border-radius: {R_SM}px;
        font-size: 11px;
    }}

    /* ── Status bar ───────────────────────────────── */
    QStatusBar {{
        background: {SURFACE};
        color: {TEXT3};
        border-top: 1px solid {BORDER};
        font-size: 11px;
    }}

    /* ── Slider ───────────────────────────────────── */
    QSlider::groove:horizontal {{
        background: {SURFACE3};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {ACCENT};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        border: none;
    }}
    QSlider::handle:horizontal:hover {{
        background: {ACCENT_LIGHT};
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: 2px;
    }}
    """
