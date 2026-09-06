"""
02_Filtro_Candidatos.py  —  PASO 2/6 del pipeline MCDA
========================================================
Filtra las localizaciones candidatas de 03_generador_candidatos.py
con criterios de viabilidad física, ambiental y logística realistas,
reduciendo los candidatos a un conjunto menor de ubicaciones factibles.

Criterios aplicados (por orden de ejecución):
  F1   Pendiente del terreno   ≤ PENDIENTE_MAX_PCT %          [Open-Elevation API]
  F2   Espacios Nat. Proteg.   ≥ BUFFER_ENP_M m              [OpenStreetMap / osmnx]
  F3   Cursos / láminas agua   ≥ BUFFER_AGUA_M m             [OpenStreetMap / osmnx]
  F4   Usos incompatibles      ≥ BUFFER_USOS_M m             [OpenStreetMap / osmnx]
  F5   Distancia a autopista   ≤ MAX_DIST_AUTOPISTA_KM km    [OSM motorway_junction — Haversine]
  F6   Cobertura de demanda    ≥ MIN_COBERTURA_PCT %         [Datos.xlsx — Haversine]
  F7   Mano de obra (30 min)   ≥ MIN_POB_LABORAL hab.        [Datos.xlsx — Haversine]
  F8   Distancia competencia   ≥ MIN_DIST_COMPETENCIA_KM km  [Lista fija — Haversine]
  F9   Subestación eléctrica   ≤ RADIO_SUBST_M m (INFO)      [OpenStreetMap / osmnx]
  F10  Centroide de demanda    ≤ MAX_DESVIACION_CENTROIDE_KM [Datos.xlsx — Haversine]
  F11  Concentración demanda   ≥ MIN_CONCENTRACION_30KM_PCT % [Datos.xlsx — Haversine]
  F12  Núcleo urbano próximo   ≤ MAX_DIST_NUCLEO_KM km       [Lista fija — Haversine]

Fuentes normativas y operacionales de los umbrales:
  F1  – Estándar sectorial logístico (Prologis, Goodman, P3): ≤ 3% para
        viabilidad sin terraplenes costosos. CTE DB-SUA regula itinerarios
        peatonales, NO pendientes de explanada industrial.
  F2  – Ley 42/2007 Patrimonio Natural y Biodiversidad; Directiva 92/43/CEE
        (art. 6.3): cualquier proyecto que pueda afectar Red Natura requiere
        Evaluación Adecuada de Repercusiones (EAR). Buffer 500 m es la
        convención académica/práctica para evitar la necesidad de EAR.
  F3  – RD 849/1986 (RDPH) art. 6: zona de policía 100 m desde DPH.
        RD 638/2016 art. 14 bis: zona de flujo preferente (ZFP) restringe
        instalaciones con productos peligrosos. Buffer 200 m = zona de
        policía + margen. (Verificar con visor SNCZI para ZFP y T100.)
  F4  – RD 1367/2007 (Ley 37/2003 del Ruido): límite nocturno industrial
        ≤ 55 dB(A) en área residencial. Operaciones logísticas generan
        ~65-75 dB(A). 200 m = atenuación suficiente sin pantallas acústicas.
        RDL 7/2015 Ley del Suelo: compatibilidad de usos según PGOU.
  F5  – CBRE/JLL Iberia (2024-25): "last-mile prime" exige acceso a
        autopista en < 5 km por red viaria. 10 km en línea recta ≈ 12-15 km
        por carretera ≈ 10-15 min conducción. Amazon DQA8 (Escúzar) está a
        3 km del acceso a la A-92.
        Accesos obtenidos de OSM (motorway_junction): 1.164 nodos en las
        4 provincias. CSV en data/raw/accesos_autopista_osm.csv.
  F6  – Amazon DSP objetivo: ≥ 90% de paquetes en ≤ 60 min desde depot.
        Radio 65 km ≈ 60-70 min conducción media en Andalucía.
        MIN_COBERTURA_PCT = 30% es umbral de preselección amplio.
  F7  – Amazon DQA8 Escúzar: > 100 empleos directos + 200-300 conductores.
        Radio 30 km ≈ 30 min; mínimo 50.000 hab. para viabilidad de
        contratación sin transporte organizado.
  F8  – Red Amazon Andalucía: separaciones ≥ 120-150 km entre estaciones.
        Mínimo 80 km para evitar canibalización de volumen.
        (DESACTIVADO por defecto: el área incluye provincias donde Amazon
        ya opera. Reactivar con ACTIVO_F8 = True.)
  F9  – Delivery station Amazon DSP: ~1-2 MVA (clasificadora + recarga
        flota eléctrica). Informativo: OSM puede estar incompleto.
  F10 – Principio del centro de gravedad logístico: el depósito óptimo
        minimiza la suma ponderada de distancias a clientes. Si el candidato
        está a > MAX_DESVIACION_CENTROIDE_KM del centroide ponderado de su
        demanda, existe otra ubicación que reduciría el total de km/día.
  F11 – Densidad operativa de última milla: las rutas eficientes tienen
        alta concentración de paradas cerca del depot. Si < 30% de la
        demanda alcanzable (65 km) está en el radio denso (30 km), los
        conductores pasan más tiempo en carretera que entregando. Umbral
        calculado sobre (30/65)² ≈ 21% de distribución uniforme; 30%
        exige cierta concentración urbana en el entorno cercano.
  F12 – Sin acceso a una ciudad de > 100.000 hab. en ≤ 25 km, la densidad
        de paradas por ruta es demasiado baja para ser rentable. Amazon
        ubica todas sus delivery stations en entornos periurbanos de
        grandes núcleos (Escúzar-Granada: 18 km del centro; DSP Sevilla:
        polígono periurbano de Sevilla capital).

NOTA sobre zonas inundables (SNCZI):
  El filtro óptimo sería consultar sig.mapama.gob.es/snczi con las capas
  ZFP, T100 y T500. F3 es un proxy conservador. Se recomienda verificar
  manualmente los candidatos aprobados en el visor SNCZI.

Entrada : data/raw/candidatos_poligonos_industriales.csv  (salida de paso 01)
Salidas : data/raw/candidatos_filtrados.csv               (entrada para paso 03)
          data/raw/candidatos_filtrados_detalle.csv        (diagnóstico completo)
"""
# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")


