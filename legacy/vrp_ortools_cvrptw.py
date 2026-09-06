# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import sys
import math
import time

# Windows Python 3.8+: pre-load OR-Tools native DLLs before the package __init__
# runs its own loader, which uses WinDLL without os.add_dll_directory.
if os.name == "nt":
    try:
        import importlib.util, ctypes
        _ortools_spec = importlib.util.find_spec("ortools")
        if _ortools_spec:
            _libs_dir = os.path.join(os.path.dirname(_ortools_spec.origin), ".libs")
            if os.path.isdir(_libs_dir):
                os.add_dll_directory(_libs_dir)
                for _dll in ["zlib1.dll", "bz2.dll", "abseil_dll.dll",
                             "libutf8_validity.dll", "re2.dll", "libprotobuf.dll",
                             "highs.dll", "libscip.dll", "ortools.dll"]:
                    _p = os.path.join(_libs_dir, _dll)
                    if os.path.exists(_p):
                        ctypes.WinDLL(_p)
    except Exception:
        pass  # non-Windows or DLLs already in PATH

# OR-Tools must be imported BEFORE numpy/pandas: numpy loads an older libprotobuf
# that conflicts with OR-Tools' bundled version (WinError 127 on re2/protobuf/ortools).
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
#  CONFIGURACION — EDITAR AQUI
# ============================================================
MODO = "A2"                # "A1" | "A2" | "candidatos"
K_MAX = 6                  # solo modo candidatos: K=1..K_MAX
METODO_PMEDIAN = "exacto"  # "exacto" (C(N,K) combinations) | "greedy"

# VRP
CAPACIDAD_FURGONETA  = 120
CAPACIDAD_EFECTIVA   = CAPACIDAD_FURGONETA  # 120 pkg — tasa de fallo no afecta capacidad de carga
JORNADA_MAX_MIN      = 480
TIEMPO_CARGA_MIN     = 45   # carga inicial en depot (min)
TIEMPO_RECARGA_MIN   = 20   # recarga entre viajes del mismo camión (min)
TIEMPO_ENTREGA_MIN   = 3
VELOCIDAD_MEDIA_KMH  = 40   # fallback Haversine depot<->nodo sin OSRM
VELOCIDAD_INTERNODO  = 40   # km/h para tramos nodo->nodo (Haversine)
COSTE_KM             = 0.35
COSTE_HORA_CONDUCTOR = 14.0
COSTE_FIJO_FURGONETA = 50.0   # €/día por furgoneta activada (alquiler, seguro, amortización)
DIA_SIMULACION       = "media"    # "media" | "dia_N"
GUARDAR_DETALLE_RUTAS = True
CO2_KG_POR_KM        = 0.21

# OR-Tools
ORTOOLS_TIME_LIMIT_S    = 60   # segundos máximos para GLS (instancias pequeñas / candidatos)
ZONA_TAM_MAX            = 40   # nodos máximos por zona OR-Tools
ZONA_TIME_LIMIT_S       = 30   # segundos por zona — primer pase
ZONA_TIME_LIMIT_S_2PASE = 90   # segundos por zona — segundo pase (con GLS, menos zonas)
RESCUE_RESIDUAL_ACTIVO  = True # False → diagnóstico: ver cuántos nodos caen sin rescate
# Escalado monetario para OR-Tools (requiere enteros).
# 1 unidad interna = 1/60 € → los tres coeficientes son exactamente enteros:
#   0.35 €/km × 60 = 21  |  14 €/h / 60 min × 60 = 14  |  50 €/van × 60 = 3 000
ESCALA_COSTE   = 60
COSTE_KM_INT   = round(COSTE_KM * ESCALA_COSTE)                      # 21 u/km
COSTE_MIN_INT  = round(COSTE_HORA_CONDUCTOR / 60 * ESCALA_COSTE)      # 14 u/min
COSTE_FIJO_INT = round(COSTE_FIJO_FURGONETA * ESCALA_COSTE)           # 3 000 u/van
# Escalado de demanda: OR-Tools requiere enteros.
# Multiplicamos demanda y capacidad por DEMANDA_ESCALA y redondeamos.
DEMANDA_ESCALA = 10

# Depots fijos
DEPOT_SVQ1 = {"nombre": "SVQ1", "lat": 37.271335, "lon": -5.988073}
DEPOT_DQA4 = {"nombre": "DQA4", "lat": 37.346775, "lon": -6.002706}

# ============================================================
#  RUTAS
# ============================================================
_CAND_FILTRADOS = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
_CAND_ORIGINAL  = os.path.join(BASE_DIR, "data", "raw", "candidatos_poligonos_industriales.csv")
RUTA_CANDIDATOS  = _CAND_FILTRADOS if os.path.exists(_CAND_FILTRADOS) else _CAND_ORIGINAL
RUTA_DATOS       = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
RUTA_DEMANDA     = os.path.join(BASE_DIR, "outputs", "xlsx", "Demanda_Amazon_365_Mejorada.xlsx")
RUTA_CHECKPOINTS = os.path.join(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")
RUTA_VRP_RES     = os.path.join(BASE_DIR, "outputs", "csv", "vrp_resultados")
RUTA_VRP_RUTAS   = os.path.join(BASE_DIR, "outputs", "csv", "vrp_rutas")
RUTA_P_MEDIAN    = os.path.join(BASE_DIR, "outputs", "csv", "p_median")
RUTA_CSV_ROOT    = os.path.join(BASE_DIR, "outputs", "csv")
RUTA_XLSX        = os.path.join(BASE_DIR, "outputs", "xlsx")

# ============================================================
#  FUNCIONES AUXILIARES
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def haversine_vectorizado(lat_ref, lon_ref, lats_arr, lons_arr):
    R = 6371.0
    lat1   = math.radians(lat_ref)
    lon1   = math.radians(lon_ref)
    lats_r = np.radians(lats_arr)
    lons_r = np.radians(lons_arr)
    dlat   = lats_r - lat1
    dlon   = lons_r - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lats_r) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _slug(nombre):
    return "".join(c if c.isalnum() or c == "_" else "_" for c in str(nombre))[:40]


def cargar_demanda():
    print("  Cargando demanda...", end=" ", flush=True)
    df = pd.read_excel(RUTA_DEMANDA)
    df_sin_fecha = df.drop(columns=["Fecha"])
    if DIA_SIMULACION == "media":
        demanda = df_sin_fecha.mean()
        print(f"media {len(df)} dias ({demanda.sum():.0f} paq/dia)")
    elif DIA_SIMULACION.startswith("dia_"):
        idx = int(DIA_SIMULACION.split("_")[1]) - 1
        demanda = df_sin_fecha.iloc[idx]
        print(f"dia {idx + 1} ({demanda.sum():.0f} paq)")
    else:
        raise ValueError(f"DIA_SIMULACION '{DIA_SIMULACION}' no reconocido. Usa 'media' o 'dia_N'.")
    return demanda


def preparar_nodos(df_secciones, demanda):
    nodos = []
    for _, row in df_secciones.iterrows():
        codigo = str(int(row["Seccion INE"]))
        dem = float(demanda.get(codigo, 0))
        if dem > 0:
            nodos.append({
                "id":      codigo,
                "lat":     float(row["Latitud"]),
                "lon":     float(row["Longitud"]),
                "demanda": dem,
                "peso":    float(row.get("Peso", dem)),
            })
    return nodos


def cargar_tiempos_osrm(nombre):
    """Reads OSRM checkpoint. Returns {ine: tiempo_mins} or None."""
    ruta = os.path.join(RUTA_CHECKPOINTS, f"tiempos_{_slug(nombre)}_checkpoint.csv")
    if not os.path.exists(ruta):
        return None
    try:
        df = pd.read_csv(ruta, dtype={"seccion_ine": str})
        return df.set_index("seccion_ine")["tiempo_mins"].astype(float).to_dict()
    except Exception:
        return None


def cargar_distancias_osrm(nombre):
    """Reads OSRM checkpoint. Returns {ine: distancia_km} or None."""
    ruta = os.path.join(RUTA_CHECKPOINTS, f"tiempos_{_slug(nombre)}_checkpoint.csv")
    if not os.path.exists(ruta):
        return None
    try:
        df = pd.read_csv(ruta, dtype={"seccion_ine": str})
        return df.set_index("seccion_ine")["distancia_km"].astype(float).to_dict()
    except Exception:
        return None


