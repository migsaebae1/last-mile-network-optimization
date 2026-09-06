# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import glob
import pandas as pd
import folium
from folium.plugins import HeatMap

# ==========================================
# 1. CONSTANTES Y CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ruta_abs(p):
    """Resuelve una ruta del CSV de campeones contra la raiz del repositorio.

    Las rutas se guardan en relativo para no filtrar rutas absolutas al CSV
    versionado; anclarlas a BASE_DIR permite ejecutar el script desde
    cualquier directorio de trabajo.
    """
    p = str(p)
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)

RUTA_ENTRADA_RESUMEN = os.path.join(BASE_DIR, "outputs", "campeones_tecnicos_red.csv")
RUTA_DATOS          = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
RUTA_CANDIDATOS     = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
DIR_MAPAS_SALIDA    = os.path.join(BASE_DIR, "outputs", "mapas_ganadores")
os.makedirs(DIR_MAPAS_SALIDA, exist_ok=True)

# KPI económicos (mismos que el resto del proyecto)
COSTE_KM   = 0.35   # €/km
COSTE_HORA = 14.0   # €/h conductor
CO2_KG_KM  = 0.21  # kg CO₂/km (furgoneta diésel media)

# Paleta Folium + hex equivalente para el panel HTML
COLORES_CENTROS = ['blue', 'green', 'orange', 'purple', 'red', 'cadetblue', 'darkred', 'darkblue']
COLORES_HEX = {
    'blue':      '#1565C0',
    'green':     '#2E7D32',
    'orange':    '#E65100',
    'purple':    '#6A1B9A',
    'red':       '#C62828',
    'cadetblue': '#006064',
    'darkred':   '#7B1FA2',
    'darkblue':  '#0D47A1',
}

# Coordenadas conocidas de estaciones Amazon (no están en candidatos_filtrados)
COORDS_CONOCIDAS = {
    'amazon_svq1': (37.2733, -5.9235),
    'svq1':        (37.2733, -5.9235),
    'amazon_dqa4': (37.3924, -5.9803),
    'dqa4':        (37.3924, -5.9803),
}


def normalizar_texto(texto):
    return str(texto).strip().lower()


def nombre_display(centro, max_len=32):
    """Convierte el slug del CSV a texto legible para mostrar en el mapa."""
    return centro.replace("_", " ")[:max_len]


# ==========================================
# 2. CARGA GLOBAL DE DATOS GEOGRÁFICOS
# ==========================================
print("Cargando coordenadas globales...")

if not os.path.exists(RUTA_ENTRADA_RESUMEN):
    raise FileNotFoundError(
        f"No se encuentra el archivo del torneo: {RUTA_ENTRADA_RESUMEN}\n"
        "Ejecuta primero el script del torneo tecnico."
    )

# Secciones INE (clientes)
df_datos = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
df_datos['Seccion INE'] = df_datos['Seccion INE'].astype(str).str.strip()
dict_clientes = df_datos.set_index('Seccion INE')[['Latitud', 'Longitud']].to_dict('index')

# Datos del HeatMap: [lat, lon, peso_normalizado]
peso_max = df_datos['Peso'].max()
heat_data = [
    [row['Latitud'], row['Longitud'], row['Peso'] / peso_max]
    for _, row in df_datos.iterrows()
]

# Candidatos industriales — doble índice: nombre exacto y normalizado
df_cand = pd.read_csv(RUTA_CANDIDATOS, encoding='utf-8', encoding_errors='replace')
dict_centros_exact = {}
dict_centros_norm  = {}
for _, row in df_cand.iterrows():
    nombre = str(row['Nombre'])
    coords = (float(row['Latitud']), float(row['Longitud']))
    dict_centros_exact[nombre]                    = coords
    dict_centros_norm[normalizar_texto(nombre)]   = coords

df_campeones = pd.read_csv(RUTA_ENTRADA_RESUMEN)