import os
import sys
import math
import time

import requests
import pandas as pd
import geopandas as gpd
import osmnx as ox
from shapely.geometry import Point

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
#  CONFIGURACIÓN — EDITAR AQUÍ
# ============================================================

# F1: Pendiente máxima del terreno
PENDIENTE_MAX_PCT      = 3.0    # %   — estándar sectorial logístico
RADIO_ELEV_M           = 300    # m   — radio de muestreo alrededor del centroide
N_ANGULOS_ELEV         =   8    # núm — puntos angulares; total = N+1 (centro incluido)

# F2: Espacios Naturales Protegidos
BUFFER_ENP_M           = 500    # m   — separación al límite del ENP
RADIO_CONSULTA_ENP_M   = 2500   # m   — radio de búsqueda OSM

# F3: Cursos y láminas de agua
BUFFER_AGUA_M          = 200    # m   — zona de policía (100 m) + margen (RD 638/2016)
RADIO_CONSULTA_AGUA_M  = 500    # m   — radio de búsqueda OSM

# F4: Usos incompatibles del suelo
BUFFER_USOS_M          = 200    # m   — residencial / hospital / colegio / clínica
RADIO_CONSULTA_USOS_M  = 400    # m   — radio de búsqueda OSM

# F5: Distancia en línea recta al acceso de autopista más cercano
MAX_DIST_AUTOPISTA_KM  = 10.0   # km  — ≈ 12-15 km por carretera; estándar Amazon DSP

# Deduplicación espacial post-filtros
# Solo el mejor candidato (mayor cobertura_pct, luego Area_Ha) por zona.
RADIO_DEDUP_KM         = 8.0    # km  — radio mínimo entre candidatos en la salida

# F6: Cobertura de demanda ponderada (columna Peso de Datos.xlsx)
RADIO_COBERTURA_KM     = 65.0   # km  — radio ≈ 60-70 min conducción en Andalucía
MIN_COBERTURA_PCT      = 0.0    # %   — desactivado: P-Median optimiza cobertura globalmente

# F7: Mano de obra disponible
RADIO_LABORAL_KM       = 30.0   # km  — ≈ 30 min conducción (radio de captación laboral)
MIN_POB_LABORAL        = 50_000 # hab — mínimo para viabilidad sin transporte organizado

# F8: Separación a estaciones logísticas Amazon existentes (anti-canibalización)
# DESACTIVADO: el área de estudio incluye provincias donde Amazon ya opera.
# Reactivar (ACTIVO_F8 = True) si se busca ubicación para ampliar la red.
ACTIVO_F8              = False
MIN_DIST_COMPETENCIA_KM = 80.0  # km  — separación mínima entre centros propios

# F9: Subestación eléctrica (informativo — no rechaza automáticamente)
RADIO_SUBST_M          = 5000   # m   — radio de búsqueda OSM (~1-2 MVA requeridos)

# F10: Desviación respecto al centroide ponderado de la demanda
# El candidato óptimo está cerca del "centro de masa" de sus clientes.
# Un candidato alejado del centroide de su demanda siempre tendrá rutas
# menos eficientes que uno bien centrado.
MAX_DESVIACION_CENTROIDE_KM = 999.0  # km — desactivado: centroide relevante es por zona asignada

# F11: Concentración de demanda en el radio denso (30 km) vs. radio total (65 km)
# Mide qué fracción de la demanda alcanzable está "cerca" del depot.
# Baja concentración = conductores pasan demasiado tiempo en carretera.
# Ref: distribución uniforme daría (30/65)² ≈ 21%; 30% exige concentración urbana.
MIN_CONCENTRACION_30KM_PCT = 0.0    # %  — desactivado: P-Median asigna zonas optimamente

# F12: Distancia al núcleo urbano principal más cercano (> MIN_POB_NUCLEO hab.)
# Sin acceso periurbano a una gran ciudad la densidad de paradas es inviable.
MAX_DIST_NUCLEO_KM     = 40.0   # km  — ampliado para incluir capitales provinciales (Huelva, Cadiz)
MIN_POB_NUCLEO         = 100_000 # hab — tamaño mínimo del núcleo urbano

# Sin límite de candidatos de salida: cualquier candidato que pase todos los
# filtros merece ser evaluado por el MCDA. El ranking y la selección final
# son responsabilidad de 04_Puntuacion_MCDA.py.

# Pausa entre consultas OSM/Overpass
PAUSA_OSM_SEG          = 1.2

# CRS métrico para Andalucía (UTM Zona 30N)
EPSG_METRICO           = 32630

# ============================================================
#  RUTAS DE FICHEROS
# ============================================================
RUTA_ENTRADA           = os.path.join(BASE_DIR, "data", "raw", "candidatos_poligonos_industriales.csv")
RUTA_SALIDA            = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
RUTA_DETALLE           = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados_detalle.csv")
RUTA_DATOS             = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
RUTA_ACCESOS_AUTOPISTA = os.path.join(BASE_DIR, "data", "raw", "accesos_autopista_osm.csv")

# (Los accesos de autopista se cargan desde RUTA_ACCESOS_AUTOPISTA al iniciar el script.
#  El CSV fue generado con OSM: 1.164 nodos motorway_junction en las 4 provincias.)