# ============================================================
#  HELPERS
# ============================================================

def _split_nodos(nodos, capacidad):
    """
    Split nodes with demand > capacidad into sub-nodes at the same location.
    Each sub-node gets demand = demand/k (evenly divided, rounded).
    OR-Tools requires every node's demand ≤ vehicle capacity to be feasible.
    """
    result = []
    for nd in nodos:
        dem = nd["demanda"]
        if dem <= capacidad:
            result.append(nd)
        else:
            k = math.ceil(dem / capacidad)
            chunk = dem / k
            for _ in range(k):
                result.append({**nd, "demanda": chunk})
    return result


# ============================================================
#  CONSTRUCCION DE MATRIZ DE TIEMPOS Y KM PARA OR-TOOLS
# ============================================================

def construir_matrices_depot(depot, nodos, tiempos_depot, distancias_depot):
    """
    Builds (N+1) x (N+1) time and km matrices for one depot.

    Index 0 = depot. Indices 1..N = nodos in order.

    Time logic:
      depot <-> nodo : OSRM tiempo_mins if available, else Haversine/VELOCIDAD_MEDIA_KMH
      nodo  <-> nodo : Haversine / VELOCIDAD_INTERNODO (interurban network approximation)

    Km logic:
      depot <-> nodo : OSRM distancia_km if available, else Haversine
      nodo  <-> nodo : Haversine
    """
    n = len(nodos)
    N = n + 1  # depot at index 0

    lats = np.array([depot["lat"]] + [nd["lat"] for nd in nodos])
    lons = np.array([depot["lon"]] + [nd["lon"] for nd in nodos])
    ids  = [None] + [nd["id"] for nd in nodos]  # ids[0] = None (depot)

    # Full Haversine distance matrix (N x N), used as fallback
    hav = np.zeros((N, N))
    for i in range(N):
        hav[i] = haversine_vectorizado(lats[i], lons[i], lats, lons)

    # Initialize all arcs as node-node (Haversine / interurban speed)
    time_matrix = hav / VELOCIDAD_INTERNODO * 60
    km_matrix   = hav.copy()

    # Override depot <-> node arcs with OSRM values (N iterations only)
    for j in range(1, N):
        nid = ids[j]
        t  = (tiempos_depot.get(nid,    hav[0, j] / VELOCIDAD_MEDIA_KMH * 60)
              if tiempos_depot else hav[0, j] / VELOCIDAD_MEDIA_KMH * 60)
        km = (distancias_depot.get(nid, hav[0, j])
              if distancias_depot else hav[0, j])
        time_matrix[0, j] = time_matrix[j, 0] = t
        km_matrix[0,   j] = km_matrix[j,   0] = km

    np.fill_diagonal(time_matrix, 0)
    np.fill_diagonal(km_matrix,   0)

    return time_matrix, km_matrix


# ============================================================
#  MOTOR VRP — OR-TOOLS
# ============================================================

def _vrp_ortools_zona(depot, nodos_zona, id_camion_inicio, time_matrix, km_matrix,
                      time_limit_s=None):
    """
    OR-Tools CVRPTW solver for a single geographic zone.
    time_matrix and km_matrix are (len(nodos_zona)+1)×(len(nodos_zona)+1) with index 0 = depot.
    Returns list of route dicts.
    """
    if time_limit_s is None:
        time_limit_s = ZONA_TIME_LIMIT_S
    n = len(nodos_zona)
    if n == 0:
        return []

    demandas_raw = [nd["demanda"] for nd in nodos_zona]
    demandas_int = [0] + [max(1, round(d * DEMANDA_ESCALA)) for d in demandas_raw]
    cap_int      = CAPACIDAD_EFECTIVA * DEMANDA_ESCALA

    time_int = np.round(time_matrix).astype(int)

    demanda_total   = sum(demandas_raw)
    umbral_solo     = JORNADA_MAX_MIN * 0.75
    n_solos         = sum(
        1 for i in range(n)
        if (time_matrix[0, i + 1] * 2 + TIEMPO_CARGA_MIN) > umbral_solo
    )
    n_vehiculos     = max(math.ceil(demanda_total / CAPACIDAD_EFECTIVA), n_solos) + 2
    jornada_max     = int(JORNADA_MAX_MIN - TIEMPO_CARGA_MIN)

    manager  = pywrapcp.RoutingIndexManager(n + 1, n_vehiculos, 0)
    routing  = pywrapcp.RoutingModel(manager)

    # Dimensión Tiempo (minutos): restringe jornada — no usada como coste.
    time_dim = time_int.copy()
    for i in range(1, n + 1):
        time_dim[i, :] += round(TIEMPO_ENTREGA_MIN * demandas_raw[i - 1])
    np.fill_diagonal(time_dim, 0)
    time_cb = routing.RegisterTransitMatrix(time_dim.tolist())
    routing.AddDimension(time_cb, 0, jornada_max, True, "Tiempo")

    # Función objetivo: min Σ_v [50€·x_v + Σ_(i,j)(km·0.35 + t·14/60 + 3·dem_j·14/60)]
    # Escalado a enteros: 1 unidad = 1/ESCALA_COSTE €
    cost_matrix = np.round(
        km_matrix * COSTE_KM_INT + time_matrix * COSTE_MIN_INT
    ).astype(int)
    for i in range(1, n + 1):
        cost_matrix[i, :] += round(TIEMPO_ENTREGA_MIN * demandas_raw[i - 1] * COSTE_MIN_INT)
    np.fill_diagonal(cost_matrix, 0)
    cost_cb = routing.RegisterTransitMatrix(cost_matrix.tolist())
    routing.SetArcCostEvaluatorOfAllVehicles(cost_cb)
    routing.SetFixedCostOfAllVehicles(COSTE_FIJO_INT)

    demand_cb = routing.RegisterUnaryTransitVector(demandas_int)
    routing.AddDimensionWithVehicleCapacity(demand_cb, 0, [cap_int] * n_vehiculos, True, "Capacidad")

    # Disjunctions: allow dropping nodes with a steep penalty. This guarantees
    # OR-Tools always returns a (partial) solution instead of None when a zone
    # contains a node that cannot fit any feasible route (e.g. demand rounding
    # edge case or tight time budget). Penalty >> total route cost keeps dropped
    # nodes rare in practice.
    for node_i in range(1, n + 1):
        routing.AddDisjunction([manager.NodeToIndex(node_i)], 1_000_000)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    if time_limit_s > ZONA_TIME_LIMIT_S:
        # Second pass: activate GLS to improve solution quality within the larger budget.
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = time_limit_s

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return []

    rutas     = []
    camion_id = id_camion_inicio
    depot_lat = depot["lat"]
    depot_lon = depot["lon"]

    for v in range(n_vehiculos):
        idx = routing.Start(v)
        if routing.IsEnd(solution.Value(routing.NextVar(idx))):
            continue

        paradas        = []
        km_ruta        = 0.0
        t_acum         = float(TIEMPO_CARGA_MIN)
        paq_total_ruta = 0
        prev_node      = 0

        idx = solution.Value(routing.NextVar(idx))
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            nodo = nodos_zona[node - 1]

            km_tramo = float(km_matrix[prev_node, node])
            t_tramo  = float(time_matrix[prev_node, node])
            paquetes = nodo["demanda"]
            t_acum  += t_tramo + TIEMPO_ENTREGA_MIN * paquetes
            km_ruta += km_tramo
            paq_total_ruta += paquetes

            paradas.append({
                "nodo":                 nodo["id"],
                "paquetes":             paquetes,
                "km_tramo":             round(km_tramo, 3),
                "tiempo_tramo_min":     round(t_tramo, 2),
                "tiempo_acumulado_min": round(t_acum, 2),
                "lat":                  nodo["lat"],
                "lon":                  nodo["lon"],
            })
            prev_node = node
            idx = solution.Value(routing.NextVar(idx))

        if not paradas:
            continue

        km_ret  = float(km_matrix[prev_node, 0])
        t_ret   = float(time_matrix[prev_node, 0])
        km_ruta += km_ret
        t_total  = t_acum + t_ret

        paradas.append({
            "nodo":                 "FIN_RUTA",
            "paquetes":             0,
            "km_tramo":             round(km_ret, 3),
            "tiempo_tramo_min":     round(t_ret, 2),
            "tiempo_acumulado_min": round(t_total, 2),
            "lat":                  depot_lat,
            "lon":                  depot_lon,
        })

        coste_km   = km_ruta * COSTE_KM
        coste_hora = (t_total / 60) * COSTE_HORA_CONDUCTOR
        rutas.append({
            "id_camion":       camion_id,
            "depot_nombre":    depot["nombre"],
            "n_paradas":       len(paradas),
            "paquetes":        round(paq_total_ruta, 4),
            "km_ruta":         round(km_ruta, 2),
            "tiempo_min":      round(t_total, 1),
            "coste_km_eur":    round(coste_km, 2),
            "coste_hora_eur":  round(coste_hora, 2),
            "coste_total_eur": round(coste_km + coste_hora, 2),
            "paradas":         paradas,
        })
        camion_id += 1

    return rutas


