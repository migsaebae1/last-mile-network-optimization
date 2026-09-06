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
import numpy as np
import pandas as pd
from tqdm import tqdm

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
#  CONFIGURACION -- EDITAR AQUI
# ============================================================
MODO = "candidatos"
# "candidatos"   -> Pipeline D (MCDA): lee candidatos_filtrados.csv
# "depots_fijos" -> Pipeline B/C: usa la lista DEPOTS_FIJOS

DEPOTS_FIJOS = [
    {"Nombre": "DQA4", "Latitud": 37.346775, "Longitud": -6.002706},
    {"Nombre": "SVQ1", "Latitud": 37.271335, "Longitud": -5.988073},
]

PAUSA_OSRM_SEG     = 1.5   # Pausa entre consultas (respeto al servidor publico)
TIMEOUT_OSRM_SEG   = 10    # Timeout por consulta
VELOCIDAD_FALLBACK = 50    # km/h si OSRM no responde (carretera secundaria)

# Curva de correccion de velocidad (distancia_km -> velocidad_objetivo_km/h)
# Refleja la velocidad media real Amazon: urbano 25 km/h, interurbano 80 km/h.
# Max delta respecto a OSRM: +20 km/h. Tiempo minimo: 5 min.
DIST_REF = [0, 50, 100, 200]
VEL_REF  = [25, 40,  55,  80]

# ============================================================
#  RUTAS
# ============================================================
_CAND_FILTRADOS  = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
_CAND_ORIGINAL   = os.path.join(BASE_DIR, "data", "raw", "candidatos_poligonos_industriales.csv")
RUTA_CANDIDATOS  = _CAND_FILTRADOS if os.path.exists(_CAND_FILTRADOS) else _CAND_ORIGINAL
RUTA_DATOS       = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
RUTA_CHECKPOINTS = os.path.join(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")


# ============================================================
#  FUNCIONES
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def corregir_tiempo(dist_km, tiempo_mins):
    """
    Correccion progresiva de velocidad segun distancia (curva VEL_REF/DIST_REF).
    Limita el incremento a +20 km/h sobre OSRM; nunca empeora; minimo 5 min.
    """
    if dist_km <= 0 or tiempo_mins <= 0:
        return max(tiempo_mins, 5.0)
    vel_orig      = (dist_km / tiempo_mins) * 60
    vel_objetivo  = float(np.interp(dist_km, DIST_REF, VEL_REF))
    vel_corregida = min(vel_objetivo, vel_orig + 20)
    vel_final     = max(vel_orig, vel_corregida)
    return max(round((dist_km / vel_final) * 60, 2), 5.0)


def obtener_ruta_osrm(origen, destino):
    """Devuelve (dist_km, tiempo_mins, es_fallback). origen/destino: dict con 'lat' y 'lon'."""
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{origen['lon']},{origen['lat']};{destino['lon']},{destino['lat']}?overview=false"
    )
    try:
        resp = requests.get(url, timeout=TIMEOUT_OSRM_SEG)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == "Ok":
                dist_km    = round(data["routes"][0]["distance"] / 1000, 2)
                tiempo_min = round(data["routes"][0]["duration"] / 60, 2)
                return dist_km, tiempo_min, False
    except Exception:
        pass
    dist_km    = haversine(origen["lat"], origen["lon"], destino["lat"], destino["lon"])
    tiempo_min = round((dist_km / VELOCIDAD_FALLBACK) * 60, 2)
    return round(dist_km, 2), tiempo_min, True


def _slug(nombre):
    return "".join(c if c.isalnum() or c == "_" else "_" for c in str(nombre))[:40]


def ruta_checkpoint(nombre):
    """Compatible con 06_rutas_N_centros.py y 08_comparacion_alternativas.py."""
    return os.path.join(RUTA_CHECKPOINTS, f"tiempos_{_slug(nombre)}_checkpoint.csv")


def cargar_checkpoint(nombre):
    ruta = ruta_checkpoint(nombre)
    if not os.path.exists(ruta):
        return {}
    try:
        df = pd.read_csv(ruta, dtype={"seccion_ine": str})
        return {
            str(r["seccion_ine"]): {
                "distancia_km": float(r["distancia_km"]),
                "tiempo_mins":  float(r["tiempo_mins"]),
                "fallback":     bool(int(r.get("fallback", 0))),
            }
            for _, r in df.iterrows()
        }
    except Exception:
        return {}


def guardar_checkpoint(nombre, resultados):
    os.makedirs(RUTA_CHECKPOINTS, exist_ok=True)
    filas = [
        {"seccion_ine": k, "distancia_km": v["distancia_km"],
         "tiempo_mins": v["tiempo_mins"], "fallback": int(v["fallback"])}
        for k, v in resultados.items()
    ]
    pd.DataFrame(filas).to_csv(ruta_checkpoint(nombre), index=False)


