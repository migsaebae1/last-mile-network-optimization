# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import time
import math
import osmnx as ox
import geopandas as gpd
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz del repositorio

# ============================================================
#  CONFIGURACIÓN - EDITAR AQUÍ
# ============================================================
PROVINCIAS = [
    "Provincia de Sevilla, Andalucía, España",
    "Provincia de Huelva, Andalucía, España",
    "Provincia de Córdoba, Andalucía, España",
    "Provincia de Cádiz, Andalucía, España",
]

AREA_MINIMA_SUELO_M2    = 100_000   # 10 ha — suelo industrial / comercial / brownfield / greenfield
AREA_MINIMA_NAVE_M2     =   5_000   # 0.5 ha — naves individuales (warehouse / building:industrial)
AREA_MINIMA_LOGISTICA_M2 = 10_000   # 1 ha — parques logísticos y zonas portuarias
AREA_MINIMA_PARKING_M2  =   2_000   # 0.2 ha — parking de camiones

DIST_DEDUPLICACION_M    =    500    # Distancia mínima entre centroides (elimina duplicados de tags)
MAX_CANDIDATOS_TOTAL    =      0    # 0 = sin límite; >0 = conservar los N más grandes por área
EPSG_METRICO            =  32630    # UTM Zona 30N — sistema de referencia métrico para Andalucía

RUTA_SALIDA      = os.path.join(BASE_DIR, "data",    "raw", "candidatos_poligonos_industriales.csv")
RUTA_CHECKPOINT  = os.path.join(BASE_DIR, "outputs", "csv", "candidatos_bruto_checkpoint.csv")
RUTA_PROGRESO    = os.path.join(BASE_DIR, "outputs", "csv", "candidatos_progreso.csv")

# ============================================================
#  DEFINICIÓN DE BÚSQUEDAS OSM

# ============================================================
BUSQUEDAS = [
    ({"landuse": "industrial"},  AREA_MINIMA_SUELO_M2,    "industrial"),
    ({"landuse": "brownfield"},  AREA_MINIMA_SUELO_M2,    "brownfield"),
    ({"landuse": "greenfield"},  AREA_MINIMA_SUELO_M2,    "greenfield"),
    ({"landuse": "commercial"},  AREA_MINIMA_SUELO_M2,    "comercial"),
    ({"building": "warehouse"},  AREA_MINIMA_NAVE_M2,     "almacen"),
    ({"building": "industrial"}, AREA_MINIMA_NAVE_M2,     "nave_industrial"),
    ({"industrial": "logistics"},AREA_MINIMA_LOGISTICA_M2,"logistica"),
    ({"industrial": "port"},     AREA_MINIMA_LOGISTICA_M2,"puerto"),
    ({"amenity": "truck_parking"},AREA_MINIMA_PARKING_M2, "parking_camiones"),
]


# ============================================================
#  FUNCIONES
# ============================================================

def cargar_checkpoint():
    """
    Carga el progreso guardado de una ejecución anterior.
    Devuelve (df_bruto, conjunto_completados) donde conjunto_completados
    es un set de strings "provincia|tipo" ya procesados.
    """
    df_bruto = pd.DataFrame()
    completados = set()

    if os.path.exists(RUTA_CHECKPOINT):
        try:
            df_bruto = pd.read_csv(RUTA_CHECKPOINT, encoding="utf-8-sig")
            print(f"  ♻️  Checkpoint encontrado: {len(df_bruto)} candidatos brutos recuperados.")
        except Exception:
            df_bruto = pd.DataFrame()

    if os.path.exists(RUTA_PROGRESO):
        try:
            df_prog = pd.read_csv(RUTA_PROGRESO, encoding="utf-8-sig")
            completados = set(f"{r['provincia']}|{r['tipo']}" for _, r in df_prog.iterrows())
            print(f"  ♻️  Progreso encontrado: {len(completados)} búsquedas ya completadas.")
        except Exception:
            completados = set()

    return df_bruto, completados


def guardar_checkpoint(df_bruto_acumulado, provincia, tipo):
    """Guarda el estado actual tras completar una búsqueda (provincia, tipo)."""
    os.makedirs(os.path.dirname(RUTA_CHECKPOINT), exist_ok=True)
    df_bruto_acumulado.to_csv(RUTA_CHECKPOINT, index=False, encoding="utf-8-sig")

    # Añadir esta combinación al registro de progreso
    nueva_fila = pd.DataFrame([{"provincia": provincia, "tipo": tipo}])
    if os.path.exists(RUTA_PROGRESO):
        try:
            df_prog = pd.read_csv(RUTA_PROGRESO, encoding="utf-8-sig")
            df_prog = pd.concat([df_prog, nueva_fila], ignore_index=True)
        except Exception:
            df_prog = nueva_fila
    else:
        df_prog = nueva_fila
    df_prog.to_csv(RUTA_PROGRESO, index=False, encoding="utf-8-sig")