def _kmeans_np(X, n_clusters, sample_weight=None, n_init=10, random_state=42, max_iter=300):
    """Pure-numpy weighted K-Means. Avoids sklearn/threadpoolctl DLL conflicts on Windows."""
    rng = np.random.default_rng(random_state)
    n = len(X)
    w = sample_weight / sample_weight.sum() if sample_weight is not None else None

    best_labels, best_inertia = None, float("inf")
    for _ in range(n_init):
        idx = rng.choice(n, n_clusters, replace=False, p=w)
        centers = X[idx].copy()
        labels = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            dists = np.sum((X[:, None, :] - centers[None, :, :]) ** 2, axis=2)
            new_labels = dists.argmin(axis=1)
            new_centers = np.zeros_like(centers)
            for k in range(n_clusters):
                mask = new_labels == k
                if mask.any():
                    wk = sample_weight[mask] if sample_weight is not None else None
                    new_centers[k] = np.average(X[mask], axis=0, weights=wk)
                else:
                    new_centers[k] = centers[k]
            if np.array_equal(new_labels, labels):
                break
            labels, centers = new_labels, new_centers
        inertia = float(np.sum((X - centers[labels]) ** 2))
        if inertia < best_inertia:
            best_inertia, best_labels = inertia, labels.copy()
    return best_labels


def vrp_ortools_depot(depot, nodos, id_camion_inicio, tiempos_depot=None, distancias_depot=None,
                      time_limit_s=None):
    """
    CVRPTW for one depot via OR-Tools.

    Pre-clusters delivery nodes into zones of ≤ZONA_TAM_MAX nodes using
    depot-first radial clustering: K-Means on (OSRM_time_normalised × 2,
    bearing_sin, bearing_cos).  Nodes at similar travel times and in the same
    direction from the depot form a zone, avoiding the arbitrary geographic
    boundaries of pure lat/lon K-Means.
    """
    if time_limit_s is None:
        time_limit_s = ZONA_TIME_LIMIT_S
    if not nodos:
        return []

    nodos = _split_nodos(nodos, CAPACIDAD_EFECTIVA)
    n     = len(nodos)

    k_zonas = max(1, math.ceil(n / ZONA_TAM_MAX))
    k_zonas = min(k_zonas, n)

    if k_zonas == 1:
        labels = np.zeros(n, dtype=int)
    else:
        dep_lat = depot["lat"]
        dep_lon = depot["lon"]
        lats    = np.array([nd["lat"] for nd in nodos])
        lons    = np.array([nd["lon"] for nd in nodos])
        dem     = np.array([nd["demanda"] for nd in nodos])

        # OSRM travel time from depot; Haversine fallback when unavailable.
        if tiempos_depot:
            times = np.array([
                tiempos_depot.get(nd["id"],
                    haversine(dep_lat, dep_lon, nd["lat"], nd["lon"]) / VELOCIDAD_MEDIA_KMH * 60)
                for nd in nodos
            ], dtype=float)
        else:
            times = haversine_vectorizado(dep_lat, dep_lon, lats, lons) / VELOCIDAD_MEDIA_KMH * 60

        t_max = times.max()
        times_norm = times / t_max if t_max > 0 else times

        # Bearing from depot decomposed into (sin, cos) to handle wrap-around.
        dlat = lats - dep_lat
        dlon = lons - dep_lon
        angles = np.arctan2(dlon, dlat)
        bearing_sin = np.sin(angles)
        bearing_cos = np.cos(angles)

        # Weight time 2× more than bearing: time drives feasibility more.
        features = np.column_stack([times_norm * 2.0, bearing_sin, bearing_cos])
        labels = _kmeans_np(features, k_zonas, sample_weight=dem, n_init=10, random_state=42)

    zonas = {}
    for i, nd in enumerate(nodos):
        zonas.setdefault(int(labels[i]), []).append(nd)

    print(f"    {depot['nombre']}: {n} nodos → {k_zonas} zonas OR-Tools "
          f"(~{n // k_zonas} nodos/zona)")

    all_rutas = []
    camion_id = id_camion_inicio

    for zona_nodos in zonas.values():
        if not zona_nodos:
            continue
        time_z, km_z = construir_matrices_depot(depot, zona_nodos, tiempos_depot, distancias_depot)
        zona_rutas    = _vrp_ortools_zona(depot, zona_nodos, camion_id, time_z, km_z, time_limit_s)
        all_rutas.extend(zona_rutas)
        camion_id += len(zona_rutas)

    return all_rutas


# ============================================================
#  MOTOR VRP — OR-TOOLS MULTI-DEPOT GLOBAL
# ============================================================

def construir_matriz_global(depots, nodos, tiempos_por_depot, distancias_por_depot):
    """
    Builds a single (N+D) x (N+D) time and km matrix for all depots + nodes.

    Index layout:
      0 .. D-1       → depots (same order as depots[])
      D .. D+N-1     → delivery nodes (same order as nodos[])

    Time rules:
      depot i → depot j   : 0 (these arcs are never traversed)
      depot i → node j    : OSRM tiempo_mins; fallback Haversine/VELOCIDAD_MEDIA_KMH
      node i  → depot j   : symmetric (same OSRM value)
      node i  → node j    : Haversine / VELOCIDAD_INTERNODO
    Km rules follow the same pattern with distancia_km / Haversine.
    """
    D = len(depots)
    N = len(nodos)
    total = N + D

    lats = np.array([d["lat"] for d in depots] + [n["lat"] for n in nodos])
    lons = np.array([d["lon"] for d in depots] + [n["lon"] for n in nodos])
    ids_nodos = [n["id"] for n in nodos]

    hav = np.zeros((total, total))
    for i in range(total):
        hav[i] = haversine_vectorizado(lats[i], lons[i], lats, lons)

    # Initialize all arcs as node-node (Haversine / interurban speed)
    time_matrix = hav / VELOCIDAD_INTERNODO * 60
    km_matrix   = hav.copy()

    # Zero depot-depot arcs (vehicles never travel between depots)
    time_matrix[:D, :D] = 0.0
    km_matrix[:D,   :D] = 0.0

    # Override depot <-> node arcs with OSRM values (D * N iterations only)
    for d_i, d in enumerate(depots):
        d_name = d["nombre"]
        t_dict = tiempos_por_depot.get(d_name)
        d_dict = (distancias_por_depot or {}).get(d_name)
        for j in range(D, total):
            ine = ids_nodos[j - D]
            t  = (t_dict.get(ine,  hav[d_i, j] / VELOCIDAD_MEDIA_KMH * 60)
                  if t_dict else hav[d_i, j] / VELOCIDAD_MEDIA_KMH * 60)
            km = (d_dict.get(ine, hav[d_i, j])
                  if d_dict else hav[d_i, j])
            time_matrix[d_i, j] = time_matrix[j, d_i] = t
            km_matrix[d_i,   j] = km_matrix[j,   d_i] = km

    np.fill_diagonal(time_matrix, 0)
    np.fill_diagonal(km_matrix,   0)

    return time_matrix, km_matrix