def calcular_tiempos_secciones(origen_row, df_secciones):
    """
    Calcula tiempos OSRM (con correccion progresiva) desde un origen a todas las
    secciones. origen_row: dict o Series con keys Nombre, Latitud, Longitud.
    Devuelve dict {seccion_ine_str: {distancia_km, tiempo_mins, fallback}}.
    """
    nombre     = origen_row["Nombre"]
    origen     = {"lat": float(origen_row["Latitud"]), "lon": float(origen_row["Longitud"])}
    resultados = cargar_checkpoint(nombre)

    pendientes = [
        row for _, row in df_secciones.iterrows()
        if str(int(row["Seccion INE"])) not in resultados
    ]

    if not pendientes:
        print(f"    [OK] Ya calculado (checkpoint completo)")
        return resultados

    n_fallback = 0
    for fila in tqdm(pendientes, desc=f"  {nombre[:35]}", unit="secc"):
        ine_key = str(int(fila["Seccion INE"]))
        destino = {"lat": float(fila["Latitud"]), "lon": float(fila["Longitud"])}
        dist_km, tiempo_mins, es_fallback = obtener_ruta_osrm(origen, destino)
        tiempo_mins = corregir_tiempo(dist_km, tiempo_mins)
        resultados[ine_key] = {
            "distancia_km": dist_km,
            "tiempo_mins":  tiempo_mins,
            "fallback":     es_fallback,
        }
        if es_fallback:
            n_fallback += 1
        if len(resultados) % 50 == 0:
            guardar_checkpoint(nombre, resultados)
        time.sleep(PAUSA_OSRM_SEG)

    guardar_checkpoint(nombre, resultados)
    if n_fallback > 0:
        print(f"    [!] {n_fallback} secciones por Haversine (OSRM no disponible)")
    return resultados


# ============================================================
#  PROGRAMA PRINCIPAL
# ============================================================

if __name__ == "__main__":
    if MODO not in ("candidatos", "depots_fijos"):
        print(f"ERROR: MODO debe ser 'candidatos' o 'depots_fijos', no '{MODO}'")
        sys.exit(1)

    # --- Cabecera ---
    print("=" * 60)
    if MODO == "candidatos":
        print("  PASO 2/5 MCDA -- TIEMPOS DE CONDUCCION POR CANDIDATO")
        print("  (candidato -> 657 secciones censales via OSRM)")
    else:
        print("  TIEMPOS OSRM -- DEPOTS FIJOS")
        print("  (depot -> 657 secciones censales via OSRM)")
    print("=" * 60)

    # --- Cargar origenes ---
    if MODO == "candidatos":
        if not os.path.exists(RUTA_CANDIDATOS):
            print(f"\nNo encontrado: {RUTA_CANDIDATOS}")
            print("Ejecuta primero 03_generador_candidatos.py")
            sys.exit(1)
        df_origenes = pd.read_csv(RUTA_CANDIDATOS, encoding="utf-8-sig")
        df_origenes = df_origenes.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)
    else:
        df_origenes = pd.DataFrame(DEPOTS_FIJOS)

    # --- Cargar secciones ---
    df_secciones = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
    df_secciones["Seccion INE"] = df_secciones["Seccion INE"].astype(int)
    df_secciones = df_secciones.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)

    n          = len(df_origenes)
    consultas  = n * len(df_secciones)
    tiempo_est = round(consultas * PAUSA_OSRM_SEG / 60, 1)

    if n <= 5:
        lista_nombres = ", ".join(df_origenes["Nombre"].tolist())
    else:
        lista_nombres = ", ".join(df_origenes["Nombre"].tolist()[:3]) + f" ... (+{n - 3} mas)"

    print(f"\n  Modo:      {MODO}")
    print(f"  Origenes:  {n}  [{lista_nombres}]")
    print(f"  Secciones: {len(df_secciones)}")
    print(f"  Consultas OSRM estimadas: {consultas:,}")
    print(f"  Tiempo estimado: ~{tiempo_est} min (los checkpoints permiten reanudar)")
    print()
    resp = input("Continuar? (s/n): ").strip().lower()
    if resp not in ("s", "si", "si", "y", "yes"):
        print("Proceso cancelado.")
        sys.exit(0)

    # --- Calcular matriz de tiempos origen -> secciones ---
    print("\n--- Calculando tiempos origen -> secciones ---")
    for i, (_, origen_row) in enumerate(df_origenes.iterrows(), 1):
        print(f"\n[{i}/{n}] {origen_row['Nombre']}")
        calcular_tiempos_secciones(origen_row, df_secciones)

    # --- Resumen final ---
    print()
    print("=" * 60)
    print("  Tiempos calculados correctamente.")
    for _, origen_row in df_origenes.iterrows():
        ruta = ruta_checkpoint(origen_row["Nombre"])
        if os.path.exists(ruta):
            df_ck = pd.read_csv(ruta)
            n_fb  = df_ck["fallback"].sum()
            print(f"  {origen_row['Nombre']}: {len(df_ck)} secciones | {n_fb} fallbacks")
            print(f"  -> {ruta}")
    print()
    if MODO == "candidatos":
        print("  Siguiente paso: python src/06_rutas_N_centros.py  (N = 1,2,3,4,5,8)")
        print("                  luego python src/07_seleccion_mejor_candidato.py")
    else:
        print("  Siguiente paso: python src/06_rutas_svq1_dqa4.py")
        print("                  luego python src/08_comparacion_alternativas.py")
    print("=" * 60)