# ============================================================
#  ESTACIONES AMAZON / LOGÍSTICA EN ANDALUCÍA  (F8)
#  Fuente: About Amazon ES, MWPVL Distribution Network Maps (2024)
# ============================================================
ESTACIONES_EXISTENTES = [
    {"lat": 36.7600, "lon": -4.5500, "nombre": "Amazon DQA3 Málaga"},
    {"lat": 37.3500, "lon": -5.9800, "nombre": "Amazon DSP Sevilla"},
    {"lat": 36.6100, "lon": -6.2200, "nombre": "Amazon El Puerto de Santa María (Cádiz)"},
    {"lat": 37.1950, "lon": -3.7900, "nombre": "Amazon DQA8 Escúzar (Granada)"},
    {"lat": 36.7000, "lon": -4.4800, "nombre": "DHL Parcel Hub Málaga"},
    {"lat": 37.3700, "lon": -5.9300, "nombre": "SEUR Hub Sevilla"},
    {"lat": 37.8200, "lon": -4.8000, "nombre": "Correos Express Hub Córdoba"},
]

# ============================================================
#  NÚCLEOS URBANOS PRINCIPALES EN EL ÁREA DE ESTUDIO  (F12)
#  Ciudades > 100.000 hab. en Sevilla, Huelva, Córdoba y Cádiz
# ============================================================
CIUDADES_PRINCIPALES = [
    {"lat": 37.3882, "lon": -5.9823, "nombre": "Sevilla",              "pob": 700_000},
    {"lat": 37.8882, "lon": -4.7794, "nombre": "Córdoba",              "pob": 320_000},
    {"lat": 36.6820, "lon": -6.1370, "nombre": "Jerez de la Frontera", "pob": 210_000},
    {"lat": 37.2609, "lon": -6.9528, "nombre": "Huelva",               "pob": 150_000},
    {"lat": 37.3862, "lon": -5.9800, "nombre": "Dos Hermanas",         "pob": 135_000},
    {"lat": 36.5270, "lon": -6.2886, "nombre": "Cádiz",                "pob": 120_000},
    {"lat": 36.6140, "lon": -4.5000, "nombre": "Algeciras",            "pob": 120_000},
    {"lat": 36.6005, "lon": -6.2274, "nombre": "El Puerto de Santa María", "pob": 90_000},
]
# Filtramos a las que superan MIN_POB_NUCLEO al iniciar
_CIUDADES_FILTRADAS = [c for c in CIUDADES_PRINCIPALES if c["pob"] >= MIN_POB_NUCLEO]


# ============================================================
#  UTILIDADES
# ============================================================

def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos GPS (fórmula de Haversine)."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def punto_desplazado(lat, lon, dist_m, angulo_deg):
    """Desplaza (lat, lon) dist_m metros en dirección angulo_deg (N=0°, E=90°)."""
    R = 6_371_000
    ang = math.radians(angulo_deg)
    dlat = (dist_m * math.cos(ang)) / R
    dlon = (dist_m * math.sin(ang)) / (R * math.cos(math.radians(lat)))
    return round(lat + math.degrees(dlat), 7), round(lon + math.degrees(dlon), 7)


def min_dist_a_gdf_m(lat, lon, gdf):
    """
    Distancia mínima en metros entre (lat, lon) y cualquier geometría del GDF.
    Proyecta a UTM 30N. Devuelve float('inf') si vacío o error.
    """
    if gdf is None or gdf.empty:
        return float("inf")
    try:
        punto_utm = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(epsg=EPSG_METRICO).iloc[0]
        return float(gdf.to_crs(epsg=EPSG_METRICO).geometry.distance(punto_utm).min())
    except Exception:
        return float("inf")


def consultar_osm(lat, lon, tags, radio_m):
    """Consulta OSM vía osmnx; devuelve GeoDataFrame vacío si falla o sin resultados."""
    try:
        gdf = ox.features_from_point((lat, lon), tags=tags, dist=radio_m)
        return gdf if not gdf.empty else gpd.GeoDataFrame()
    except Exception:
        return gpd.GeoDataFrame()


def cargar_poblacion():
    """
    Carga población por sección censal desde hojas provinciales de Datos.xlsx.
    Devuelve DataFrame con columnas [Seccion INE, Poblacion], o vacío si falla.
    """
    dfs = []
    for idx in range(1, 5):
        try:
            df_p = pd.read_excel(RUTA_DATOS, sheet_name=idx)
            df_p = df_p[[df_p.columns[0], df_p.columns[4]]].copy()
            df_p.columns = ["Seccion INE", "Poblacion"]
            df_p["Seccion INE"] = pd.to_numeric(df_p["Seccion INE"], errors="coerce")
            df_p = df_p.dropna(subset=["Seccion INE"])
            df_p["Seccion INE"] = df_p["Seccion INE"].astype(int)
            dfs.append(df_p)
        except Exception:
            pass
    if not dfs:
        return pd.DataFrame(columns=["Seccion INE", "Poblacion"])
    return pd.concat(dfs, ignore_index=True).drop_duplicates("Seccion INE")


def cargar_accesos_autopista():
    """
    Carga los accesos de autopista desde el CSV generado con OSM
    (data/raw/accesos_autopista_osm.csv, 1.164 nodos motorway_junction).
    Aborta con mensaje claro si el fichero no existe.
    """
    if not os.path.exists(RUTA_ACCESOS_AUTOPISTA):
        print()
        print(f"ERROR: no se encontro el fichero de accesos de autopista:")
        print(f"  {RUTA_ACCESOS_AUTOPISTA}")
        print()
        print("Para regenerarlo ejecuta desde la raiz del repositorio:")
        print("  python -c \"")
        print("  from osmnx._overpass import _overpass_request; import pandas as pd, os")
        print("  q = '[out:json][timeout:90];node[\\\"highway\\\"=\\\"motorway_junction\\\"](35.9,-7.6,38.5,-4.0);out body;'")
        print("  nodes = _overpass_request(data={'data': q})['elements']")
        print("  rows = [{'lat': n['lat'], 'lon': n['lon'], 'nombre': n.get('tags',{}).get('name', n.get('tags',{}).get('ref',''))} for n in nodes]")
        print("  pd.DataFrame(rows).to_csv(r'data/raw/accesos_autopista_osm.csv', index=False, encoding='utf-8-sig')")
        print("  \"")
        sys.exit(1)
    df_acc = pd.read_csv(RUTA_ACCESOS_AUTOPISTA, encoding="utf-8-sig")
    accesos = df_acc[["lat", "lon", "nombre"]].to_dict("records")
    return accesos


