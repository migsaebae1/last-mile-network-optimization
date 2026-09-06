# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import pandas as pd
import folium
from folium.plugins import HeatMap

# ==========================================
# 1. CONSTANTES Y CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# El fichero va incluido en el repositorio bajo outputs/rutas_ganadoras/.
# Si se regenera con 06_rutas_svq1_dqa4.py aparece en outputs/rutas_parejas_generadas/.
_NOMBRE_CSV    = "alianza_pareja_Amazon_SVQ1_y_DQA4.csv"
_CANDIDATAS    = [
    os.path.join(BASE_DIR, "outputs", "rutas_ganadoras", _NOMBRE_CSV),
    os.path.join(BASE_DIR, "outputs", "rutas_parejas_generadas", _NOMBRE_CSV),
]
RUTA_CSV_RUTAS = next((p for p in _CANDIDATAS if os.path.exists(p)), _CANDIDATAS[0])
RUTA_DATOS     = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
DIR_MAPAS      = os.path.join(BASE_DIR, "outputs", "mapas_ganadores")
os.makedirs(DIR_MAPAS, exist_ok=True)

COSTE_KM   = 0.35
COSTE_HORA = 14.0
CO2_KG_KM  = 0.21

COLORES_CENTROS = ['blue', 'green']
COLORES_HEX = {
    'blue':  '#1565C0',
    'green': '#2E7D32',
}

COORDS_DEPOTS = {
    'Amazon_SVQ1': (37.271335, -5.988073),
    'DQA4':        (37.346775, -6.002706),
}

# ==========================================
# 2. CARGA DE DATOS
# ==========================================
print("Cargando datos geograficos...")
df_datos = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
df_datos['Seccion INE'] = df_datos['Seccion INE'].astype(str).str.strip()
dict_clientes = df_datos.set_index('Seccion INE')[['Latitud', 'Longitud']].to_dict('index')

peso_max  = df_datos['Peso'].max()
heat_data = [
    [row['Latitud'], row['Longitud'], row['Peso'] / peso_max]
    for _, row in df_datos.iterrows()
]

print(f"Cargando rutas: {os.path.basename(RUTA_CSV_RUTAS)}...")
df_rutas = pd.read_csv(RUTA_CSV_RUTAS)

centros_activos  = list(df_rutas['Centro_Origen'].unique())
mapa_colores_hub = {c: COLORES_CENTROS[i % len(COLORES_CENTROS)] for i, c in enumerate(centros_activos)}
mapa_hex_hub     = {c: COLORES_HEX[mapa_colores_hub[c]] for c in centros_activos}

# ==========================================
# 3. KPIs GLOBALES Y POR DEPOT
# ==========================================
km_totales       = df_rutas['km_tramo'].sum()
transportistas   = df_rutas['Id_Transportista'].nunique()
tiempo_total_min = df_rutas['tiempo_tramo_min'].sum()
coste_dia        = km_totales * COSTE_KM + (tiempo_total_min / 60.0) * COSTE_HORA
co2_dia          = km_totales * CO2_KG_KM

depot_stats = {}
for centro in centros_activos:
    df_c = df_rutas[df_rutas['Centro_Origen'] == centro]
    depot_stats[centro] = {
        'vans': df_c['Id_Transportista'].nunique(),
        'km':   df_c['km_tramo'].sum(),
    }

# ==========================================
# 4. COORDENADAS FILA A FILA
# ==========================================
lats, lons = [], []
for _, row in df_rutas.iterrows():
    nodo = str(row['nodo_ine'])
    if nodo.startswith("Inicio_") or nodo.startswith("Regreso_"):
        hub_name = nodo.replace("Inicio_", "").replace("Regreso_", "")
        coords   = COORDS_DEPOTS.get(hub_name)
        lats.append(coords[0] if coords else None)
        lons.append(coords[1] if coords else None)
    else:
        info = dict_clientes.get(nodo)
        lats.append(info['Latitud'] if info else None)
        lons.append(info['Longitud'] if info else None)

df_rutas['Latitud']  = lats
df_rutas['Longitud'] = lons
df_rutas = (df_rutas
            .dropna(subset=['Latitud', 'Longitud'])
            .sort_values(['Id_Transportista', 'orden_parada']))

# ==========================================
# 5. PANEL DE KPIs
# ==========================================
filas_depots = ""
for centro in centros_activos:
    hex_c  = mapa_hex_hub[centro]
    vans_c = depot_stats[centro]['vans']
    label  = centro.replace("_", " ")
    filas_depots += (
        f'<tr>'
        f'<td style="padding:2px 6px 2px 0;">'
        f'<span style="display:inline-block;width:11px;height:11px;border-radius:2px;'
        f'background:{hex_c};margin-right:5px;vertical-align:middle;"></span>'
        f'{label}</td>'
        f'<td style="text-align:right;">{vans_c} vans</td>'
        f'</tr>'
    )

