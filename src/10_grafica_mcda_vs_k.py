# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ==========================================
# 1. CONSTANTES Y RUTAS
# ==========================================
BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_INFORME   = os.path.join(BASE_DIR, "outputs", "csv", "Informe_Final_Red.csv")
DIR_FIGURAS    = os.path.join(BASE_DIR, "outputs", "figuras")
os.makedirs(DIR_FIGURAS, exist_ok=True)

COLOR_NORMAL  = "#4A90D9"
COLOR_MAXIMO  = "#E8472A"
COLOR_REF     = "#AAAAAA"

# ==========================================
# 2. CARGA Y FILTRADO DE DATOS
# ==========================================
df = pd.read_csv(RUTA_INFORME)

# Ganadores oficiales K=1..8 (excluye la línea de control manual)
df_ganadores = df[df['modo'].str.startswith("Ganador")].copy()
df_ganadores['K'] = df_ganadores['n_depots'].astype(int)
df_ganadores = df_ganadores.sort_values('K').reset_index(drop=True)

# Línea de referencia: mejor escenario K=1 ya está en df_ganadores (Amazon_SVQ1)
# Añadimos también DQA4 como punto de referencia separado
df_control = df[df['modo'] == "Control Manual (DQA4)"].copy()

K_vals     = df_ganadores['K'].tolist()
scores     = df_ganadores['mcda_puntuacion'].tolist()
labels     = [f"K={k}" for k in K_vals]
idx_max    = int(np.argmax(scores))
score_max  = scores[idx_max]
k_max      = K_vals[idx_max]

colores = [COLOR_MAXIMO if i == idx_max else COLOR_NORMAL for i in range(len(K_vals))]

print(f"Datos cargados: {len(K_vals)} escenarios | Maximo: K={k_max} -> {score_max:.2f} pts")

# ==========================================
# 3. FIGURA
# ==========================================
fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor('white')
ax.set_facecolor('#F8F9FA')

bars = ax.bar(labels, scores, color=colores, width=0.6, zorder=3,
              edgecolor='white', linewidth=1.2)

# Valor sobre cada barra
for bar, score in zip(bars, scores):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 1.0,
        f"{score:.2f}",
        ha='center', va='bottom',
        fontsize=10, fontweight='bold',
        color='#333333'
    )

# Línea de referencia DQA4
if not df_control.empty:
    score_dqa4 = float(df_control['mcda_puntuacion'].iloc[0])
    ax.axhline(score_dqa4, color=COLOR_REF, linewidth=1.5, linestyle='--', zorder=2)
    ax.text(len(K_vals) - 0.45, score_dqa4 + 1.5,
            f"DQA4 base: {score_dqa4:.2f}",
            color=COLOR_REF, fontsize=9, ha='right')

# Línea del máximo
ax.axhline(score_max, color=COLOR_MAXIMO, linewidth=1.2,
           linestyle=':', alpha=0.6, zorder=2)

# Rejilla y límites
ax.yaxis.grid(True, linestyle='--', alpha=0.5, color='#CCCCCC', zorder=0)
ax.set_axisbelow(True)
ax.set_ylim(0, min(score_max * 1.18, 105))
ax.spines[['top', 'right']].set_visible(False)
ax.spines[['left', 'bottom']].set_color('#DDDDDD')

# Etiquetas
ax.set_xlabel("Numero de centros logisticos (K)", fontsize=12, labelpad=8, color='#333333')
ax.set_ylabel("Puntuacion MCDA (0-100)", fontsize=12, labelpad=8, color='#333333')
ax.set_title("Score MCDA vs. Numero de centros K", fontsize=14,
             fontweight='bold', pad=14, color='#1a1a1a')
ax.tick_params(axis='both', labelsize=10, colors='#555555')

# Anotación del máximo
ax.annotate(
    f"Optimo: K={k_max}\n({score_max:.2f} pts)",
    xy=(labels[idx_max], score_max),
    xytext=(labels[idx_max], score_max + 6),
    fontsize=9, color=COLOR_MAXIMO, fontweight='bold',
    ha='center',
    arrowprops=dict(arrowstyle='->', color=COLOR_MAXIMO, lw=1.5),
)

# Leyenda
leyenda = [
    mpatches.Patch(color=COLOR_MAXIMO, label=f"Escenario optimo (K={k_max})"),
    mpatches.Patch(color=COLOR_NORMAL, label="Resto de escenarios"),
]
ax.legend(handles=leyenda, fontsize=9, loc='upper left',
          framealpha=0.9, edgecolor='#CCCCCC')

# Nombres de depots en tooltip textual (pie de figura)
depots_max = df_ganadores.loc[df_ganadores['K'] == k_max, 'depot_nombres'].iloc[0]
depots_str = " | ".join([d.replace("_", " ") for d in depots_max.split(" | ")])
fig.text(0.5, 0.01, f"K={k_max}: {depots_str}",
         ha='center', fontsize=8, color='#888888',
         style='italic', wrap=True)

plt.tight_layout(rect=[0, 0.04, 1, 1])

# ==========================================
# 4. GUARDAR
# ==========================================
ruta_png = os.path.join(DIR_FIGURAS, "mcda_score_vs_K.png")
plt.savefig(ruta_png, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()

print(f"[OK] Grafica guardada: {ruta_png}")


# ── Publicar en docs/ ─────────────────────────────────────────────────────────
# El README incrusta la imagen desde docs/assets/.
import shutil as _shutil
_DIR_DOCS = os.path.join(BASE_DIR, "docs", "assets")
os.makedirs(_DIR_DOCS, exist_ok=True)
_origen = os.path.join(DIR_FIGURAS, "mcda_score_vs_K.png")
if os.path.exists(_origen):
    _shutil.copy2(_origen, os.path.join(_DIR_DOCS, "mcda_score_vs_K.png"))
    print("Publicada en docs/assets/mcda_score_vs_K.png")
