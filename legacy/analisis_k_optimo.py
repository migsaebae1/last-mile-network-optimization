"""
analisis_k_optimo.py
Analisis del numero optimo de centros de ultima milla (Alternativa C greenfield).

Para K=1..3 reutiliza los resultados de vrp_resultados_candidatos_b.csv (OR-Tools).
Para K>3 ejecuta P-Median (exacto para K<=3, greedy para K>3) + VRP multi-depot.
Genera la grafica de 3 curvas y exporta analisis_optimo_K.csv.

Ver la estimacion de OPEX en el README de esta carpeta (seccion "Supuestos").
"""
# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")


import os
import sys
import ctypes
import importlib.util

# Pre-load OR-Tools DLLs before importing any module that uses OR-Tools.
# Required on Windows: ortools/__init__.py's own loader fails if the .libs dir
# is not already in the DLL search path when exec_module runs vrp_ortools_cvrptw.py.
if os.name == "nt":
    try:
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
        pass

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# BASE_DIR: 2 niveles (legacy/ -> raiz del repositorio)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
#  PARAMETROS FINANCIEROS — ajustar si se dispone de datos reales
# ============================================================
OPEX_CENTRO_ANIO = 800_000    # euros/anio/centro (estimacion propia; ver legacy/README.md)
CAPEX_CENTRO     = 6_000_000  # euros/centro
VIDA_UTIL_ANOS   = 20         # horizonte amortizacion CAPEX
DIAS_ANIO        = 250        # dias laborables (idem que el resto del proyecto)
K_MAX            = 6          # maximo K a evaluar

# ============================================================
#  IMPORTAR MOTOR VRP (OR-Tools)
#  vrp_ortools_cvrptw.py tiene guardia if __name__ == "__main__"
#  => importlib es seguro; el bloque main no se ejecuta
# ============================================================
_vrp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vrp_ortools_cvrptw.py")
if not os.path.exists(_vrp_path):
    print(f"ERROR: No encontrado {_vrp_path}")
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("vrp_rutas", _vrp_path)
_vrp  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vrp)

vrp_multi_depot          = _vrp.vrp_multi_depot
calcular_kpis            = _vrp.calcular_kpis
cargar_tiempos_osrm      = _vrp.cargar_tiempos_osrm
cargar_distancias_osrm   = _vrp.cargar_distancias_osrm
construir_matriz_tiempos = _vrp.construir_matriz_tiempos
preparar_nodos           = _vrp.preparar_nodos
cargar_demanda           = _vrp.cargar_demanda
p_median_exacto          = _vrp.p_median_exacto

# ============================================================
#  RUTAS DE ENTRADA / SALIDA
# ============================================================
RUTA_CANDIDATOS = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
RUTA_CSV_OUT    = os.path.join(BASE_DIR, "outputs", "csv", "vrp_resultados")
RUTA_CSV_ANALISIS = os.path.join(BASE_DIR, "outputs", "csv", "vrp_resultados")
RUTA_GRAFICAS   = os.path.join(BASE_DIR, "outputs", "graficas")

_CSV_A2   = os.path.join(RUTA_CSV_OUT, "vrp_resultados_A2_b.csv")
_CSV_CAND = os.path.join(RUTA_CSV_OUT, "vrp_resultados_candidatos_b.csv")


# ============================================================
#  MAIN
# ============================================================