def limpiar_checkpoints():
    """Elimina los archivos de checkpoint una vez finalizado el proceso."""
    for ruta in [RUTA_CHECKPOINT, RUTA_PROGRESO]:
        if os.path.exists(ruta):
            os.remove(ruta)


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos GPS."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def descargar_poligonos(nombre_provincia, tags, area_minima_m2, tipo):
    """
    Descarga features de OSM para una provincia y un conjunto de tags.
    Filtra por tipo de geometría (solo polígonos) y por área mínima.
    Devuelve un DataFrame con las columnas estándar o None si no hay resultados.
    """
    try:
        gdf = ox.features_from_place(nombre_provincia, tags)
    except Exception as e:
        # Es normal que algunas combinaciones de tags no tengan datos en ciertas provincias
        return None

    # Filtrar solo polígonos (descartar nodos puntuales y líneas)
    mascara_poligono = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    gdf = gdf[mascara_poligono].copy()

    if gdf.empty:
        return None

    # Proyectar a UTM para medir áreas en m²
    gdf_utm = gdf.to_crs(epsg=EPSG_METRICO)
    
    gdf_utm = gdf_utm[gdf_utm.geometry.area > area_minima_m2].copy()

    if gdf_utm.empty:
        return None

    # Volver a WGS84 y extraer centroides
    gdf_wgs = gdf_utm.to_crs(epsg=4326)
    centroides = gdf_utm.geometry.centroid.to_crs(epsg=4326)

    # Extraer columnas útiles de OSM con manejo seguro de campos opcionales
    # Bug fix: np.nan sobrevive astype(str) como float nan; fillna("") lo neutraliza antes.
    # _col combina varias columnas tomando el primer valor no vacío por fila (no solo la primera columna existente).
    _NULOS = {"nan", "None", "<NA>", "NaT", "none", "null", "NULL"}

    def _col(gdf, *nombres):
        result = pd.Series("", index=gdf.index)
        for n in reversed(nombres):          # reversed → el primer nombre listado tiene prioridad
            if n not in gdf.columns:
                continue
            vals = gdf[n].fillna("").astype(str)
            vals = vals.where(~vals.isin(_NULOS), "")
            result = result.where(vals == "", vals)   # vals sobreescribe donde no está vacío
        return result

    nombre_osm    = _col(gdf_wgs, "name")
    municipio_osm = _col(gdf_wgs, "addr:city", "addr:municipality", "addr:town")
    provincia_corta = nombre_provincia.split(",")[0].replace("Provincia de ", "")

    def _scalar(series, idx):
        """Devuelve siempre un str escalar aunque el índice esté duplicado."""
        val = series.get(idx, "")
        if isinstance(val, pd.Series):
            val = val.iloc[0] if not val.empty else ""
        v = str(val) if val is not None else ""
        return "" if v in _NULOS else v   # Bug fix: str(np.nan)="nan" es truthy; lo limpiamos aquí

    indices_list = list(gdf_utm.index)
    filas = []
    for pos, idx in enumerate(indices_list):
        nombre_val    = _scalar(nombre_osm, idx)
        municipio_raw = _scalar(municipio_osm, idx)
        municipio_val = municipio_raw if municipio_raw else provincia_corta  # Bug fix: "nan" era truthy
        geom_utm      = gdf_utm.geometry.iloc[pos]
        area_ha       = round(geom_utm.area / 10_000, 2)
        lat           = round(centroides.iloc[pos].y, 6)
        lon           = round(centroides.iloc[pos].x, 6)

        filas.append({
            "Nombre":      nombre_val or f"Poligono_{tipo.capitalize()}",
            "Latitud":     lat,
            "Longitud":    lon,
            "Municipio":   municipio_val,
            "Tipo":        tipo,
            "Area_Ha":     area_ha,
            "Descripcion": f"OSM: {tipo} | {area_ha:.1f} ha | {provincia_corta}",
        })

    return pd.DataFrame(filas)


def deduplicar_por_proximidad(df, distancia_min_m=DIST_DEDUPLICACION_M):
    """
    Elimina filas cuyo centroide esté a menos de `distancia_min_m` metros de uno ya incluido.
    Entre dos candidatos cercanos, mantiene el de mayor área.
    """
    df_ord = df.sort_values("Area_Ha", ascending=False).reset_index(drop=True)
    conservar = []
    coords_conservados = []

    for _, fila in df_ord.iterrows():
        lat, lon = fila["Latitud"], fila["Longitud"]
        demasiado_cerca = False
        for lat_c, lon_c in coords_conservados:
            if haversine_m(lat, lon, lat_c, lon_c) < distancia_min_m:
                demasiado_cerca = True
                break
        if not demasiado_cerca:
            conservar.append(fila)
            coords_conservados.append((lat, lon))

    return pd.DataFrame(conservar).reset_index(drop=True)


_NULOS_NOMBRE = {"nan", "None", "<NA>", "NaT", "none", "null", "NULL"}