def _depot_mas_cercano(nodo, depots, tiempos_por_depot):
    """Returns the name of the depot with minimum OSRM time to nodo (Haversine fallback)."""
    ine     = nodo["id"]
    mejor   = depots[0]["nombre"]
    mejor_t = np.inf
    for d in depots:
        t_dict = tiempos_por_depot.get(d["nombre"])
        t = t_dict.get(ine, 9999.0) if t_dict else haversine(d["lat"], d["lon"], nodo["lat"], nodo["lon"]) / VELOCIDAD_MEDIA_KMH * 60
        if t < mejor_t:
            mejor_t = t
            mejor   = d["nombre"]
    return mejor


def _estimar_vehiculos_por_depot(depots, nodos, tiempos_por_depot):
    """
    Greedy depot assignment used ONLY to estimate vehicle counts.
    Returns {depot_nombre: n_vehiculos} with a +2 buffer per depot.
    """
    asig = {d["nombre"]: 0.0 for d in depots}
    for nodo in nodos:
        asig[_depot_mas_cercano(nodo, depots, tiempos_por_depot)] += nodo["demanda"]
    return {
        nombre: max(1, math.ceil(dem / CAPACIDAD_EFECTIVA)) + 2
        for nombre, dem in asig.items()
    }


def vrp_ortools_global(depots, nodos, tiempos_por_depot, distancias_por_depot, id_camion_inicio):
    """
    Solves the true MDVRP in a single OR-Tools model.

    All depots and delivery nodes appear in one (N+D)×(N+D) matrix.
    OR-Tools assigns customers to depots and builds routes simultaneously,
    eliminating the greedy pre-assignment of vrp_ortools_depot loops.

    Falls back to per-depot vrp_ortools_depot if OR-Tools finds no solution.
    """
    if not nodos:
        return []

    # Pre-split high-demand nodes (same fix as vrp_ortools_depot)
    nodos = _split_nodos(nodos, CAPACIDAD_EFECTIVA)

    D = len(depots)
    N = len(nodos)

    time_matrix, km_matrix = construir_matriz_global(
        depots, nodos, tiempos_por_depot, distancias_por_depot
    )

    vehiculos_por_depot = _estimar_vehiculos_por_depot(depots, nodos, tiempos_por_depot)

    starts, ends = [], []
    for d_idx, d in enumerate(depots):
        n_v = vehiculos_por_depot[d["nombre"]]
        starts.extend([d_idx] * n_v)
        ends.extend([d_idx] * n_v)
    n_vehiculos = len(starts)

    demandas_raw = [nd["demanda"] for nd in nodos]
    demandas_int = [0] * D + [max(1, round(d * DEMANDA_ESCALA)) for d in demandas_raw]
    cap_int = CAPACIDAD_EFECTIVA * DEMANDA_ESCALA

    time_int = np.round(time_matrix).astype(int)
    jornada_conduccion = int(JORNADA_MAX_MIN - TIEMPO_CARGA_MIN)
    large_instance = N > 100

    manager = pywrapcp.RoutingIndexManager(N + D, n_vehiculos, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # Dimensión Tiempo (minutos): restringe jornada — no usada como coste.
    time_dim = time_int.copy()
    for i in range(D, N + D):
        time_dim[i, :] += round(TIEMPO_ENTREGA_MIN * demandas_raw[i - D])
    np.fill_diagonal(time_dim, 0)
    time_cb = routing.RegisterTransitMatrix(time_dim.tolist())
    routing.AddDimension(time_cb, 0, jornada_conduccion, True, "Tiempo")

    # Función objetivo: min Σ_v [50€·x_v + Σ_(i,j)(km·0.35 + t·14/60 + 3·dem_j·14/60)]
    # Escalado a enteros: 1 unidad = 1/ESCALA_COSTE €
    cost_matrix = np.round(
        km_matrix * COSTE_KM_INT + time_matrix * COSTE_MIN_INT
    ).astype(int)
    for i in range(D, N + D):
        cost_matrix[i, :] += round(TIEMPO_ENTREGA_MIN * demandas_raw[i - D] * COSTE_MIN_INT)
    np.fill_diagonal(cost_matrix, 0)
    cost_cb = routing.RegisterTransitMatrix(cost_matrix.tolist())
    routing.SetArcCostEvaluatorOfAllVehicles(cost_cb)
    routing.SetFixedCostOfAllVehicles(COSTE_FIJO_INT)

    demand_cb = routing.RegisterUnaryTransitVector(demandas_int)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0, [cap_int] * n_vehiculos, True, "Capacidad"
    )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    if not large_instance:
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = ORTOOLS_TIME_LIMIT_S
    else:
        # Cap large global instances to avoid indefinite hangs; fallback handles None.
        params.time_limit.seconds = ORTOOLS_TIME_LIMIT_S

    solution = routing.SolveWithParameters(params)

    if solution is None:
        print("    AVISO OR-Tools global: sin solucion — usando fallback por depot")
        todas, cid = [], id_camion_inicio
        for depot in depots:
            nombre    = depot["nombre"]
            nodos_dep = [n for n in nodos if _depot_mas_cercano(n, depots, tiempos_por_depot) == nombre]
            rutas_dep = vrp_ortools_depot(
                depot, nodos_dep, cid,
                tiempos_por_depot.get(nombre),
                (distancias_por_depot or {}).get(nombre),
            )
            todas.extend(rutas_dep)
            cid += len(rutas_dep)
        return todas

    rutas     = []
    camion_id = id_camion_inicio

    for v in range(n_vehiculos):
        idx = routing.Start(v)
        if routing.IsEnd(solution.Value(routing.NextVar(idx))):
            continue

        depot     = depots[starts[v]]
        depot_lat = depot["lat"]
        depot_lon = depot["lon"]
        depot_idx = starts[v]   # global matrix index of this vehicle's depot

        paradas        = []
        km_ruta        = 0.0
        t_acum         = float(TIEMPO_CARGA_MIN)
        paq_total_ruta = 0.0
        prev_node      = depot_idx

        idx = solution.Value(routing.NextVar(idx))
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            nodo = nodos[node - D]

            km_tramo = float(km_matrix[prev_node, node])
            t_tramo  = float(time_matrix[prev_node, node])
            t_acum  += t_tramo + TIEMPO_ENTREGA_MIN * nodo["demanda"]
            km_ruta += km_tramo
            paq_total_ruta += nodo["demanda"]

            paradas.append({
                "nodo":                nodo["id"],
                "paquetes":            nodo["demanda"],
                "km_tramo":            round(km_tramo, 3),
                "tiempo_tramo_min":    round(t_tramo, 2),
                "tiempo_acumulado_min": round(t_acum, 2),
                "lat":                 nodo["lat"],
                "lon":                 nodo["lon"],
            })
            prev_node = node
            idx = solution.Value(routing.NextVar(idx))

        if not paradas:
            continue

        km_ret  = float(km_matrix[prev_node, depot_idx])
        t_ret   = float(time_matrix[prev_node, depot_idx])
        km_ruta += km_ret
        t_total  = t_acum + t_ret

        paradas.append({
            "nodo":                "FIN_RUTA",
            "paquetes":            0,
            "km_tramo":            round(km_ret, 3),
            "tiempo_tramo_min":    round(t_ret, 2),
            "tiempo_acumulado_min": round(t_total, 2),
            "lat":                 depot_lat,
            "lon":                 depot_lon,
        })

        coste_km   = km_ruta * COSTE_KM
        coste_hora = (t_total / 60) * COSTE_HORA_CONDUCTOR
        rutas.append({
            "id_camion":       camion_id,
            "depot_nombre":    depot["nombre"],
            "n_paradas":       len(paradas),
            "paquetes":        round(paq_total_ruta, 4),
            "km_ruta":         round(km_ruta, 2),
            "tiempo_min":      round(t_total, 1),
            "coste_km_eur":    round(coste_km, 2),
            "coste_hora_eur":  round(coste_hora, 2),
            "coste_total_eur": round(coste_km + coste_hora, 2),
            "paradas":         paradas,
        })
        camion_id += 1

    return rutas