# ============================================================
#  F1: PENDIENTE DEL TERRENO  (Open-Elevation API)
# ============================================================
_OPEN_ELEV_URL = "https://api.open-elevation.com/api/v1/lookup"


def filtro_pendiente(lat, lon):
    """
    Muestrea elevación en centroide + N_ANGULOS_ELEV puntos a RADIO_ELEV_M metros.
    Devuelve (aprobado, pendiente_pct | None, detalle).
    Si la API no responde → aprobado=True (beneficio de la duda).
    """
    puntos = [(lat, lon)] + [
        punto_desplazado(lat, lon, RADIO_ELEV_M, i * 360.0 / N_ANGULOS_ELEV)
        for i in range(N_ANGULOS_ELEV)
    ]
    payload = {"locations": [{"latitude": p[0], "longitude": p[1]} for p in puntos]}
    try:
        resp = requests.post(_OPEN_ELEV_URL, json=payload, timeout=20)
        if resp.status_code == 200:
            elevs = [r["elevation"] for r in resp.json()["results"]]
            pend_max = round(max(abs(e - elevs[0]) / RADIO_ELEV_M * 100 for e in elevs[1:]), 2)
            return pend_max <= PENDIENTE_MAX_PCT, pend_max, f"pendiente={pend_max:.1f}%"
    except Exception:
        pass
    return True, None, "API elevación no disponible — no verificado"


# ============================================================
#  F2: ESPACIOS NATURALES PROTEGIDOS  (OSM)
# ============================================================
_TAGS_ENP = {
    "boundary": ["protected_area", "national_park"],
    "leisure":  "nature_reserve",
    "landuse":  "conservation",
}


def filtro_enp(lat, lon):
    """Rechaza si dist al ENP más cercano < BUFFER_ENP_M (evita necesidad de EAR)."""
    gdf = consultar_osm(lat, lon, _TAGS_ENP, RADIO_CONSULTA_ENP_M)
    time.sleep(PAUSA_OSM_SEG)
    dist_m = min_dist_a_gdf_m(lat, lon, gdf)
    if dist_m < BUFFER_ENP_M:
        nombre = ""
        if not gdf.empty and "name" in gdf.columns:
            nombres = gdf["name"].dropna()
            if not nombres.empty:
                nombre = str(nombres.iloc[0])
        det = f"ENP a {dist_m:.0f} m (mín {BUFFER_ENP_M} m){': ' + nombre if nombre else ''}"
        return False, round(dist_m), det
    dist_str = f"{dist_m:.0f} m" if dist_m != float("inf") else "ninguno en radio"
    return True, (round(dist_m) if dist_m != float("inf") else None), f"ENP más cercano: {dist_str}"


# ============================================================
#  F3: CURSOS Y LÁMINAS DE AGUA  (OSM)
# ============================================================
_TAGS_AGUA = {
    "natural":  ["water", "wetland"],
    "waterway": ["river", "stream", "canal", "drain"],
    "landuse":  "basin",
}


def filtro_agua(lat, lon):
    """Rechaza si hay agua a < BUFFER_AGUA_M (proxy zona de policía RD 849/1986)."""
    gdf = consultar_osm(lat, lon, _TAGS_AGUA, RADIO_CONSULTA_AGUA_M)
    time.sleep(PAUSA_OSM_SEG * 0.5)
    dist_m = min_dist_a_gdf_m(lat, lon, gdf)
    if dist_m < BUFFER_AGUA_M:
        return False, round(dist_m), f"Agua a {dist_m:.0f} m (mín {BUFFER_AGUA_M} m)"
    dist_str = f"{dist_m:.0f} m" if dist_m != float("inf") else "ninguna en radio"
    return True, (round(dist_m) if dist_m != float("inf") else None), f"Agua más cercana: {dist_str}"


# ============================================================
#  F4: USOS INCOMPATIBLES DEL SUELO  (OSM)
# ============================================================
_TAGS_USOS = {
    "landuse": "residential",
    "amenity": ["hospital", "school", "kindergarten", "clinic", "nursing_home"],
}


def filtro_usos_incompatibles(lat, lon):
    """Rechaza si hay uso sensible a < BUFFER_USOS_M (RD 1367/2007 acústica)."""
    gdf = consultar_osm(lat, lon, _TAGS_USOS, RADIO_CONSULTA_USOS_M)
    time.sleep(PAUSA_OSM_SEG * 0.5)
    dist_m = min_dist_a_gdf_m(lat, lon, gdf)
    if dist_m < BUFFER_USOS_M:
        tipo_uso = "uso sensible"
        if not gdf.empty:
            try:
                gdf_utm = gdf.reset_index().to_crs(epsg=EPSG_METRICO)
                punto_utm = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(epsg=EPSG_METRICO).iloc[0]
                pos = int(gdf_utm.geometry.distance(punto_utm).argmin())
                for col in ("amenity", "landuse"):
                    if col in gdf_utm.columns:
                        val = gdf_utm.iloc[pos].get(col)
                        if pd.notna(val) and str(val) not in ("nan", ""):
                            tipo_uso = str(val)
                            break
            except Exception:
                pass
        return False, round(dist_m), f"{tipo_uso} a {dist_m:.0f} m (mín {BUFFER_USOS_M} m)"
    dist_str = f"{dist_m:.0f} m" if dist_m != float("inf") else "ninguno en radio"
    return True, (round(dist_m) if dist_m != float("inf") else None), f"Uso más cercano: {dist_str}"