def buscar_coords_depot(centro):
    """Devuelve (lat, lon) del depot: exacto → normalizado → conocidos → None."""
    if centro in dict_centros_exact:
        return dict_centros_exact[centro]
    norm = normalizar_texto(centro)
    if norm in dict_centros_norm:
        return dict_centros_norm[norm]
    if norm in COORDS_CONOCIDAS:
        return COORDS_CONOCIDAS[norm]
    return None


# ==========================================
# 3. BUCLE DE GENERACIÓN DE MAPAS
# ==========================================
print(f"Procesando {len(df_campeones)} escenarios campeones...\n")

for idx, fila in df_campeones.iterrows():
    categoria         = fila['Categoria']
    nombre_csv        = fila['Archivo']
    ruta_csv          = _ruta_abs(fila['Ruta_Completa'])
    km_totales        = float(fila['KM_Totales'])
    transportistas    = int(fila['Transportistas'])
    tiempo_total_min  = float(fila['Tiempo_Total_Mins'])

    coste_dia = km_totales * COSTE_KM + (tiempo_total_min / 60.0) * COSTE_HORA
    co2_dia   = km_totales * CO2_KG_KM

    print(f"[{categoria}] Leyendo: {nombre_csv}")

    # Localizar CSV de rutas
    if not os.path.exists(ruta_csv):
        patron = os.path.join(BASE_DIR, "outputs", "**", nombre_csv)
        encontrados = glob.glob(patron, recursive=True)
        if encontrados:
            ruta_csv = encontrados[0]
        else:
            print(f"  [ERROR] No se localiza {nombre_csv}. Saltando.")
            continue

    df_rutas = pd.read_csv(ruta_csv)
    centros_activos   = list(df_rutas['Centro_Origen'].unique())
    mapa_colores_hub  = {c: COLORES_CENTROS[i % len(COLORES_CENTROS)] for i, c in enumerate(centros_activos)}
    mapa_hex_hub      = {c: COLORES_HEX[mapa_colores_hub[c]] for c in centros_activos}

    # KPIs por depot
    depot_stats = {}
    for centro in centros_activos:
        df_c = df_rutas[df_rutas['Centro_Origen'] == centro]
        depot_stats[centro] = {
            'vans': df_c['Id_Transportista'].nunique(),
            'km':   df_c['km_tramo'].sum(),
        }

    # Inyectar coordenadas fila a fila
    lats, lons = [], []
    for _, row in df_rutas.iterrows():
        nodo = str(row['nodo_ine'])
        if nodo.startswith("Inicio_") or nodo.startswith("Regreso_"):
            hub_name = nodo.replace("Inicio_", "").replace("Regreso_", "")
            coords = buscar_coords_depot(hub_name)
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

    # ----------------------------------------------------------
    # PANEL DE KPIs (fijo esquina inferior-derecha, estilo referencia)
    # ----------------------------------------------------------
    filas_depots = ""
    for centro in centros_activos:
        hex_c  = mapa_hex_hub[centro]
        vans_c = depot_stats[centro]['vans']
        label  = nombre_display(centro)
        filas_depots += (
            f'<tr>'
            f'<td style="padding:2px 6px 2px 0;">'
            f'<span style="display:inline-block;width:11px;height:11px;border-radius:2px;'
            f'background:{hex_c};margin-right:5px;vertical-align:middle;"></span>'
            f'{label}</td>'
            f'<td style="text-align:right;">{vans_c} vans</td>'
            f'</tr>'
        )

    n_depots  = len(centros_activos)
    subtitulo = f"{n_depots} depot{'s' if n_depots > 1 else ''} activo{'s' if n_depots > 1 else ''}"

    panel_html = f"""
    <div style="position:fixed;bottom:25px;right:10px;z-index:9999;
         background:white;padding:14px 16px;border:2px solid #ccc;
         border-radius:10px;font-family:Arial,sans-serif;font-size:12px;
         width:260px;box-shadow:3px 3px 8px rgba(0,0,0,0.25);">
      <b style="font-size:13px;color:#1a1a1a;">Escenario: {categoria}</b><br/>
      <span style="color:#666;font-size:11px;">{subtitulo}</span>
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

    # ----------------------------------------------------------
    # MAPA BASE
    # ----------------------------------------------------------
    mapa = folium.Map(
        location=[df_rutas['Latitud'].mean(), df_rutas['Longitud'].mean()],
        zoom_start=8,
        tiles="cartodbpositron",
    )

    # Inyectar panel KPIs en el body del HTML
    mapa.get_root().html.add_child(folium.Element(panel_html))

    # ----------------------------------------------------------
    # CAPA 1: HeatMap de demanda
    # ----------------------------------------------------------
    fg_heat = folium.FeatureGroup(name="Demanda (calor)", show=True)
    HeatMap(heat_data, radius=14, blur=18, min_opacity=0.25).add_to(fg_heat)
    fg_heat.add_to(mapa)

    # ----------------------------------------------------------
    # CAPA 2: CircleMarkers de paradas de entrega
    # ----------------------------------------------------------
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
                f"Depot: {nombre_display(row['Centro_Origen'])}<br/>"
                f"Van: {row['Id_Transportista']}"
                f"</div>"
            ),
        ).add_to(fg_paradas)
    fg_paradas.add_to(mapa)

    # ----------------------------------------------------------
    # CAPA 3+: Rutas por depot (PolyLines)
    # ----------------------------------------------------------
    capas_rutas = {}
    for centro in centros_activos:
        color_name   = mapa_colores_hub[centro]
        label        = nombre_display(centro)
        capas_rutas[centro] = folium.FeatureGroup(
            name=f"Rutas — {label}",
            show=True,
        )

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
            tooltip=(
                f"Van {t_id} | {nombre_display(centro_origen, 20)}"
                f" | {km_ruta:.0f} km | {n_paradas} paradas"
            ),
        ).add_to(capas_rutas[centro_origen])

    for capa in capas_rutas.values():
        capa.add_to(mapa)

    # ----------------------------------------------------------
    # Marcadores de depot
    # ----------------------------------------------------------
    for centro in centros_activos:
        coords = buscar_coords_depot(centro)
        if not coords:
            continue
        color_name = mapa_colores_hub[centro]
        label      = nombre_display(centro)
        vans_c     = depot_stats[centro]['vans']
        km_c       = depot_stats[centro]['km']
        folium.Marker(
            location=list(coords),
            popup=folium.Popup(
                f"<b>{label}</b><br/>"
                f"Vans: {vans_c}<br/>"
                f"Km/dia: {km_c:,.0f}",
                max_width=220,
            ),
            tooltip=f"DEPOT: {label}",
            icon=folium.Icon(color=color_name, icon="building", prefix="fa"),
        ).add_to(mapa)

    folium.LayerControl(collapsed=False).add_to(mapa)

    # ----------------------------------------------------------
    # Guardar
    # ----------------------------------------------------------
    nombre_salida = f"mapa_interactivo_{categoria}.html"
    ruta_salida   = os.path.join(DIR_MAPAS_SALIDA, nombre_salida)
    mapa.save(ruta_salida)
    print(f"  [OK] -> {nombre_salida}  ({transportistas} vans, {km_totales:,.0f} km, {coste_dia:,.0f} EUR/dia)\n")

print(f"Mapas guardados en: {os.path.abspath(DIR_MAPAS_SALIDA)}")


# ── Publicar en docs/ ─────────────────────────────────────────────────────────
# El README y GitHub Pages leen de docs/mapas/, no de outputs/. Copiar aqui evita
# que una regeneracion deje la version publicada desactualizada.
import shutil as _shutil
_DIR_DOCS = os.path.join(BASE_DIR, "docs", "mapas")
os.makedirs(_DIR_DOCS, exist_ok=True)
_copiados = 0
for _f in os.listdir(DIR_MAPAS_SALIDA):
    if _f.endswith(".html"):
        _shutil.copy2(os.path.join(DIR_MAPAS_SALIDA, _f), os.path.join(_DIR_DOCS, _f))
        _copiados += 1
print(f"Publicados {_copiados} mapas en docs/mapas/")