def vrp_multi_depot(depots, nodos_base, tiempos_por_depot, distancias_por_depot=None):
    """
    Full pipeline: single OR-Tools solve per depot (D=1) or global MDVRP model (D≥2).
    """
    if distancias_por_depot is None:
        distancias_por_depot = {}

    todas_rutas = []

    if len(depots) == 1:
        depot            = depots[0]
        nombre           = depot["nombre"]
        tiempos_depot    = tiempos_por_depot.get(nombre)
        distancias_depot = distancias_por_depot.get(nombre)
        demanda_depot    = sum(n["demanda"] for n in nodos_base)

        print(f"  {nombre}: {len(nodos_base)} secciones | {demanda_depot:.0f} paq | OR-Tools...",
              end=" ", flush=True)

        rutas_depot = vrp_ortools_depot(depot, nodos_base, 1, tiempos_depot, distancias_depot)
        todas_rutas.extend(rutas_depot)
        print(f"{len(rutas_depot)} furgonetas")

    else:
        # Depot-first: assign each node to nearest depot by OSRM time, then
        # solve each depot independently with radial-zone clustering.
        demanda_total = sum(n["demanda"] for n in nodos_base)
        nombres       = " + ".join(d["nombre"] for d in depots)
        print(f"  {nombres}: {len(nodos_base)} secciones | {demanda_total:.0f} paq | depot-first...")

        cid = 1
        for depot in depots:
            nombre       = depot["nombre"]
            tiempos_dep  = tiempos_por_depot.get(nombre)
            dist_dep     = distancias_por_depot.get(nombre)
            nodos_dep    = [n for n in nodos_base
                            if _depot_mas_cercano(n, depots, tiempos_por_depot) == nombre]
            demanda_dep  = sum(n["demanda"] for n in nodos_dep)
            print(f"  {nombre}: {len(nodos_dep)} secciones | {demanda_dep:.0f} paq | OR-Tools...",
                  end=" ", flush=True)
            rutas_dep = vrp_ortools_depot(depot, nodos_dep, cid, tiempos_dep, dist_dep)
            todas_rutas.extend(rutas_dep)
            cid += len(rutas_dep)
            print(f"{len(rutas_dep)} furgonetas")

    # ── Diagnóstico overtime ────────────────────────────────────────────────
    n_rutas_total    = len(todas_rutas)
    rutas_overtime   = [r for r in todas_rutas if r["tiempo_min"] > JORNADA_MAX_MIN]
    pct_overtime     = len(rutas_overtime) / n_rutas_total * 100 if n_rutas_total else 0
    overtime_stops   = set()
    for r in rutas_overtime:
        overtime_stops.update(p["nodo"] for p in r["paradas"] if p["nodo"] != "FIN_RUTA")
    print(f"  [DIAG] Rutas 1er pase: {n_rutas_total} | overtime: {len(rutas_overtime)} "
          f"({pct_overtime:.1f}%) | paradas afectadas: {len(overtime_stops)}")
    if overtime_stops:
        todas_rutas = [r for r in todas_rutas if r["tiempo_min"] <= JORNADA_MAX_MIN]
        print(f"  {len(overtime_stops)} paradas devueltas al pool")

    # ── Segundo pase VRP ────────────────────────────────────────────────────
    # Sections that OR-Tools dropped in the first pass are re-clustered and
    # solved again with a longer time limit + GLS. This converts the bulk of
    # single-stop rescue routes into proper multi-stop routes, significantly
    # reducing the fleet size.
    servidas = {p["nodo"] for r in todas_rutas for p in r["paradas"]}
    sin_ruta = [n for n in nodos_base if n["id"] not in servidas]

    if sin_ruta:
        print(f"  Segundo pase: {len(sin_ruta)} secciones sin servir → nuevo VRP "
              f"({ZONA_TIME_LIMIT_S_2PASE}s/zona, GLS)...")
        siguiente_id = max((r["id_camion"] for r in todas_rutas), default=0) + 1

        if len(depots) == 1:
            depot_obj        = depots[0]
            tiempos_dep      = tiempos_por_depot.get(depot_obj["nombre"])
            distancias_dep   = distancias_por_depot.get(depot_obj["nombre"])
            rutas_2pase = vrp_ortools_depot(
                depot_obj, sin_ruta, siguiente_id,
                tiempos_dep, distancias_dep,
                time_limit_s=ZONA_TIME_LIMIT_S_2PASE,
            )
            todas_rutas.extend(rutas_2pase)
            print(f"    {depot_obj['nombre']}: {len(rutas_2pase)} rutas nuevas")
        else:
            # Multi-depot: group unserved nodes by nearest depot, solve per depot.
            grupos = {d["nombre"]: [] for d in depots}
            for n in sin_ruta:
                grupos[_depot_mas_cercano(n, depots, tiempos_por_depot)].append(n)
            for depot_obj in depots:
                nodos_dep = grupos[depot_obj["nombre"]]
                if not nodos_dep:
                    continue
                siguiente_id = max((r["id_camion"] for r in todas_rutas), default=0) + 1
                tiempos_dep    = tiempos_por_depot.get(depot_obj["nombre"])
                distancias_dep = distancias_por_depot.get(depot_obj["nombre"])
                rutas_dep = vrp_ortools_depot(
                    depot_obj, nodos_dep, siguiente_id,
                    tiempos_dep, distancias_dep,
                    time_limit_s=ZONA_TIME_LIMIT_S_2PASE,
                )
                todas_rutas.extend(rutas_dep)
                print(f"    {depot_obj['nombre']}: {len(rutas_dep)} rutas nuevas "
                      f"({len(nodos_dep)} secciones)")

    # ── Rescate residual ────────────────────────────────────────────────────
    # Sections still unserved after both VRP passes are grouped into small
    # geographic batches (≤ZONA_TAM_MAX nodes each) per depot and solved with
    # a fast OR-Tools call. Only nodes that OR-Tools drops from those batches
    # fall through to the final single-stop fallback.
    servidas2 = {p["nodo"] for r in todas_rutas for p in r["paradas"]}
    sin_ruta2 = [n for n in nodos_base if n["id"] not in servidas2]
    if sin_ruta2:
        print(f"  Rescate residual: {len(sin_ruta2)} secciones — agrupando por proximidad...")
        siguiente_id = max((r["id_camion"] for r in todas_rutas), default=0) + 1
        n_rescate_rutas = 0

        # Group by nearest depot, then K-Means cluster within each depot group.
        grupos_dep = {d["nombre"]: [] for d in depots}
        for n in sin_ruta2:
            grupos_dep[
                _depot_mas_cercano(n, depots, tiempos_por_depot)
                if len(depots) > 1 else depots[0]["nombre"]
            ].append(n)

        for depot_obj in depots:
            nodos_dep = grupos_dep[depot_obj["nombre"]]
            if not nodos_dep:
                continue
            tiempos_dep    = tiempos_por_depot.get(depot_obj["nombre"])
            distancias_dep = distancias_por_depot.get(depot_obj["nombre"])

            # Split into geographic batches of ≤ ZONA_TAM_MAX and run OR-Tools.
            nodos_split = _split_nodos(nodos_dep, CAPACIDAD_EFECTIVA)
            k_bat = max(1, math.ceil(len(nodos_split) / ZONA_TAM_MAX))
            if k_bat == 1 or len(nodos_split) < 2:
                batches = [nodos_split]
            else:
                lats = np.array([nd["lat"] for nd in nodos_split])
                lons = np.array([nd["lon"] for nd in nodos_split])
                dem  = np.array([nd["demanda"] for nd in nodos_split])
                labs = _kmeans_np(np.column_stack([lats, lons]), k_bat,
                                  sample_weight=dem, n_init=5, random_state=0)
                bat_dict = {}
                for i, nd in enumerate(nodos_split):
                    bat_dict.setdefault(int(labs[i]), []).append(nd)
                batches = list(bat_dict.values())

            for batch in batches:
                if not batch:
                    continue
                t_z, km_z = construir_matrices_depot(depot_obj, batch, tiempos_dep, distancias_dep)
                rutas_bat = _vrp_ortools_zona(
                    depot_obj, batch, siguiente_id, t_z, km_z,
                    time_limit_s=ZONA_TIME_LIMIT_S_2PASE,
                )
                todas_rutas.extend(rutas_bat)
                siguiente_id += len(rutas_bat)
                n_rescate_rutas += len(rutas_bat)

            # Single-stop fallback only for nodes OR-Tools still couldn't serve.
            servidas3 = {p["nodo"] for r in todas_rutas for p in r["paradas"]}
            sin_ruta3 = [n for n in nodos_dep if n["id"] not in servidas3]
            for nd in _split_nodos(sin_ruta3, CAPACIDAD_EFECTIVA):
                t_mat, km_mat = construir_matrices_depot(depot_obj, [nd], tiempos_dep, distancias_dep)
                t_to  = float(t_mat[0, 1])
                km_to = float(km_mat[0, 1])
                tiempo_entrega_disponible = JORNADA_MAX_MIN - TIEMPO_CARGA_MIN - 2 * t_to
                max_paq_tiempo = max(1, int(tiempo_entrega_disponible / TIEMPO_ENTREGA_MIN)) if tiempo_entrega_disponible > 0 else 1
                for sub_nd in _split_nodos([nd], min(CAPACIDAD_EFECTIVA, max_paq_tiempo)):
                    paquetes = sub_nd["demanda"]
                    t_total  = TIEMPO_CARGA_MIN + t_to + TIEMPO_ENTREGA_MIN * paquetes + t_to
                    km_ruta  = km_to * 2
                    coste_km   = km_ruta * COSTE_KM
                    coste_hora = (t_total / 60) * COSTE_HORA_CONDUCTOR
                    todas_rutas.append({
                        "id_camion":       siguiente_id,
                        "depot_nombre":    depot_obj["nombre"],
                        "n_paradas":       1,
                        "paquetes":        round(paquetes, 4),
                        "km_ruta":         round(km_ruta, 2),
                        "tiempo_min":      round(t_total, 1),
                        "coste_km_eur":    round(coste_km, 2),
                        "coste_hora_eur":  round(coste_hora, 2),
                        "coste_total_eur": round(coste_km + coste_hora, 2),
                        "paradas": [
                            {
                                "nodo":                 sub_nd["id"],
                                "paquetes":             paquetes,
                                "km_tramo":             round(km_to, 3),
                                "tiempo_tramo_min":     round(t_to, 2),
                                "tiempo_acumulado_min": round(TIEMPO_CARGA_MIN + t_to + TIEMPO_ENTREGA_MIN * paquetes, 2),
                                "lat":                  sub_nd["lat"],
                                "lon":                  sub_nd["lon"],
                            },
                            {
                                "nodo":                 "FIN_RUTA",
                                "paquetes":             0,
                                "km_tramo":             round(km_to, 3),
                                "tiempo_tramo_min":     round(t_to, 2),
                                "tiempo_acumulado_min": round(t_total, 2),
                                "lat":                  depot_obj["lat"],
                                "lon":                  depot_obj["lon"],
                            },
                        ],
                    })
                    siguiente_id += 1
                    n_rescate_rutas += 1

        print(f"  Rescate residual: {len(sin_ruta2)} secciones → {n_rescate_rutas} rutas")

    return todas_rutas


