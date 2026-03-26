# b3mc PySide6 Theme Reference

Dark theme used across all b3mc GUI widgets.  Copy these values when building
other PySide6 / matplotlib apps that should look consistent.

---

## Colours

### Backgrounds
| Role | Hex | RGB |
|---|---|---|
| Window / panel background | `#2d2d2d` | 45, 45, 45 |
| Log pane / deep background | `#1a1a1a` | 26, 26, 26 |
| Legend background | `#333333` | 51, 51, 51 |
| QChart legend brush | `#323232` | 50, 50, 50 |

### Text
| Role | Hex | RGB |
|---|---|---|
| Primary text / chart titles | `#dcdcdc` | 220, 220, 220 |
| Secondary text / axis labels | `#aaaaaa` | 170, 170, 170 |
| Dimmed text / status bar | `#888888` | 136, 136, 136 |
| Tick labels | `#888888` | 136, 136, 136 |
| Tick marks | `#777777` | 119, 119, 119 |
| Log pane text (green-tinted mono) | `#b0c4b0` | 176, 196, 176 |
| QChart title brush | `#969696` | 150, 150, 150 |
| QChart legend text | `#a0a0a0` | 160, 160, 160 |

### Lines and borders
| Role | Hex | RGB |
|---|---|---|
| Grid lines | `#444444` | 68, 68, 68 |
| Grid lines (BEM tab, slightly lighter) | `#555555` | 85, 85, 85 |
| Axis spines / edges | `#555555` | 85, 85, 85 |
| Axis line pen (QChart) | `#787878` | 120, 120, 120 |
| Legend border | `#444444` | 68, 68, 68 |

### Data colours
| Role | Hex / RGB | Notes |
|---|---|---|
| Primary line (spline chart) | `#64b96e` / RGB(100, 185, 110) | Light green |
| Control points | RGB(70, 130, 180) | Steel blue |
| Selected control point | Qt red | |
| Overlay / reference line | `#aaaaaa` | Dashed |
| Primary data line (BEM/ANBA) | `#4682b4` | Steel blue |
| Stiffness plots | `#4a9eca` | |
| Mass matrix plots | `#e07b50` | |
| Flapwise moment | `#4682b4` | |
| Edgewise moment | `#dc8c28` | |
| Combined RMS | `#6ab04c` | |
| Total / summary line | `#aaaaaa` dashed | |
| Bar chart total bar | `#ffffff` | |
| Section mesh material colours | `tab10` cmap | |

---

## Typography

### Fonts (preference order)
```
Liberation Sans, DejaVu Sans, Arial, Helvetica
```
Used for both Qt widgets (QFont) and matplotlib (`rcParams["font.sans-serif"]`).

### Font sizes
| Context | Size |
|---|---|
| matplotlib default (`rcParams["font.size"]`) | 8 pt |
| QChart title | 8 pt, Normal weight |
| QChart axis labels / tick labels | 7 pt |
| QChart legend | 7 pt |
| matplotlib axis labels | 8 pt |
| matplotlib tick labels | 7 pt |
| matplotlib legend | 7 pt |
| Log pane (monospace) | 11 px |
| Toolbar close button | 18 px |

---

## QChart (PySide6.QtCharts)

```python
chart.setTheme(QChart.ChartTheme.ChartThemeDark)
chart.setBackgroundBrush(QColor(45, 45, 45))
chart.setPlotAreaBackgroundBrush(QColor(45, 45, 45))
chart.setPlotAreaBackgroundVisible(True)
chart.setTitleBrush(QColor(150, 150, 150))
chart.setMargins(QMargins(4, 4, 4, 4))

legend = chart.legend()
legend.setVisible(False)          # hidden by default; show per-chart if needed
legend.setColor(QColor(160, 160, 160))
legend.setBrush(QColor(50, 50, 50))
legend.setFont(QFont("Liberation Sans", 7))

# Per axis:
axis.setTitleFont(QFont("Liberation Sans", 7))
axis.setLabelsFont(QFont("Liberation Sans", 7))
axis.setLabelsColor(QColor(120, 120, 120))
axis.setTitleBrush(QColor(120, 120, 120))
axis.setGridLineColor(QColor(68, 68, 68))
axis.setLinePenColor(QColor(120, 120, 120))
```

---

## Matplotlib (embedded FigureCanvasQTAgg)

### rcParams (set once at module level)
```python
import matplotlib as mpl
mpl.rcParams["font.family"] = "sans-serif"
mpl.rcParams["font.sans-serif"] = ["Liberation Sans", "DejaVu Sans", "Arial", "Helvetica"]
mpl.rcParams["font.size"] = 8
```

### Canvas widget
```python
class _Canvas(FigureCanvasQTAgg):
    def __init__(self, figsize=(10, 4)):
        self.fig = Figure(figsize=figsize, tight_layout=True)
        super().__init__(self.fig)
        self.fig.patch.set_facecolor("#2d2d2d")
        self.setStyleSheet("background-color: #2d2d2d;")
```

### Axes style helper
```python
def _style_ax(ax):
    ax.set_facecolor("#2d2d2d")
    ax.grid(color="#444", linewidth=0.5)
    ax.tick_params(colors="#777", labelcolor="#888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#555")
    ax.xaxis.label.set_color("#888")
    ax.yaxis.label.set_color("#888")
    ax.title.set_color("#aaa")
    ax.title.set_fontweight("normal")

def _style_legend(ax):
    legend = ax.get_legend()
    if legend:
        legend.get_frame().set_facecolor("#333")
        legend.get_frame().set_edgecolor("#444")
        for text in legend.get_texts():
            text.set_color("#999")
```

### rcParams dict (for one-shot apply with `plt.rcParams.update`)
```python
MPL_DARK = {
    "figure.facecolor": "#2d2d2d",
    "axes.facecolor":   "#2d2d2d",
    "axes.edgecolor":   "#888888",
    "axes.labelcolor":  "#888888",
    "text.color":       "#dcdcdc",
    "xtick.color":      "#aaaaaa",
    "ytick.color":      "#aaaaaa",
    "grid.color":       "#444444",
    "grid.linewidth":   0.5,
    "legend.facecolor": "#333333",
    "legend.edgecolor": "#444444",
}
```

---

## Layout

### Main window
- Initial size: `1400 × 900` px
- Horizontal splitter (forms | plot+log): `[480, 700]`
- Vertical splitter (plots | log): `[500, 200]`

### Margins and spacing
| Context | Value |
|---|---|
| Tab layouts (tight panels) | `setContentsMargins(0, 0, 0, 0)` |
| Run button bar | `setContentsMargins(4, 4, 4, 4)` |
| About dialog | `setContentsMargins(24, 24, 24, 24)`, spacing 12 |
| Planform grid | `setSpacing(4)` |

### Log pane stylesheet
```css
QPlainTextEdit {
    background: #1a1a1a;
    color: #b0c4b0;
    font-family: monospace;
    font-size: 11px;
    border: none;
}
```

### Toolbar (close button)
```css
QToolBar { border: none; }
QToolButton { font-size: 18px; padding: 2px 8px; }
```

### Status label
```css
padding: 2px 6px; color: #aaa;
```