# ============================================================
#  F5: ACCESIBILIDAD A AUTOPISTA  (Haversine sobre nodos OSM)
# ============================================================

def filtro_autopista(lat, lon, entradas_autopista):
    """
    Haversine al nodo motorway_junction mas cercano del CSV OSM.
    10 km en linea recta ≈ 12-15 km por carretera (estandar Amazon DSP).
    """
    mejor_dist, mejor_nom = float("inf"), ""
    for e in entradas_autopista:
        d = haversine_km(lat, lon, float(e["lat"]), float(e["lon"]))
        if d < mejor_dist:
            mejor_dist, mejor_nom = d, str(e["nombre"])
    mejor_dist = round(mejor_dist, 2)
    return mejor_dist <= MAX_DIST_AUTOPISTA_KM, mejor_dist, mejor_nom


# ============================================================
#  F6: COBERTURA DE DEMANDA  (Datos.xlsx — Haversine)
# ============================================================

def filtro_cobertura(lat, lon, df_sec):
    """% de demanda ponderada (Peso) dentro de RADIO_COBERTURA_KM."""
    dists = df_sec.apply(
        lambda r: haversine_km(lat, lon, float(r["Latitud"]), float(r["Longitud"])), axis=1
    )
    peso_total = float(df_sec["Peso"].sum())
    cob = round(100 * float(df_sec.loc[dists <= RADIO_COBERTURA_KM, "Peso"].sum()) / peso_total, 1) \
          if peso_total > 0 else 0.0
    return cob >= MIN_COBERTURA_PCT, cob


# ============================================================
#  F7: MANO DE OBRA DISPONIBLE  (Datos.xlsx — Haversine)
# ============================================================

def filtro_mano_obra(lat, lon, df_sec_pob):
    """Población total en radio RADIO_LABORAL_KM. Pasa si df_sec_pob está vacío."""
    if df_sec_pob.empty:
        return True, None, "Datos de población no disponibles — no verificado"
    dists = df_sec_pob.apply(
        lambda r: haversine_km(lat, lon, float(r["Latitud"]), float(r["Longitud"])), axis=1
    )
    pob = int(df_sec_pob.loc[dists <= RADIO_LABORAL_KM, "Poblacion"].sum())
    return pob >= MIN_POB_LABORAL, pob, f"población {pob:,} hab. en {RADIO_LABORAL_KM:.0f} km"


# ============================================================
#  F8: DISTANCIA A ESTACIONES LOGÍSTICAS EXISTENTES  (Haversine)
# ============================================================

def filtro_competencia(lat, lon):
    """Distancia Haversine a la estación Amazon/logística más cercana."""
    menor_dist, est_cercana = float("inf"), ""
    for est in ESTACIONES_EXISTENTES:
        d = haversine_km(lat, lon, est["lat"], est["lon"])
        if d < menor_dist:
            menor_dist, est_cercana = d, est["nombre"]
    menor_dist = round(menor_dist, 2)
    return menor_dist >= MIN_DIST_COMPETENCIA_KM, menor_dist, est_cercana


# ============================================================
#  F9: SUBESTACIÓN ELÉCTRICA  (OSM — informativo, no rechaza)
# ============================================================
_TAGS_SUBST = {"power": "substation"}


def info_substation(lat, lon):
    """Busca subestación en OSM en radio RADIO_SUBST_M. Solo informativo."""
    gdf = consultar_osm(lat, lon, _TAGS_SUBST, RADIO_SUBST_M)
    time.sleep(PAUSA_OSM_SEG * 0.5)
    dist_m = min_dist_a_gdf_m(lat, lon, gdf)
    if dist_m != float("inf"):
        return True, round(dist_m), f"subestación a {dist_m:.0f} m"
    return False, None, f"sin subestación OSM en {RADIO_SUBST_M} m (verificar con REE)"


# ============================================================
#  F10: DESVIACIÓN RESPECTO AL CENTROIDE DE DEMANDA  (Datos.xlsx)
# ============================================================

def filtro_centroide_demanda(lat, lon, df_sec):
    """
    Calcula el centroide geográfico ponderado (centro de masa) de la demanda
    dentro del radio de servicio. Rechaza si el candidato está a más de
    MAX_DESVIACION_CENTROIDE_KM de ese centroide.

    Principio: el depot óptimo minimiza la suma ponderada de distancias a
    clientes → debe estar cerca del centro de masa de su demanda.
    """
    dists = df_sec.apply(
        lambda r: haversine_km(lat, lon, float(r["Latitud"]), float(r["Longitud"])), axis=1
    )
    df_area = df_sec[dists <= RADIO_COBERTURA_KM].copy()

    if df_area.empty or df_area["Peso"].sum() == 0:
        return True, None, "sin demanda en radio — no verificado"

    peso_total   = df_area["Peso"].sum()
    lat_centroide = float((df_area["Latitud"] * df_area["Peso"]).sum() / peso_total)
    lon_centroide = float((df_area["Longitud"] * df_area["Peso"]).sum() / peso_total)

    desv_km = round(haversine_km(lat, lon, lat_centroide, lon_centroide), 2)
    aprobado = desv_km <= MAX_DESVIACION_CENTROIDE_KM
    return aprobado, desv_km, f"desviación centroide={desv_km:.1f} km"


# ============================================================
#  F11: CONCENTRACIÓN DE DEMANDA EN RADIO DENSO  (Datos.xlsx)
# ============================================================