# ============================================================
#  CALCULO DE KPIs
# ============================================================

def _min_tiempos_por_nodo(nodos_base, tiempos_por_depot):
    """For each node: minimum OSRM time from any active depot."""
    depot_dicts = [t for t in tiempos_por_depot.values() if t]
    result = {}
    for nodo in nodos_base:
        ine = nodo["id"]
        result[ine] = min((d.get(ine, 9999.0) for d in depot_dicts), default=9999.0)
    return result


def calcular_kpis(rutas, nodos_base, tiempos_por_depot):
    if not rutas:
        return {}

    dem_total   = sum(n["demanda"] for n in nodos_base)
    n_furg      = len(rutas)
    km_total    = sum(r["km_ruta"] for r in rutas)
    paq_total   = sum(r["paquetes"] for r in rutas)
    coste_km    = sum(r["coste_km_eur"] for r in rutas)
    coste_hora  = sum(r["coste_hora_eur"] for r in rutas)
    coste_fijo  = n_furg * COSTE_FIJO_FURGONETA
    coste_total = sum(r["coste_total_eur"] for r in rutas) + coste_fijo
    t_max       = max(r["tiempo_min"] for r in rutas)
    secc_serv   = len({p["nodo"] for r in rutas for p in r["paradas"] if p["nodo"] != "FIN_RUTA"})

    min_t = _min_tiempos_por_nodo(nodos_base, tiempos_por_depot)

    dem_30 = sum(n["demanda"] for n in nodos_base if min_t.get(n["id"], 9999) < 30)
    dem_45 = sum(n["demanda"] for n in nodos_base if min_t.get(n["id"], 9999) < 45)
    dem_60 = sum(n["demanda"] for n in nodos_base if min_t.get(n["id"], 9999) < 60)
    t_pond = (
        sum(n["demanda"] * min_t.get(n["id"], 9999) for n in nodos_base) / dem_total
        if dem_total > 0 else 0
    )

    return {
        "n_furgonetas":           n_furg,
        "km_total":               round(km_total, 1),
        "paquetes_total":         round(paq_total, 1),
        "paquetes_sin_servir":    round(max(0, dem_total - paq_total), 1),
        "coste_km_dia":           round(coste_km, 2),
        "coste_conductor_dia":    round(coste_hora, 2),
        "coste_fijo_dia":         round(coste_fijo, 2),
        "coste_total_dia":        round(coste_total, 2),
        "km_por_paquete":         round(km_total / paq_total, 4) if paq_total > 0 else 0,
        "coste_por_paquete":      round(coste_total / paq_total, 4) if paq_total > 0 else 0,
        "utilizacion_flota_pct":  round(
            paq_total / (n_furg * CAPACIDAD_FURGONETA) * 100, 1
        ) if n_furg > 0 else 0,
        "cobertura_30min_pct":    round(dem_30 / dem_total * 100, 1) if dem_total > 0 else 0,
        "cobertura_45min_pct":    round(dem_45 / dem_total * 100, 1) if dem_total > 0 else 0,
        "cobertura_60min_pct":    round(dem_60 / dem_total * 100, 1) if dem_total > 0 else 0,
        "tiempo_medio_pond_min":  round(t_pond, 2),
        "tiempo_ruta_max_min":    round(t_max, 1),
        "secciones_servidas":     secc_serv,
        "secciones_servidas_pct": round(secc_serv / len(nodos_base) * 100, 1) if nodos_base else 0,
        "co2_kg_dia":             round(km_total * CO2_KG_POR_KM, 1),
    }


# ============================================================
#  HELPERS DE SALIDA
# ============================================================

def guardar_vrp_resultados_modo(modo, alternativa, depots, kpis):
    os.makedirs(RUTA_CHECKPOINTS, exist_ok=True)
    fila = {
        "modo":          modo,
        "alternativa":   alternativa,
        "n_depots":      len(depots),
        "depot_nombres": "|".join(d["nombre"] for d in depots),
        **kpis,
    }
    ruta = os.path.join(RUTA_VRP_RES, f"vrp_resultados_{modo}_b.csv")
    pd.DataFrame([fila]).to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


def guardar_detalle_rutas_modo(tag, rutas):
    if not GUARDAR_DETALLE_RUTAS or not rutas:
        return
    os.makedirs(RUTA_CHECKPOINTS, exist_ok=True)
    filas = []
    for ruta in rutas:
        for orden, parada in enumerate(ruta["paradas"], 1):
            filas.append({
                "tag":          tag,
                "id_camion":    ruta["id_camion"],
                "depot_nombre": ruta["depot_nombre"],
                "orden_parada": orden,
                "nodo_ine":     parada["nodo"],
                "paquetes":     parada["paquetes"],
                "km_tramo":     parada["km_tramo"],
                "tiempo_tramo_min": parada.get("tiempo_tramo_min", 0.0),
                "tiempo_acumulado_min": parada.get("tiempo_acumulado_min", 0.0),
                "lat":          parada["lat"],
                "lon":          parada["lon"],
            })
    ruta_csv = os.path.join(RUTA_VRP_RUTAS, f"vrp_rutas_detalle_{tag}_b.csv")
    pd.DataFrame(filas).to_csv(ruta_csv, index=False, encoding="utf-8-sig")


