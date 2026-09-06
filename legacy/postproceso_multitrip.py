#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
postproceso_multitrip.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Post-processing over OR-Tools VRP route detail CSVs.

Two operations applied in sequence:
  1. Minimum inter-node travel time (MIN_TRAMO_MIN): replace any segment
     shorter than MIN_TRAMO_MIN minutes with that floor value and recompute
     cumulative times. Ensures realistic last-mile dwell time between stops.

  2. Multi-trip LPT scheduling: instead of one truck per route, group routes
     into full driver shifts using Longest Processing Time first bin packing.
     A driver whose route ends early returns to the depot, reloads in
     TIEMPO_RECARGA_MIN minutes, and starts a new route — up to JORNADA_MAX_MIN
     total. Trucks from different depots are never mixed.

Input : outputs/csv/vrp_rutas_detalle_{TAG}_b.csv
Output: outputs/csv/vrp_rutas_detalle_{TAG}_mt.csv   (stop-level, n_viaje added)
        outputs/csv/vrp_resumen_{TAG}_mt.csv          (shift-level summary)
"""
# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")


import os, pathlib
import pandas as pd

# ── Parameters ──────────────────────────────────────────────────────────────
TAG                 = "A2"   # "A1" | "A2" | "candidatos_K1" | "candidatos_K2" | "candidatos_K3"
MIN_TRAMO_MIN       = 5      # minimum inter-node travel time (min)
JORNADA_MAX_MIN     = 480    # maximum driver shift duration (min)
TIEMPO_CARGA_MIN    = 45     # initial depot loading time (min)
TIEMPO_RECARGA_MIN  = 20     # reload time between consecutive trips (min)
TIEMPO_ENTREGA_MIN  = 3      # delivery time per stop (min)
COSTE_KM            = 0.35   # €/km
COSTE_HORA_CONDUCTOR = 14.0  # €/hour
CO2_KG_POR_KM       = 0.21  # kg CO₂/km

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR        = pathlib.Path(__file__).resolve().parents[1]
CSV_DIR         = BASE_DIR / "outputs" / "csv" / "vrp_rutas"
CSV_IN          = CSV_DIR / f"vrp_rutas_detalle_{TAG}_b.csv"
CSV_OUT_PARADAS = CSV_DIR / f"vrp_rutas_detalle_{TAG}_mt.csv"
CSV_OUT_RESUMEN = CSV_DIR / f"vrp_resumen_{TAG}_mt.csv"

# ── Route reconstruction helpers ─────────────────────────────────────────────

def _is_fin(nodo_val):
    return str(nodo_val) == "FIN_RUTA"


def recalcular_ruta(stops):
    """
    Apply MIN_TRAMO_MIN floor to every travel segment and recompute
    cumulative timestamps. Mirrors the original time model:
      t_acum starts at TIEMPO_CARGA_MIN;
      each delivery stop adds max(tramo, MIN_TRAMO_MIN) + TIEMPO_ENTREGA_MIN;
      FIN_RUTA adds max(tramo, MIN_TRAMO_MIN) travel only (no delivery).

    Returns (corrected_stops, total_tiempo_min, total_km)
    """
    t_acum  = float(TIEMPO_CARGA_MIN)
    km_ruta = 0.0
    out = []

    for stop in stops:
        t_orig   = float(stop["tiempo_tramo_min"])
        km_tramo = float(stop["km_tramo"])
        t_corr   = max(t_orig, MIN_TRAMO_MIN)
        fin      = _is_fin(stop["nodo_ine"])

        if fin:
            t_acum += t_corr  # return leg: travel only
        else:
            t_acum += t_corr + TIEMPO_ENTREGA_MIN * float(stop["paquetes"])

        km_ruta += km_tramo
        out.append({
            **stop,
            "tiempo_tramo_min":     round(t_corr, 2),
            "tiempo_acumulado_min": round(t_acum, 2),
        })

    return out, round(t_acum, 1), round(km_ruta, 2)


# ── Multi-trip scheduling ─────────────────────────────────────────────────────

def lpt_scheduling(routes):
    """
    Longest Processing Time (LPT) bin packing into driver shifts.

    Routes from different depots are never combined. Within the same depot,
    the algorithm assigns each route (sorted longest-first) to the
    least-loaded existing shift that can still accommodate it.

    Time model for trip k ≥ 2:
      delta = route.tiempo_min - TIEMPO_CARGA_MIN + TIEMPO_RECARGA_MIN
            = route.tiempo_min - 25
    This replaces the initial loading (45 min) with the quick reload (20 min).

    Returns a list of shift dicts: {depot, tiempo_shift, trips: [route, ...]}
    """
    DELTA = TIEMPO_RECARGA_MIN - TIEMPO_CARGA_MIN  # -25

    sorted_routes = sorted(routes, key=lambda r: r["tiempo_min"], reverse=True)
    shifts = []  # each: {"depot": str, "tiempo": float, "trips": [...]}

    for route in sorted_routes:
        depot   = route["depot_nombre"]
        t_route = route["tiempo_min"]

        best_idx, best_load = None, float("inf")
        for i, sh in enumerate(shifts):
            if sh["depot"] != depot:
                continue
            t_added = t_route + DELTA
            if sh["tiempo"] + t_added <= JORNADA_MAX_MIN and sh["tiempo"] < best_load:
                best_idx, best_load = i, sh["tiempo"]

        if best_idx is not None:
            shifts[best_idx]["tiempo"] += t_route + DELTA
            shifts[best_idx]["trips"].append(route)
        else:
            if t_route > JORNADA_MAX_MIN:
                print(f"    AVISO: ruta {route['id_camion_orig']} ({depot}) excede "
                      f"la jornada ({t_route:.0f} > {JORNADA_MAX_MIN} min) — asignada sola")
            shifts.append({"depot": depot, "tiempo": t_route, "trips": [route]})

    return shifts


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 66)
    print(f"  08_POSTPROCESO_MULTITRIP  tag={TAG}")
    print(f"  MIN_TRAMO={MIN_TRAMO_MIN} min | RECARGA={TIEMPO_RECARGA_MIN} min | "
          f"JORNADA={JORNADA_MAX_MIN} min")
    print("=" * 66)

    # ── [1] Load ──────────────────────────────────────────────────────────
    print(f"\n[1] Leyendo {CSV_IN.name}...")
    if not CSV_IN.exists():
        sys.exit(f"ERROR: no existe {CSV_IN}")
    df = pd.read_csv(CSV_IN, encoding="utf-8-sig")
    df.columns = df.columns.str.lstrip("﻿")  # strip BOM if present

    # Ensure depot_nombre column (absent in single-candidato files)
    if "depot_nombre" not in df.columns:
        df["depot_nombre"] = "Candidato"

    n_rutas_orig = df["id_camion"].nunique()
    print(f"    {len(df)} paradas | {n_rutas_orig} rutas originales")

    # ── [2] Reconstruct + apply MIN_TRAMO_MIN ────────────────────────────
    print(f"\n[2] Aplicando mínimo {MIN_TRAMO_MIN} min entre nodos...")

    routes = []
    t_orig_sum = t_corr_sum = 0.0

    for (depot, camion_id), grp in df.groupby(["depot_nombre", "id_camion"]):
        stops_raw = grp.sort_values("orden_parada").to_dict("records")
        corrected, tiempo_min, km_ruta = recalcular_ruta(stops_raw)

        t_orig = float(grp.sort_values("orden_parada")["tiempo_acumulado_min"].iloc[-1])
        t_orig_sum += t_orig
        t_corr_sum += tiempo_min

        delivery = [s for s in corrected if not _is_fin(s["nodo_ine"])]
        routes.append({
            "id_camion_orig": camion_id,
            "depot_nombre":   depot,
            "n_paradas":      len(delivery),
            "paquetes":       round(sum(s["paquetes"] for s in delivery), 4),
            "km_ruta":        km_ruta,
            "tiempo_min":     tiempo_min,
            "stops":          corrected,
        })

    n = len(routes)
    print(f"    Tiempo medio original:  {t_orig_sum / n:.1f} min/ruta")
    print(f"    Tiempo medio corregido: {t_corr_sum / n:.1f} min/ruta "
          f"(+{(t_corr_sum - t_orig_sum) / n:.1f} min)")

    # ── [3] LPT multi-trip scheduling ────────────────────────────────────
    print(f"\n[3] Agrupando multi-viaje (LPT scheduling)...")
    all_shifts = lpt_scheduling(routes)

    depots = sorted({sh["depot"] for sh in all_shifts})
    for depot in depots:
        dep_shifts = [sh for sh in all_shifts if sh["depot"] == depot]
        n_dep_routes = sum(len(sh["trips"]) for sh in dep_shifts)
        n_dep_shifts = len(dep_shifts)
        avg = n_dep_routes / n_dep_shifts if n_dep_shifts else 0
        print(f"    {depot}: {n_dep_routes} rutas → "
              f"{n_dep_shifts} conductores ({avg:.1f} viajes/conductor)")

    total_orig_trucks = n
    total_mt_trucks   = len(all_shifts)
    reduccion = (1 - total_mt_trucks / total_orig_trucks) * 100 if total_orig_trucks else 0
    print(f"\n    Total: {total_orig_trucks} rutas → {total_mt_trucks} conductores "
          f"({reduccion:.1f}% reducción de flota)")

    # ── [4] Build output DataFrames ───────────────────────────────────────
    print(f"\n[4] Generando CSVs...")

    paradas_rows = []
    resumen_rows = []

    for camion_mt_id, shift in enumerate(all_shifts, 1):
        depot        = shift["depot"]
        trips        = shift["trips"]
        tiempo_shift = shift["tiempo"]

        km_total      = sum(t["km_ruta"]  for t in trips)
        paq_total     = sum(t["paquetes"] for t in trips)
        n_par_total   = sum(t["n_paradas"] for t in trips)
        coste_km      = round(km_total * COSTE_KM, 2)
        coste_hora    = round((tiempo_shift / 60) * COSTE_HORA_CONDUCTOR, 2)
        coste_total   = round(coste_km + coste_hora, 2)
        co2_kg        = round(km_total * CO2_KG_POR_KM, 2)

        resumen_rows.append({
            "id_camion_mt":      camion_mt_id,
            "depot_nombre":      depot,
            "n_viajes":          len(trips),
            "n_paradas_total":   n_par_total,
            "paquetes_total":    round(paq_total, 2),
            "km_total":          round(km_total, 2),
            "tiempo_shift_min":  round(tiempo_shift, 1),
            "coste_km_eur":      coste_km,
            "coste_hora_eur":    coste_hora,
            "coste_total_eur":   coste_total,
            "co2_kg":            co2_kg,
        })

        orden_global = 1
        for n_viaje, trip in enumerate(trips, 1):
            for stop in trip["stops"]:
                paradas_rows.append({
                    "id_camion_mt":         camion_mt_id,
                    "depot_nombre":         depot,
                    "n_viaje":              n_viaje,
                    "id_camion_orig":       trip["id_camion_orig"],
                    "orden_parada":         orden_global,
                    "nodo_ine":             stop["nodo_ine"],
                    "paquetes":             stop["paquetes"],
                    "km_tramo":             stop["km_tramo"],
                    "tiempo_tramo_min":     stop["tiempo_tramo_min"],
                    "tiempo_acumulado_min": stop["tiempo_acumulado_min"],
                    "lat":                  stop["lat"],
                    "lon":                  stop["lon"],
                })
                orden_global += 1

    df_paradas = pd.DataFrame(paradas_rows)
    df_resumen = pd.DataFrame(resumen_rows)
    df_paradas.to_csv(CSV_OUT_PARADAS, index=False, encoding="utf-8-sig")
    df_resumen.to_csv(CSV_OUT_RESUMEN, index=False, encoding="utf-8-sig")

    # ── [5] KPI summary ───────────────────────────────────────────────────
    km_tot    = df_resumen["km_total"].sum()
    coste_tot = df_resumen["coste_total_eur"].sum()
    t_medio   = df_resumen["tiempo_shift_min"].mean()
    t_std     = df_resumen["tiempo_shift_min"].std()
    pct_full  = (df_resumen["tiempo_shift_min"] >= 0.9 * JORNADA_MAX_MIN).mean() * 100

    print(f"\n[5] KPIs resultado:")
    print(f"    Conductores multi-viaje: {total_mt_trucks}  "
          f"({reduccion:.1f}% menos que modelo base)")
    print(f"    km totales:              {km_tot:,.0f} km")
    print(f"    Coste total/dia:         {coste_tot:,.2f} EUR")
    print(f"    Tiempo medio turno:      {t_medio:.1f} min ({t_medio/60:.1f}h)")
    print(f"    Desv. std turno:         {t_std:.1f} min  (balance de carga)")
    print(f"    Conductores >=90% jorn.: {pct_full:.1f}%")
    print(f"\n    CSV paradas: {CSV_OUT_PARADAS.name}")
    print(f"    CSV resumen: {CSV_OUT_RESUMEN.name}")
    print("\n  Proceso completado.")


if __name__ == "__main__":
    import sys
    main()