def filtro_concentracion_demanda(lat, lon, df_sec):
    """
    Calcula qué fracción de la demanda dentro de RADIO_COBERTURA_KM
    está en el radio denso (30 km). Baja concentración = alta proporción
    de km en carretera vs. km entregando.

    Ref: distribución uniforme → (30/65)² ≈ 21%. Umbral 30% exige
    concentración urbana en el entorno cercano al candidato.
    """
    dists = df_sec.apply(
        lambda r: haversine_km(lat, lon, float(r["Latitud"]), float(r["Longitud"])), axis=1
    )
    peso_65km = float(df_sec.loc[dists <= RADIO_COBERTURA_KM, "Peso"].sum())
    peso_30km = float(df_sec.loc[dists <= 30.0, "Peso"].sum())

    if peso_65km == 0:
        return True, None, "sin demanda en radio — no verificado"

    conc = round(100 * peso_30km / peso_65km, 1)
    aprobado = conc >= MIN_CONCENTRACION_30KM_PCT
    return aprobado, conc, f"concentración {conc:.1f}% (≥{MIN_CONCENTRACION_30KM_PCT}% requerido)"


# ============================================================
#  F12: PROXIMIDAD A NÚCLEO URBANO PRINCIPAL  (lista fija)
# ============================================================

def filtro_nucleo_urbano(lat, lon):
    """
    Distancia Haversine a la ciudad más cercana con población ≥ MIN_POB_NUCLEO.
    Sin acceso periurbano a una gran ciudad la densidad de paradas es inviable.
    """
    mejor_dist, mejor_ciudad = float("inf"), ""
    for c in _CIUDADES_FILTRADAS:
        d = haversine_km(lat, lon, c["lat"], c["lon"])
        if d < mejor_dist:
            mejor_dist, mejor_ciudad = d, c["nombre"]
    mejor_dist = round(mejor_dist, 2)
    aprobado = mejor_dist <= MAX_DIST_NUCLEO_KM
    return aprobado, mejor_dist, mejor_ciudad


# ============================================================
#  DEDUPLICACION ESPACIAL
# ============================================================

def _deduplicar_candidatos(df_ok):
    """
    Dentro del conjunto de candidatos aprobados, elimina los que esten a menos
    de RADIO_DEDUP_KM de un candidato mejor.
    Criterio de mejor: mayor cobertura_pct; desempate por mayor Area_Ha.
    Algoritmo greedy: ordena de mejor a peor y acepta solo si ningun candidato
    ya aceptado esta dentro del radio.
    Devuelve (df_dedup, df_eliminados).
    """
    if df_ok.empty:
        return df_ok.copy(), pd.DataFrame()

    df_s = df_ok.copy()
    if "cobertura_pct" not in df_s.columns:
        df_s["cobertura_pct"] = 0.0
    if "Area_Ha" not in df_s.columns:
        df_s["Area_Ha"] = 0.0
    df_s["cobertura_pct"] = pd.to_numeric(df_s["cobertura_pct"], errors="coerce").fillna(0.0)
    df_s["Area_Ha"]       = pd.to_numeric(df_s["Area_Ha"],       errors="coerce").fillna(0.0)
    df_s = df_s.sort_values(["cobertura_pct", "Area_Ha"], ascending=[False, False])
    df_s = df_s.reset_index(drop=True)

    aceptados = []
    eliminados = []
    for i, row_i in df_s.iterrows():
        lat_i = float(row_i["Latitud"])
        lon_i = float(row_i["Longitud"])
        demasiado_cerca = False
        for j in aceptados:
            row_j = df_s.loc[j]
            if haversine_km(lat_i, lon_i, float(row_j["Latitud"]), float(row_j["Longitud"])) < RADIO_DEDUP_KM:
                demasiado_cerca = True
                break
        if demasiado_cerca:
            eliminados.append(i)
        else:
            aceptados.append(i)

    df_dedup = df_s.loc[aceptados].reset_index(drop=True)
    df_elim  = df_s.loc[eliminados].reset_index(drop=True)
    return df_dedup, df_elim