def asignar_nombres_unicos(df):
    """
    Añade un sufijo numérico a los candidatos sin nombre, con nombre nulo o con nombre duplicado.
    """
    contador = {}
    nombres_nuevos = []
    for _, fila in df.iterrows():
        nombre = fila["Nombre"].strip()
        # Bug fix: "nan" es truthy pero no es un nombre válido
        if not nombre or nombre in _NULOS_NOMBRE or nombre.startswith("Poligono_"):
            tipo = fila["Tipo"].capitalize()
            n = contador.get(tipo, 0) + 1
            contador[tipo] = n
            nombre = f"Poligono_{tipo}_{n:03d}"
        nombres_nuevos.append(nombre)
    df = df.copy()
    df["Nombre"] = nombres_nuevos
    return df


# ============================================================
#  PROGRAMA PRINCIPAL
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  GENERADOR DE CANDIDATOS LOGÍSTICOS — OpenStreetMap")
    print("=" * 60)
    print(f"Provincias: {', '.join(p.split(',')[0] for p in PROVINCIAS)}")
    print(f"Tipos de búsqueda: {len(BUSQUEDAS)}")
    print()

    # Cargar progreso anterior si existe
    df_checkpoint, completados = cargar_checkpoint()
    todos_candidatos = [df_checkpoint] if not df_checkpoint.empty else []
    resumen = {}

    for nombre_provincia in PROVINCIAS:
        provincia_corta = nombre_provincia.split(",")[0].replace("Provincia de ", "")
        print(f"\n--- {provincia_corta} ---")
        n_provincia = 0

        for tags, area_min, tipo in BUSQUEDAS:
            clave = f"{provincia_corta}|{tipo}"
            tag_str = list(tags.items())[0]

            # Saltar si ya está completado en una ejecución anterior
            if clave in completados:
                print(f"  [ya hecho] {tag_str[0]}={tag_str[1]}")
                continue

            print(f"  Buscando {tag_str[0]}={tag_str[1]} (>= {area_min/10_000:.1f} ha)...", end=" ", flush=True)
            df_parcial = descargar_poligonos(nombre_provincia, tags, area_min, tipo)

            if df_parcial is not None and not df_parcial.empty:
                print(f"{len(df_parcial)} encontrados")
                todos_candidatos.append(df_parcial)
                n_provincia += len(df_parcial)
            else:
                print("0 encontrados")

            # Guardar checkpoint tras cada búsqueda (con o sin resultados)
            df_acumulado = pd.concat(todos_candidatos, ignore_index=True) if todos_candidatos else pd.DataFrame()
            guardar_checkpoint(df_acumulado, provincia_corta, tipo)
            completados.add(clave)

            time.sleep(1)  # Pausa de cortesía con Nominatim/Overpass API

        resumen[provincia_corta] = n_provincia
        print(f"  → Subtotal {provincia_corta}: {n_provincia} candidatos")

    if not todos_candidatos:
        print("\n⚠️  No se encontraron candidatos. Comprueba la conexión a internet y que osmnx esté instalado.")
        exit(1)

    # Combinar y deduplicar
    print("\n" + "=" * 60)
    df_total = pd.concat(todos_candidatos, ignore_index=True).drop_duplicates(
        subset=["Latitud", "Longitud", "Tipo"]
    ).reset_index(drop=True)
    print(f"Total bruto (con posibles duplicados): {len(df_total)}")

    df_dedup = deduplicar_por_proximidad(df_total)
    print(f"Total tras deduplicar (>{DIST_DEDUPLICACION_M} m entre centroides): {len(df_dedup)}")

    df_final = asignar_nombres_unicos(df_dedup)

    # Ordenar: primero los más grandes, luego alfabético por nombre
    df_final = df_final.sort_values(["Area_Ha"], ascending=False).reset_index(drop=True)

    # Aplicar límite de candidatos (los N más grandes por área); 0 = sin límite
    if MAX_CANDIDATOS_TOTAL > 0 and len(df_final) > MAX_CANDIDATOS_TOTAL:
        print(f"Aplicando límite MAX_CANDIDATOS_TOTAL={MAX_CANDIDATOS_TOTAL} (se descartan {len(df_final) - MAX_CANDIDATOS_TOTAL} menores)")
        df_final = df_final.head(MAX_CANDIDATOS_TOTAL).reset_index(drop=True)
    else:
        print(f"Sin límite de candidatos — se conservan todos: {len(df_final)}")

    # Guardar CSV
    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)
    df_final.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("  RESUMEN FINAL")
    print("=" * 60)
    for prov, n in resumen.items():
        print(f"  {prov:<25} → {n:>3} candidatos")
    limite_str = f"max={MAX_CANDIDATOS_TOTAL}" if MAX_CANDIDATOS_TOTAL > 0 else "sin límite"
    print(f"  {f'TOTAL (final, {limite_str})':<25} → {len(df_final):>3} candidatos")
    print()
    print(f"✅ CSV guardado en: {RUTA_SALIDA}")

    # Limpiar checkpoints — ya no hacen falta
    limpiar_checkpoints()
    print("   (checkpoints de progreso eliminados)")
    print()
    print("Primeros 5 candidatos por tamaño:")
    print(df_final[["Nombre", "Municipio", "Tipo", "Area_Ha"]].head().to_string(index=False))
    print()
    print("Siguiente paso: python src/04_filtro_candidatos.py")