def main():
    os.makedirs(RUTA_GRAFICAS, exist_ok=True)

    print("=" * 65)
    print("  07_OPTIMO_K -- Numero optimo de centros de ultima milla")
    print(f"  OPEX/centro: {OPEX_CENTRO_ANIO:,.0f} EUR/anio | "
          f"CAPEX: {CAPEX_CENTRO/1e6:.0f} M EUR | "
          f"Vida util: {VIDA_UTIL_ANOS} anios | K_MAX: {K_MAX}")
    print("=" * 65)

    # ----------------------------------------------------------
    # 1. Datos base: secciones censales + demanda
    # ----------------------------------------------------------
    print("\n[1] Cargando secciones censales y demanda...")
    df_secciones = pd.read_excel(_vrp.RUTA_DATOS, sheet_name="Dat")
    df_secciones["Seccion INE"] = df_secciones["Seccion INE"].astype(int)
    df_secciones = df_secciones.dropna(subset=["Latitud", "Longitud"]).reset_index(drop=True)

    demanda    = cargar_demanda()
    nodos_base = preparar_nodos(df_secciones, demanda)
    print(f"  Secciones con demanda: {len(nodos_base)}")

    # ----------------------------------------------------------
    # 2. Baseline A2
    # ----------------------------------------------------------
    print("\n[2] Cargando baseline A2...")
    if not os.path.exists(_CSV_A2):
        print(f"ERROR: {_CSV_A2} no encontrado.")
        print("Ejecuta primero: vrp_ortools_cvrptw.py con MODO='A2'")
        sys.exit(1)
    df_a2 = pd.read_csv(_CSV_A2)
    coste_routing_dia_A2 = float(df_a2["coste_total_dia"].iloc[0])
    print(f"  A2 coste routing/dia: {coste_routing_dia_A2:,.2f} EUR")

    # ----------------------------------------------------------
    # 3. Resultados K=1,2,3 existentes
    # ----------------------------------------------------------
    print("\n[3] Cargando resultados K=1,2,3 existentes...")
    coste_routing_dia = {}
    depot_nombres_k   = {}

    if not os.path.exists(_CSV_CAND):
        print(f"ERROR: {_CSV_CAND} no encontrado.")
        print("Ejecuta primero: vrp_ortools_cvrptw.py con MODO='candidatos'")
        sys.exit(1)

    df_cand = pd.read_csv(_CSV_CAND, encoding="utf-8-sig")
    for _, row in df_cand.iterrows():
        alt = str(row["alternativa"])
        if not alt.startswith("C-K"):
            continue
        k = int(alt.replace("C-K", ""))
        coste_routing_dia[k] = float(row["coste_total_dia"])
        depot_nombres_k[k]   = str(row["depot_nombres"])
        print(f"  K={k}: {coste_routing_dia[k]:,.2f} EUR/dia | {depot_nombres_k[k][:60]}")

    k_existentes = sorted(coste_routing_dia.keys())
    k_nuevo_min  = (max(k_existentes) + 1) if k_existentes else 1

    # ----------------------------------------------------------
    # 4. P-Median + VRP para K = k_nuevo_min .. K_MAX
    # ----------------------------------------------------------
    if k_nuevo_min <= K_MAX:
        print(f"\n[4] Construyendo matriz de tiempos OSRM "
              f"para P-Median K={k_nuevo_min}..{K_MAX}...")
        df_candidatos = pd.read_csv(RUTA_CANDIDATOS, encoding="utf-8-sig")
        df_candidatos = df_candidatos.dropna(
            subset=["Latitud", "Longitud"]
        ).reset_index(drop=True)

        secciones_ine = [str(int(x)) for x in df_secciones["Seccion INE"].tolist()]
        pesos_arr     = df_secciones["Peso"].values.astype(float)

        tiempos_matrix, df_cand_inc = construir_matriz_tiempos(df_candidatos, secciones_ine)
        if tiempos_matrix is None:
            print("ERROR: sin matrices OSRM. Ejecuta 05_extraccion_tiempos_osrm.py primero.")
            sys.exit(1)
        n_cand_inc = tiempos_matrix.shape[0]
        print(f"  Matriz: {n_cand_inc} candidatos x {tiempos_matrix.shape[1]} secciones")

        for k in range(k_nuevo_min, K_MAX + 1):
            if k > n_cand_inc:
                print(f"  K={k}: no hay suficientes candidatos ({n_cand_inc}). Deteniendo.")
                break

            metodo = "exacto" if k <= 3 else "greedy"
            print(f"\n[4.{k}] K={k} P-Median ({metodo})...")
            indices, coste_pm, _ = p_median_exacto(tiempos_matrix, pesos_arr, k)

            depots = []
            for idx in indices:
                row_c = df_cand_inc.iloc[idx]
                depots.append({
                    "nombre": str(row_c["Nombre"]),
                    "lat":    float(row_c["Latitud"]),
                    "lon":    float(row_c["Longitud"]),
                })
            nombres_k = [d["nombre"] for d in depots]
            print(f"  K={k} ganadores: {' + '.join(nombres_k)}")
            print(f"  Coste P-Median: {coste_pm:.2f} min/paq ponderado")

            tiempos_por_depot    = {}
            distancias_por_depot = {}
            for d in depots:
                t    = cargar_tiempos_osrm(d["nombre"])
                dist = cargar_distancias_osrm(d["nombre"])
                if t:
                    tiempos_por_depot[d["nombre"]]    = t
                    distancias_por_depot[d["nombre"]] = dist or {}
                else:
                    print(f"  AVISO: sin OSRM para '{d['nombre']}' -- Haversine fallback")

            print(f"  K={k}: ejecutando VRP multi-depot...")
            print("-" * 40)
            rutas = vrp_multi_depot(depots, nodos_base, tiempos_por_depot, distancias_por_depot)
            print("-" * 40)
            kpis  = calcular_kpis(rutas, nodos_base, tiempos_por_depot)

            coste_routing_dia[k] = kpis["coste_total_dia"]
            depot_nombres_k[k]   = "|".join(nombres_k)
            print(f"  K={k}: coste routing/dia = {coste_routing_dia[k]:,.2f} EUR")
    else:
        print(f"\n[4] K_MAX={K_MAX} cubierto por resultados existentes.")

    # ----------------------------------------------------------
    # 5. Modelo de costes y beneficio neto
    # ----------------------------------------------------------
    print("\n[5] Modelo de costes...")
    coste_routing_anual_A2 = coste_routing_dia_A2 * DIAS_ANIO
    Ks       = sorted(coste_routing_dia.keys())
    Ks_eval  = [k for k in Ks if k <= K_MAX]
    resultados = {}

    for k in Ks_eval:
        routing_anual  = coste_routing_dia[k] * DIAS_ANIO
        opex_centros   = OPEX_CENTRO_ANIO * k
        capex_amort    = CAPEX_CENTRO * k / VIDA_UTIL_ANOS
        ahorro_routing = coste_routing_anual_A2 - routing_anual
        coste_centros  = opex_centros + capex_amort
        beneficio_neto = ahorro_routing - coste_centros

        resultados[k] = {
            "routing_anual_eur":  routing_anual,
            "opex_centros_eur":   opex_centros,
            "capex_amort_eur":    capex_amort,
            "ahorro_routing_eur": ahorro_routing,
            "coste_centros_eur":  coste_centros,
            "beneficio_neto_eur": beneficio_neto,
            "depot_nombres":      depot_nombres_k[k],
        }
        print(f"  K={k}: ahorro routing={ahorro_routing/1e6:+.3f} M EUR | "
              f"coste centros={coste_centros/1e6:.3f} M EUR | "
              f"beneficio neto={beneficio_neto/1e6:+.3f} M EUR")

    K_optimo  = max(Ks_eval, key=lambda k: resultados[k]["beneficio_neto_eur"])
    bn_optimo = resultados[K_optimo]["beneficio_neto_eur"]
    print(f"\n  K OPTIMO: {K_optimo} centros ({bn_optimo/1e6:+.3f} M EUR/anio)")

    if K_optimo == K_MAX:
        print("  AVISO: el optimo coincide con K_MAX. "
              "Incrementa K_MAX para confirmar el maximo real.")
    if bn_optimo < 0:
        print("  AVISO: ninguna alternativa C supera a A2 con el modelo de costes actual.")

    # ----------------------------------------------------------
    # 6. Exportar CSV
    # ----------------------------------------------------------
    rows = []
    for k in Ks_eval:
        r = dict(resultados[k])
        r["K"]        = k
        r["K_optimo"] = (k == K_optimo)
        rows.append(r)
    df_out = pd.DataFrame(rows)[[
        "K", "routing_anual_eur", "opex_centros_eur", "capex_amort_eur",
        "ahorro_routing_eur", "coste_centros_eur", "beneficio_neto_eur",
        "K_optimo", "depot_nombres",
    ]]
    ruta_csv_out = os.path.join(RUTA_CSV_OUT, "analisis_optimo_K.csv")
    df_out.to_csv(ruta_csv_out, index=False, encoding="utf-8-sig")
    print(f"\n  CSV: {ruta_csv_out}")

    # ----------------------------------------------------------
    # 7. Grafica 3 curvas
    # ----------------------------------------------------------
    print("\n[6] Generando grafica...")
    ahorro_M = [resultados[k]["ahorro_routing_eur"] / 1e6 for k in Ks_eval]
    coste_M  = [resultados[k]["coste_centros_eur"]  / 1e6 for k in Ks_eval]
    benef_M  = [resultados[k]["beneficio_neto_eur"] / 1e6 for k in Ks_eval]

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(Ks_eval, ahorro_M, color="#2ca02c", marker="o", linewidth=1.8,
            markersize=7, label="Ahorro anual en distribucion vs. A2")
    ax.plot(Ks_eval, coste_M,  color="#d62728", marker="s", linewidth=1.8,
            markersize=7, label="Coste anual de los centros (OPEX + amort. CAPEX)")
    ax.plot(Ks_eval, benef_M,  color="#1f77b4", marker="D", linewidth=2.5,
            markersize=8, label="Beneficio neto anual (ahorro - coste centros)")

    ax.axhline(0, color="grey", linestyle="--", linewidth=0.9,
               label="Umbral de rentabilidad")

    # Marcador K optimo
    k_opt_y   = bn_optimo / 1e6
    y_rng     = max(ahorro_M + coste_M + benef_M) - min(ahorro_M + coste_M + benef_M)
    offset_y  = y_rng * 0.10
    offset_x  = 0.35 if K_optimo < max(Ks_eval) else -0.35
    ha_annot  = "left" if K_optimo < max(Ks_eval) else "right"
    ax.axvline(K_optimo, color="#1f77b4", linestyle=":", linewidth=1.2, alpha=0.7)
    ax.annotate(
        f"K optimo = {K_optimo}\n{k_opt_y:+.2f} M EUR/anio",
        xy=(K_optimo, k_opt_y),
        xytext=(K_optimo + offset_x, k_opt_y + offset_y),
        fontsize=9,
        color="#1f77b4",
        ha=ha_annot,
        arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=1.2),
    )

    ax.set_xlabel("Numero de centros de distribucion (K)", fontsize=11)
    ax.set_ylabel("M EUR / anio", fontsize=11)
    ax.set_title(
        "Beneficio neto anual segun numero de centros de ultima milla\n"
        "(vs. situacion actual A2: SVQ1 + DQA4)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xticks(Ks_eval)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(fontsize=9, loc="best")
    fig.tight_layout()

    ruta_png = os.path.join(RUTA_GRAFICAS, "OptimizacionK_Centros.png")
    fig.savefig(ruta_png, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  Grafica: {ruta_png}")
    print("\n  Proceso completado.")


if __name__ == "__main__":
    main()