# ============================================================
#  PROGRAMA PRINCIPAL
# ============================================================
if __name__ == "__main__":
    print("=" * 72)
    print("  FILTRO DE CANDIDATOS — Pipeline D MCDA  /  Paso 2 de 6")
    print("=" * 72)
    print()
    print("Criterios de viabilidad:")
    print(f"  F1   Pendiente terreno      ≤ {PENDIENTE_MAX_PCT}%    [estándar sectorial logístico]")
    print(f"  F2   Espacio protegido      ≥ {BUFFER_ENP_M} m   [Ley 42/2007 — Red Natura 2000]")
    print(f"  F3   Agua / inundación      ≥ {BUFFER_AGUA_M} m   [RD 849/1986 + RD 638/2016]")
    print(f"  F4   Usos incompatibles     ≥ {BUFFER_USOS_M} m   [RD 1367/2007 acústica]")
    print(f"  F5   Acceso autopista       ≤ {MAX_DIST_AUTOPISTA_KM} km  [estándar Amazon DSP ≈ 5 km/carretera]")
    print(f"  F6   Cobertura demanda      ≥ {MIN_COBERTURA_PCT}%   [Amazon DSP: ≤60 min a cliente]")
    print(f"  F7   Mano de obra (30 km)   ≥ {MIN_POB_LABORAL:,} hab [viabilidad contratación DSP]")
    f8_est = f"≥ {MIN_DIST_COMPETENCIA_KM} km" if ACTIVO_F8 else "DESACTIVADO (informativo)"
    print(f"  F8   Distancia competencia  {f8_est}  [anti-canibalización]")
    print(f"  F9   Subestación eléctrica  ≤ {RADIO_SUBST_M} m  [informativo — ~1-2 MVA req.]")
    print(f"  F10  Centroide de demanda   ≤ {MAX_DESVIACION_CENTROIDE_KM} km  [principio centro de gravedad logístico]")
    print(f"  F11  Concentración demanda  ≥ {MIN_CONCENTRACION_30KM_PCT}%   [densidad operativa 30 km vs 65 km]")
    print(f"  F12  Núcleo urbano próximo  ≤ {MAX_DIST_NUCLEO_KM} km  [periurbano de ciudad >{MIN_POB_NUCLEO//1000}k hab.]")
    print()
    print("  ⚠  Verificar manualmente en visor SNCZI (sig.mapama.gob.es/snczi)")
    print("     las capas ZFP, T100 y T500 para los candidatos aprobados.")
    print()

    # ---- Cargar datos ----
    if not os.path.exists(RUTA_ENTRADA):
        print(f"ERROR: archivo no encontrado: {RUTA_ENTRADA}")
        print("   Ejecuta primero: python src/03_generador_candidatos.py")
        sys.exit(1)

    print("  Cargando accesos de autopista (OSM)...", end=" ", flush=True)
    entradas_autopista = cargar_accesos_autopista()
    print(f"{len(entradas_autopista)} nodos cargados desde CSV.")

    df = pd.read_csv(RUTA_ENTRADA, encoding="utf-8-sig")
    df = df.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)

    df_sec = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
    df_sec = df_sec.dropna(subset=["Latitud", "Longitud", "Peso"]).reset_index(drop=True)

    print("  Cargando poblacion por seccion censal...", end=" ", flush=True)
    df_pob_sec = cargar_poblacion()
    if not df_pob_sec.empty:
        df_sec_pob = df_sec.merge(df_pob_sec, on="Seccion INE", how="left")
        df_sec_pob["Poblacion"] = df_sec_pob["Poblacion"].fillna(0)
        print(f"{df_sec_pob['Poblacion'].sum():,.0f} hab. totales")
    else:
        df_sec_pob = pd.DataFrame()
        print("no disponible (F7 desactivado)")

    n = len(df)
    n_osm = n * 4
    print()
    print(f"  Candidatos de entrada :  {n}")
    print(f"  Secciones INE         :  {len(df_sec)}")
    print(f"  Consultas OSM estim.  :  ~{n_osm} (~{round(n_osm * PAUSA_OSM_SEG * 1.5 / 60):.0f} min)")
    print()
    resp = input("¿Continuar? (s/n): ").strip().lower()
    if resp not in ("s", "si", "sí", "y", "yes"):
        print("Proceso cancelado.")
        sys.exit(0)

    # ---- Columnas de diagnóstico ----
    for col in ["pendiente_pct", "enp_dist_m", "agua_dist_m", "usos_dist_m",
                "dist_autopista_km", "autopista_cercana", "cobertura_pct",
                "poblacion_30km", "dist_competencia_km", "estacion_cercana",
                "subst_dist_m", "subst_encontrada",
                "desv_centroide_km", "concentracion_30km_pct",
                "dist_nucleo_km", "nucleo_cercano",
                "motivos_rechazo"]:
        df[col] = None if col not in ("autopista_cercana", "estacion_cercana",
                                       "nucleo_cercano", "motivos_rechazo") else ""
    df["aprobado"] = True

    contadores = {f"F{i}": 0 for i in range(1, 13) if i != 9}

    # ---- Aplicar filtros ----
    print(f"\n{'#':>4}  {'Nombre':<45}  Resultado")
    print("-" * 80)

    for idx, fila in df.iterrows():
        lat, lon = float(fila["Latitud"]), float(fila["Longitud"])
        nom      = str(fila["Nombre"])
        rechazos = []

        # F1
        ok, val, det = filtro_pendiente(lat, lon)
        df.at[idx, "pendiente_pct"] = val
        if not ok:
            rechazos.append(f"F1({det})"); contadores["F1"] += 1
        time.sleep(0.3)

        # F2
        ok, val, det = filtro_enp(lat, lon)
        df.at[idx, "enp_dist_m"] = val
        if not ok:
            rechazos.append(f"F2({det[:50]})"); contadores["F2"] += 1

        # F3
        ok, val, det = filtro_agua(lat, lon)
        df.at[idx, "agua_dist_m"] = val
        if not ok:
            rechazos.append(f"F3({det})"); contadores["F3"] += 1

        # F4
        ok, val, det = filtro_usos_incompatibles(lat, lon)
        df.at[idx, "usos_dist_m"] = val
        if not ok:
            rechazos.append(f"F4({det})"); contadores["F4"] += 1

        # F5
        ok, dist_auto, nom_auto = filtro_autopista(lat, lon, entradas_autopista)
        df.at[idx, "dist_autopista_km"] = dist_auto
        df.at[idx, "autopista_cercana"]  = nom_auto
        if not ok:
            rechazos.append(f"F5({dist_auto:.1f} km>{MAX_DIST_AUTOPISTA_KM} km)"); contadores["F5"] += 1

        # F6
        ok, cob = filtro_cobertura(lat, lon, df_sec)
        df.at[idx, "cobertura_pct"] = cob
        if not ok:
            rechazos.append(f"F6(cobertura {cob:.1f}%<{MIN_COBERTURA_PCT}%)"); contadores["F6"] += 1

        # F7
        ok, pob, det = filtro_mano_obra(lat, lon, df_sec_pob)
        df.at[idx, "poblacion_30km"] = pob
        if not ok:
            rechazos.append(f"F7({det})"); contadores["F7"] += 1

        # F8 (calculado siempre; solo rechaza si ACTIVO_F8=True)
        ok, dist_comp, est_c = filtro_competencia(lat, lon)
        df.at[idx, "dist_competencia_km"] = dist_comp
        df.at[idx, "estacion_cercana"]     = est_c
        if ACTIVO_F8 and not ok:
            rechazos.append(f"F8({est_c[:30]} {dist_comp:.0f} km<{MIN_DIST_COMPETENCIA_KM} km)")
            contadores["F8"] += 1

        # F9 (informativo)
        subst_ok, subst_dist, _ = info_substation(lat, lon)
        df.at[idx, "subst_encontrada"] = subst_ok
        df.at[idx, "subst_dist_m"]     = subst_dist

        # F10
        ok, desv, det = filtro_centroide_demanda(lat, lon, df_sec)
        df.at[idx, "desv_centroide_km"] = desv
        if not ok:
            rechazos.append(f"F10({det})"); contadores["F10"] += 1

        # F11
        ok, conc, det = filtro_concentracion_demanda(lat, lon, df_sec)
        df.at[idx, "concentracion_30km_pct"] = conc
        if not ok:
            rechazos.append(f"F11({det})"); contadores["F11"] += 1

        # F12
        ok, dist_nuc, ciudad = filtro_nucleo_urbano(lat, lon)
        df.at[idx, "dist_nucleo_km"] = dist_nuc
        df.at[idx, "nucleo_cercano"]  = ciudad
        if not ok:
            rechazos.append(f"F12({ciudad} {dist_nuc:.1f} km>{MAX_DIST_NUCLEO_KM} km)")
            contadores["F12"] += 1

        # Resultado
        if rechazos:
            df.at[idx, "aprobado"]        = False
            df.at[idx, "motivos_rechazo"] = " | ".join(rechazos)
            print(f"{idx+1:>4}  {nom[:45]:<45}  ✗  {rechazos[0][:32]}")
        else:
            pend_str  = f"{df.at[idx,'pendiente_pct']:.1f}%" if df.at[idx,'pendiente_pct'] is not None else "n/v"
            subst_str = f"⚡{subst_dist}m" if subst_ok else "⚡?"
            print(
                f"{idx+1:>4}  {nom[:45]:<45}  ✓  "
                f"pend={pend_str}, auto={dist_auto:.1f}km, "
                f"conc={conc if conc is not None else '?'}%, {subst_str}"
            )

    # ---- Candidatos que pasan todos los filtros ----
    df_ok_pre = df[df["aprobado"]].copy().reset_index(drop=True)
    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)

    # ---- Deduplicacion espacial ----
    df_ok, df_elim_dedup = _deduplicar_candidatos(df_ok_pre)

    # Marcar eliminados por dedup en el detalle
    df["eliminado_dedup"] = False
    if not df_elim_dedup.empty:
        nombres_elim = set(df_elim_dedup["Nombre"].tolist())
        df.loc[df["Nombre"].isin(nombres_elim) & df["aprobado"], "eliminado_dedup"] = True

    # ---- Guardar resultados ----
    cols_csv = [
        "Nombre", "Latitud", "Longitud", "Municipio", "Tipo", "Area_Ha",
        "Descripcion", "pendiente_pct", "dist_autopista_km", "autopista_cercana",
        "cobertura_pct", "poblacion_30km", "desv_centroide_km",
        "concentracion_30km_pct", "dist_nucleo_km", "nucleo_cercano",
        "dist_competencia_km", "estacion_cercana", "subst_dist_m",
    ]
    cols_csv = [c for c in cols_csv if c in df_ok.columns]
    df_ok[cols_csv].to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")
    df.to_csv(RUTA_DETALLE, index=False, encoding="utf-8-sig")

    # ---- Resumen ----
    n_rec = n - len(df_ok_pre)
    print()
    print("=" * 72)
    print("  RESUMEN DEL FILTRADO")
    print("=" * 72)
    print(f"  Candidatos de entrada                          : {n}")
    print(f"  F1  - Pendiente > {PENDIENTE_MAX_PCT}%                          : {contadores['F1']:>2} rechazados")
    print(f"  F2  - ENP < {BUFFER_ENP_M} m                             : {contadores['F2']:>2} rechazados")
    print(f"  F3  - Agua < {BUFFER_AGUA_M} m                             : {contadores['F3']:>2} rechazados")
    print(f"  F4  - Usos incompatibles < {BUFFER_USOS_M} m                  : {contadores['F4']:>2} rechazados")
    print(f"  F5  - Autopista > {MAX_DIST_AUTOPISTA_KM} km ({len(entradas_autopista)} nodos OSM)      : {contadores['F5']:>2} rechazados")
    print(f"  F6  - Cobertura demanda < {MIN_COBERTURA_PCT}%                  : {contadores['F6']:>2} rechazados")
    print(f"  F7  - Mano de obra < {MIN_POB_LABORAL:,} hab en {RADIO_LABORAL_KM:.0f} km    : {contadores['F7']:>2} rechazados")
    f8_lbl = f"Competencia < {MIN_DIST_COMPETENCIA_KM} km" if ACTIVO_F8 else "Competencia (DESACTIVADO)    "
    print(f"  F8  - {f8_lbl:<38}: {contadores['F8']:>2} rechazados")
    print(f"  F10 - Desviacion centroide > {MAX_DESVIACION_CENTROIDE_KM} km              : {contadores['F10']:>2} rechazados")
    print(f"  F11 - Concentracion demanda 30km < {MIN_CONCENTRACION_30KM_PCT}%         : {contadores['F11']:>2} rechazados")
    print(f"  F12 - Nucleo urbano > {MAX_DIST_NUCLEO_KM} km                    : {contadores['F12']:>2} rechazados")
    print(f"  {'─' * 55}")
    print(f"  Aprobados tras filtros F1-F12                  : {len(df_ok_pre)}")
    print(f"  Eliminados por deduplicacion (radio {RADIO_DEDUP_KM} km)    : {len(df_elim_dedup)}")
    print(f"  CANDIDATOS FINALES                             : {len(df_ok)}")
    print()

    if not df_ok.empty:
        cols_show = [c for c in [
            "Nombre", "Municipio", "Area_Ha", "pendiente_pct",
            "dist_autopista_km", "cobertura_pct", "desv_centroide_km",
            "concentracion_30km_pct", "dist_nucleo_km",
        ] if c in df_ok.columns]
        print(df_ok[cols_show].to_string(index=False))
        print()

    print(f"Candidatos aprobados -> {RUTA_SALIDA}")
    print(f"Diagnostico completo -> {RUTA_DETALLE}")
    print()
    print("AVISO: Verificar manualmente en SNCZI (sig.mapama.gob.es/snczi)")
    print("   las capas ZFP, T100 y T500 para los candidatos aprobados.")
    print()
    print("Siguiente paso: python src/05_extraccion_tiempos_osrm.py")
    print()