def guardar_p_median_k(k, indices, df_cand_inc, tiempos_matrix, secciones_ine):
    t_sel      = tiempos_matrix[list(indices), :]
    asig_local = np.argmin(t_sel, axis=0)
    zonas      = {idx: [] for idx in indices}
    for col, local_idx in enumerate(asig_local):
        zonas[indices[local_idx]].append(secciones_ine[col])

    filas = []
    for idx_cand, ines_zona in zonas.items():
        cand = df_cand_inc.iloc[idx_cand]
        filas.append({
            "Nombre":         str(cand["Nombre"]),
            "Latitud":        float(cand["Latitud"]),
            "Longitud":       float(cand["Longitud"]),
            "Zona_secciones": "|".join(ines_zona),
        })
    ruta_csv = os.path.join(RUTA_P_MEDIAN, f"p_median_K{k}_b.csv")
    pd.DataFrame(filas).to_csv(ruta_csv, index=False, encoding="utf-8-sig")


# ============================================================
#  MOTOR P-MEDIAN  (motor greedy de referencia: ver src/06_rutas_N_centros.py)
# ============================================================

def construir_matriz_tiempos(df_candidatos, secciones_ine):
    """Builds (n_cand x n_secc) time matrix from OSRM checkpoints."""
    filas = []
    incluidos = []
    for _, cand in df_candidatos.iterrows():
        nombre  = str(cand["Nombre"])
        tiempos = cargar_tiempos_osrm(nombre)
        if tiempos is None:
            print(f"  AVISO: sin checkpoint para '{nombre}' -- omitido del P-Median")
            continue
        fila = np.array([tiempos.get(ine, 999.0) for ine in secciones_ine], dtype=float)
        filas.append(fila)
        incluidos.append(cand.to_dict())
    if not filas:
        return None, None
    return np.array(filas), pd.DataFrame(incluidos).reset_index(drop=True)


def p_median_exacto(tiempos_matrix, pesos_arr, K):
    n       = tiempos_matrix.shape[0]
    w_total = pesos_arr.sum()
    best_cost    = np.inf
    best_indices = None
    best_min_t   = None

    if K == 1:
        costs  = np.dot(tiempos_matrix, pesos_arr) / w_total
        idx    = int(np.argmin(costs))
        return (idx,), float(costs[idx]), tiempos_matrix[idx].copy()

    if K == 2:
        for i in range(n):
            rest = tiempos_matrix[i + 1:]
            if len(rest) == 0:
                continue
            pairwise_min = np.minimum(tiempos_matrix[i], rest)
            costs        = np.dot(pairwise_min, pesos_arr) / w_total
            j_local      = int(np.argmin(costs))
            if costs[j_local] < best_cost:
                best_cost    = float(costs[j_local])
                best_indices = (i, i + 1 + j_local)
                best_min_t   = pairwise_min[j_local].copy()
        return best_indices, best_cost, best_min_t

    if K == 3:
        for i in range(n):
            for j in range(i + 1, n):
                min_ij = np.minimum(tiempos_matrix[i], tiempos_matrix[j])
                rest   = tiempos_matrix[j + 1:]
                if len(rest) == 0:
                    continue
                pairwise_min = np.minimum(min_ij, rest)
                costs        = np.dot(pairwise_min, pesos_arr) / w_total
                k_local      = int(np.argmin(costs))
                if costs[k_local] < best_cost:
                    best_cost    = float(costs[k_local])
                    best_indices = (i, j, j + 1 + k_local)
                    best_min_t   = pairwise_min[k_local].copy()
        return best_indices, best_cost, best_min_t

    if K == 4:
        for i in range(n):
            for j in range(i + 1, n):
                min_ij = np.minimum(tiempos_matrix[i], tiempos_matrix[j])
                for k in range(j + 1, n):
                    min_ijk = np.minimum(min_ij, tiempos_matrix[k])
                    rest = tiempos_matrix[k + 1:]
                    if len(rest) == 0:
                        continue
                    pairwise_min = np.minimum(min_ijk, rest)
                    costs = np.dot(pairwise_min, pesos_arr) / w_total
                    l_local = int(np.argmin(costs))
                    if costs[l_local] < best_cost:
                        best_cost    = float(costs[l_local])
                        best_indices = (i, j, k, k + 1 + l_local)
                        best_min_t   = pairwise_min[l_local].copy()
        return best_indices, best_cost, best_min_t

    if K == 5:
        for i in range(n):
            for j in range(i + 1, n):
                min_ij = np.minimum(tiempos_matrix[i], tiempos_matrix[j])
                for k in range(j + 1, n):
                    min_ijk = np.minimum(min_ij, tiempos_matrix[k])
                    for l in range(k + 1, n):
                        min_ijkl = np.minimum(min_ijk, tiempos_matrix[l])
                        rest = tiempos_matrix[l + 1:]
                        if len(rest) == 0:
                            continue
                        pairwise_min = np.minimum(min_ijkl, rest)
                        costs = np.dot(pairwise_min, pesos_arr) / w_total
                        m_local = int(np.argmin(costs))
                        if costs[m_local] < best_cost:
                            best_cost    = float(costs[m_local])
                            best_indices = (i, j, k, l, l + 1 + m_local)
                            best_min_t   = pairwise_min[m_local].copy()
        return best_indices, best_cost, best_min_t

    if K == 6:
        for i in range(n):
            for j in range(i + 1, n):
                min_ij = np.minimum(tiempos_matrix[i], tiempos_matrix[j])
                for k in range(j + 1, n):
                    min_ijk = np.minimum(min_ij, tiempos_matrix[k])
                    for l in range(k + 1, n):
                        min_ijkl = np.minimum(min_ijk, tiempos_matrix[l])
                        for m in range(l + 1, n):
                            min_ijklm = np.minimum(min_ijkl, tiempos_matrix[m])
                            rest = tiempos_matrix[m + 1:]
                            if len(rest) == 0:
                                continue
                            pairwise_min = np.minimum(min_ijklm, rest)
                            costs = np.dot(pairwise_min, pesos_arr) / w_total
                            p_local = int(np.argmin(costs))
                            if costs[p_local] < best_cost:
                                best_cost    = float(costs[p_local])
                                best_indices = (i, j, k, l, m, m + 1 + p_local)
                                best_min_t   = pairwise_min[p_local].copy()
        return best_indices, best_cost, best_min_t

    return _p_median_greedy_k(tiempos_matrix, pesos_arr, K)


def _p_median_greedy_k(tiempos_matrix, pesos_arr, K):
    n       = tiempos_matrix.shape[0]
    w_total = pesos_arr.sum()
    seleccionados = []
    min_tiempos   = np.full(tiempos_matrix.shape[1], np.inf)

    for _ in range(K):
        mejor_idx   = None
        mejor_cost  = np.inf
        mejor_min_t = None
        for i in range(n):
            if i in seleccionados:
                continue
            nuevo_min = np.minimum(min_tiempos, tiempos_matrix[i])
            cost      = float(np.dot(pesos_arr, nuevo_min) / w_total)
            if cost < mejor_cost:
                mejor_cost  = cost
                mejor_idx   = i
                mejor_min_t = nuevo_min
        if mejor_idx is None:
            break
        seleccionados.append(mejor_idx)
        min_tiempos = mejor_min_t

    return tuple(seleccionados), float(np.dot(pesos_arr, min_tiempos) / w_total), min_tiempos.copy()


# ============================================================
#  PROGRAMA PRINCIPAL
# ============================================================