panel_html = f"""
<div style="position:fixed;bottom:25px;right:10px;z-index:9999;
     background:white;padding:14px 16px;border:2px solid #ccc;
     border-radius:10px;font-family:Arial,sans-serif;font-size:12px;
     width:260px;box-shadow:3px 3px 8px rgba(0,0,0,0.25);">
  <b style="font-size:13px;color:#1a1a1a;">Escenario: SVQ1 + DQA4</b><br/>
  <span style="color:#666;font-size:11px;">2 depots activos</span>
  <hr style="margin:7px 0;border-color:#e0e0e0;"/>
  <table style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="padding:2px 6px 2px 0;color:#555;">Conductores/dia</td>
      <td style="padding:2px 0;font-weight:bold;text-align:right;">{transportistas}</td>
    </tr>
    <tr>
      <td style="padding:2px 6px 2px 0;color:#555;">Km totales/dia</td>
      <td style="padding:2px 0;text-align:right;">{km_totales:,.0f} km</td>
    </tr>
    <tr>
      <td style="padding:2px 6px 2px 0;color:#555;">Coste routing/dia</td>
      <td style="padding:2px 0;font-weight:bold;text-align:right;">{coste_dia:,.0f} &#8364;</td>
    </tr>
    <tr>
      <td style="padding:2px 6px 2px 0;color:#555;">CO&#8322;/dia</td>
      <td style="padding:2px 0;text-align:right;">{co2_dia:,.0f} kg</td>
    </tr>
  </table>
  <hr style="margin:7px 0;border-color:#e0e0e0;"/>
  <b style="font-size:11px;color:#444;">Depots:</b>
  <table style="width:100%;border-collapse:collapse;margin-top:3px;">
    {filas_depots}
  </table>
  <hr style="margin:7px 0;border-color:#e0e0e0;"/>
  <span style="color:#999;font-size:10px;">Motor greedy VRP</span>
</div>
"""

# ==========================================
# 6. CONSTRUCCIÓN DEL MAPA
# ==========================================
mapa = folium.Map(
    location=[df_rutas['Latitud'].mean(), df_rutas['Longitud'].mean()],
    zoom_start=8,
    tiles="cartodbpositron",
)

mapa.get_root().html.add_child(folium.Element(panel_html))

# Capa 1: HeatMap de demanda
fg_heat = folium.FeatureGroup(name="Demanda (calor)", show=True)
HeatMap(heat_data, radius=14, blur=18, min_opacity=0.25).add_to(fg_heat)
fg_heat.add_to(mapa)

# Capa 2: CircleMarkers de paradas de entrega
fg_paradas = folium.FeatureGroup(name="Paradas de entrega", show=True)
es_entrega = ~df_rutas['nodo_ine'].astype(str).str.startswith(('Inicio_', 'Regreso_'))
for _, row in df_rutas[es_entrega].iterrows():
    hex_c = mapa_hex_hub[row['Centro_Origen']]
    folium.CircleMarker(
        location=[row['Latitud'], row['Longitud']],
        radius=4,
        color=hex_c,
        fill=True,
        fill_color=hex_c,
        fill_opacity=0.75,
        weight=0.5,
        tooltip=(
            f"<div>"
            f"INE: {row['nodo_ine']}<br/>"
            f"Depot: {row['Centro_Origen'].replace('_', ' ')}<br/>"
            f"Van: {row['Id_Transportista']}"
            f"</div>"
        ),
    ).add_to(fg_paradas)
fg_paradas.add_to(mapa)

# Capas 3+: Rutas por depot (PolyLines)
capas_rutas = {
    centro: folium.FeatureGroup(name=f"Rutas -- {centro.replace('_', ' ')}", show=True)
    for centro in centros_activos
}

for t_id, df_van in df_rutas.groupby('Id_Transportista'):
    centro_origen = df_van['Centro_Origen'].iloc[0]
    hex_c         = mapa_hex_hub[centro_origen]
    coords        = df_van[['Latitud', 'Longitud']].values.tolist()
    km_ruta       = df_van['km_tramo'].sum()
    n_paradas     = int(es_entrega[df_van.index].sum())

    folium.PolyLine(
        locations=coords,
        weight=2,
        color=hex_c,
        opacity=0.45,
        tooltip=f"Van {t_id} | {centro_origen.replace('_', ' ')} | {km_ruta:.0f} km | {n_paradas} paradas",
    ).add_to(capas_rutas[centro_origen])

for capa in capas_rutas.values():
    capa.add_to(mapa)

# Marcadores de depot
for centro in centros_activos:
    coords     = COORDS_DEPOTS.get(centro)
    if not coords:
        continue
    color_name = mapa_colores_hub[centro]
    label      = centro.replace("_", " ")
    vans_c     = depot_stats[centro]['vans']
    km_c       = depot_stats[centro]['km']
    folium.Marker(
        location=list(coords),
        popup=folium.Popup(
            f"<b>{label}</b><br/>Vans: {vans_c}<br/>Km/dia: {km_c:,.0f}",
            max_width=220,
        ),
        tooltip=f"DEPOT: {label}",
        icon=folium.Icon(color=color_name, icon="building", prefix="fa"),
    ).add_to(mapa)

folium.LayerControl(collapsed=False).add_to(mapa)

# ==========================================
# 7. GUARDAR
# ==========================================
nombre_salida = "mapa_interactivo_SVQ1_DQA4.html"
ruta_salida   = os.path.join(DIR_MAPAS, nombre_salida)
mapa.save(ruta_salida)
print(f"\n[OK] -> {nombre_salida}")
print(f"  Conductores: {transportistas} | Km: {km_totales:,.0f} | Coste: {coste_dia:,.0f} EUR/dia")
print(f"  Guardado en: {os.path.abspath(ruta_salida)}")


# ── Publicar en docs/ ─────────────────────────────────────────────────────────
import shutil as _shutil
_DIR_DOCS = os.path.join(BASE_DIR, "docs", "mapas")
os.makedirs(_DIR_DOCS, exist_ok=True)
for _f in os.listdir(DIR_MAPAS):
    if _f == "mapa_interactivo_SVQ1_DQA4.html":
        _shutil.copy2(os.path.join(DIR_MAPAS, _f), os.path.join(_DIR_DOCS, _f))
        print("Publicado en docs/mapas/" + _f)