if __name__ == "__main__":
    print("=" * 65)
    print(f"  03_VRP_RUTAS_B -- MODO: {MODO}  [OR-Tools]")
    print("  VRP completo: OR-Tools CVRPTW + OSRM + Haversine internodo")
    print("=" * 65)

    for ruta, nombre_fichero in [
        (RUTA_DATOS,   "Datos.xlsx"),
        (RUTA_DEMANDA, "Demanda_Amazon_365_Mejorada.xlsx"),
    ]:
        if not os.path.exists(ruta):
            print(f"\nERROR: No encontrado: {ruta}")
            sys.exit(1)

    df_secciones = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
    df_secciones["Seccion INE"] = df_secciones["Seccion INE"].astype(int)
    df_secciones = df_secciones.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)

    demanda    = cargar_demanda()
    nodos_base = preparar_nodos(df_secciones, demanda)
    dem_total  = sum(n["demanda"] for n in nodos_base)

    print(f"  Secciones con demanda: {len(nodos_base)}")
    print(f"  Demanda total:         {dem_total:.0f} paquetes")

    # ===== MODO A1: SVQ1 solo =====
    if MODO == "A1":
        depots = [DEPOT_SVQ1]
        tiempos_por_depot    = {}
        distancias_por_depot = {}
        t = cargar_tiempos_osrm(DEPOT_SVQ1["nombre"])
        d = cargar_distancias_osrm(DEPOT_SVQ1["nombre"])
        if t:
            tiempos_por_depot[DEPOT_SVQ1["nombre"]]    = t
            distancias_por_depot[DEPOT_SVQ1["nombre"]] = d
            print(f"  Tiempos OSRM SVQ1: {len(t)} secciones cargadas")
        else:
            print("  AVISO: sin checkpoint OSRM para SVQ1 -- usando Haversine")

        print("\n  Ejecutando VRP (OR-Tools)...")
        print("-" * 40)
        rutas = vrp_multi_depot(depots, nodos_base, tiempos_por_depot, distancias_por_depot)
        print("-" * 40)
        kpis  = calcular_kpis(rutas, nodos_base, tiempos_por_depot)

        print("\n  KPIs:")
        for k, v in kpis.items():
            print(f"    {k:<35} {v}")

        ruta_csv = guardar_vrp_resultados_modo("A1", "A1", depots, kpis)
        guardar_detalle_rutas_modo("A1", rutas)
        print(f"\n  Resultados: {ruta_csv}")

    # ===== MODO A2: SVQ1 + DQA4 =====
    elif MODO == "A2":
        depots = [DEPOT_SVQ1, DEPOT_DQA4]
        tiempos_por_depot    = {}
        distancias_por_depot = {}
        for depot in depots:
            t = cargar_tiempos_osrm(depot["nombre"])
            d = cargar_distancias_osrm(depot["nombre"])
            if t:
                tiempos_por_depot[depot["nombre"]]    = t
                distancias_por_depot[depot["nombre"]] = d
                print(f"  Tiempos OSRM {depot['nombre']}: {len(t)} secciones")
            else:
                print(f"  AVISO: sin checkpoint para {depot['nombre']} -- Haversine")

        print("\n  Ejecutando VRP multi-depot (OR-Tools)...")
        print("-" * 40)
        rutas = vrp_multi_depot(depots, nodos_base, tiempos_por_depot, distancias_por_depot)
        print("-" * 40)
        kpis  = calcular_kpis(rutas, nodos_base, tiempos_por_depot)

        print("\n  KPIs:")
        for k, v in kpis.items():
            print(f"    {k:<35} {v}")

        ruta_csv = guardar_vrp_resultados_modo("A2", "A2", depots, kpis)
        guardar_detalle_rutas_modo("A2", rutas)
        print(f"\n  Resultados: {ruta_csv}")

    # ===== MODO CANDIDATOS =====
    elif MODO == "candidatos":
        if not os.path.exists(RUTA_CANDIDATOS):
            print(f"\nERROR: No encontrado: {RUTA_CANDIDATOS}")
            sys.exit(1)

        df_candidatos = pd.read_csv(RUTA_CANDIDATOS, encoding="utf-8-sig")
        df_candidatos = df_candidatos.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)
        n_cand = len(df_candidatos)

        secciones_ine = [str(int(x)) for x in df_secciones["Seccion INE"].tolist()]
        pesos_arr     = df_secciones["Peso"].values.astype(float)

        print(f"\n  Construyendo matriz de tiempos OSRM ({n_cand} candidatos)...")
        tiempos_matrix, df_cand_inc = construir_matriz_tiempos(df_candidatos, secciones_ine)

        if tiempos_matrix is None:
            print("\nERROR: Ningun candidato tiene checkpoint OSRM.")
            print("Ejecuta primero: python src/05_extraccion_tiempos_osrm.py")
            sys.exit(1)

        n_inc  = len(df_cand_inc)
        print(f"  Candidatos con tiempos disponibles: {n_inc}/{n_cand}")
        k_eval = min(K_MAX, n_inc)

        print(f"\n  P-Median {METODO_PMEDIAN.upper()} K=1..{k_eval}...")
        print("-" * 40)
        resultados_pmedian = []
        for k in range(1, k_eval + 1):
            if METODO_PMEDIAN == "exacto":
                indices, coste, _ = p_median_exacto(tiempos_matrix, pesos_arr, k)
            else:
                indices, coste, _ = _p_median_greedy_k(tiempos_matrix, pesos_arr, k)
            nombres_k = [str(df_cand_inc.iloc[i]["Nombre"]) for i in indices]
            print(f"  K={k}: coste={coste:.2f} min/paq | ganadores: {' + '.join(nombres_k)}")
            resultados_pmedian.append({
                "k":       k,
                "indices": indices,
                "coste":   coste,
                "nombres": nombres_k,
            })
        print("-" * 40)

        print(f"\n  VRP OR-Tools para cada red K-optima...")
        filas_vrp_k = []
        for res in resultados_pmedian:
            k       = res["k"]
            indices = res["indices"]
            depots_k = [
                {
                    "nombre": str(df_cand_inc.iloc[i]["Nombre"]),
                    "lat":    float(df_cand_inc.iloc[i]["Latitud"]),
                    "lon":    float(df_cand_inc.iloc[i]["Longitud"]),
                }
                for i in indices
            ]
            tiempos_k = {
                df_cand_inc.iloc[i]["Nombre"]: cargar_tiempos_osrm(df_cand_inc.iloc[i]["Nombre"])
                for i in indices
            }
            distancias_k = {
                df_cand_inc.iloc[i]["Nombre"]: cargar_distancias_osrm(df_cand_inc.iloc[i]["Nombre"])
                for i in indices
            }

            print(f"\n  C-K{k}: {' + '.join(res['nombres'])}")
            print("-" * 40)
            rutas_k = vrp_multi_depot(depots_k, nodos_base, tiempos_k, distancias_k)
            print("-" * 40)
            kpis_k  = calcular_kpis(rutas_k, nodos_base, tiempos_k)

            filas_vrp_k.append({
                "modo":            "candidatos",
                "alternativa":     f"C-K{k}",
                "n_depots":        k,
                "depot_nombres":   "|".join(res["nombres"]),
                **kpis_k,
            })

            guardar_detalle_rutas_modo(f"candidatos_K{k}", rutas_k)
            guardar_p_median_k(k, indices, df_cand_inc, tiempos_matrix, secciones_ine)

        ruta_res = os.path.join(RUTA_VRP_RES, "vrp_resultados_candidatos_b.csv")
        pd.DataFrame(filas_vrp_k).to_csv(ruta_res, index=False, encoding="utf-8-sig")

        print("\n" + "=" * 65)
        print("  RESUMEN C-K1 / C-K2 / C-K3")
        print("=" * 65)
        for fila in filas_vrp_k:
            print(
                f"  {fila['alternativa']}: {fila['depot_nombres']}\n"
                f"    {fila['n_furgonetas']} furgs | "
                f"{fila['km_total']:,.0f} km | "
                f"{fila['coste_total_dia']:,.0f} EUR/dia | "
                f"cob.<60min: {fila['cobertura_60min_pct']:.1f}%"
            )
        print(f"\n  Resultados VRP: {ruta_res}")

    else:
        print(f"\nERROR: MODO '{MODO}' no reconocido. Usa 'A1', 'A2' o 'candidatos'.")
        sys.exit(1)

    print("\nSiguiente paso: python scripts/04_Comparar_KPIs.py")
