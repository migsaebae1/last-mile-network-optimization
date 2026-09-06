"""
===================
Compara el escenario base de control (DQA4 como único centro) frente a los 
ganadores oficiales de cada categoría guardados en 'campeones_tecnicos_red.csv'.

Aplica un análisis multicriterio (MCDA) integrando CAPEX, OPEX, Servicio y Sostenibilidad.
"""
# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import pathlib
import numpy as np
import pandas as pd

# ============================================================
# 1. CONFIGURACIÓN DE RUTAS Y PARÁMETROS
# ============================================================
BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ruta_abs(p):
    """Resuelve una ruta del CSV de campeones contra la raiz del repositorio.

    Las rutas se guardan en relativo para no filtrar rutas absolutas al CSV
    versionado; anclarlas a BASE_DIR permite ejecutar el script desde
    cualquier directorio de trabajo.
    """
    p = str(p)
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)
RUTA_CAMPEONES    = pathlib.Path(BASE_DIR, "outputs", "campeones_tecnicos_red.csv")
RUTA_DQA4_CONTROL = pathlib.Path(BASE_DIR, "outputs", "rutas_ganadoras", "rutas_optimizadas_DQA4_checkpoint.csv")
RUTA_DEMANDA      = pathlib.Path(BASE_DIR, "outputs", "xlsx", "Demanda_Amazon_365_Mejorada.xlsx")
DIR_TIEMPOS       = pathlib.Path(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")
RUTA_INFORME_FIN  = pathlib.Path(BASE_DIR, "outputs", "csv", "Informe_Final_Red.csv")

# Parámetros Económicos y Ambientales (Juanjo Baseline Ajustado)
COSTE_KM           = 0.35    # EUR/km (Se mantiene, es realista)
COSTE_HORA         = 14.0    # EUR/h por transportista (Se mantiene)
CO2_KG_POR_KM      = 0.21    # kg CO2/km (Se mantiene)
SECCIONES_TOT      = 657     # Total secciones INE
COSTE_FIJO_HUB_DIA = 4500.0  #  CAPEX diario realista para un hub logístico

# Pesos del Modelo Multicriterio (MCDA) - Enfoque más a Negocio/Rentabilidad
W_COSTES           = 0.50    # 50% (Subimos el peso económico)
W_SERVICIO         = 0.30    # 30% (Bajamos ligeramente)
W_SOSTENIBILIDAD   = 0.20    # 20% (Bajamos ligeramente)

# ============================================================
# 2. CARGA DE DEMANDA GLOBAL (Para coberturas ponderadas)
# ============================================================
print("Cargando matriz de demanda para ponderación...")
df_dem = pd.read_excel(RUTA_DEMANDA, index_col=0)
df_dem.columns = df_dem.columns.astype(str).str.strip()
demanda_dia = np.ceil(df_dem.mean(axis=0)).astype(int)
demanda_dia.index = demanda_dia.index.astype(str).str.strip()
PAQUETES_TOT = int(demanda_dia.sum())

# ============================================================
# 3. CORE FUNCTIONS (Cálculo de KPIs unificado)
# ============================================================
def _coberturas_osrm(slugs_depots: list[str]) -> dict:
    merged = {}
    encontrado = False
    for slug in slugs_depots:
        clean_slug = str(slug).replace("Inicio_", "").replace("Regreso_", "").strip()
        p = DIR_TIEMPOS / f"tiempos_{clean_slug}_checkpoint.csv"
        if not p.exists(): continue
        
        try:
            with p.open(encoding="utf-8") as fh:
                df = pd.read_csv(fh)
            encontrado = True
            df["seccion_ine"] = df["seccion_ine"].astype(str).str.strip()
            for _, row in df.iterrows():
                sec = row["seccion_ine"]
                t   = float(row["tiempo_mins"])
                if sec not in merged or t < merged[sec]:
                    merged[sec] = t
        except Exception:
            continue

    if not encontrado:
        return {"cobertura_60min_pct": float("nan"), "tiempo_medio_pond_min": float("nan")}

    c60 = 0
    t_num, t_den = 0.0, 0
    for sec, t in merged.items():
        dem = int(demanda_dia.get(sec, 0))
        if dem <= 0: continue
        if t <= 60: c60 += dem
        t_num += t * dem
        t_den += dem

    return {
        "cobertura_60min_pct": round(c60 / max(1, PAQUETES_TOT) * 100, 1),
        "tiempo_medio_pond_min": round(t_num / max(1, t_den), 2)
    }

def _slugs_desde_df(df: pd.DataFrame) -> list[str]:
    if "Centro_Origen" not in df.columns: return []
    raw = df["Centro_Origen"].dropna().unique().tolist()
    return list(set(str(s).replace("Inicio_", "").replace("Regreso_", "").strip() for s in raw))

def procesar_archivo_rutas(ruta_csv, etiqueta_modo, categoria_str) -> dict:
    with open(ruta_csv, encoding="utf-8") as f:
        df = pd.read_csv(f)
    
    df["nodo_ine"] = df["nodo_ine"].astype(str).str.strip()
    df_paradas = df[~df["nodo_ine"].str.startswith(("Inicio_", "Regreso_"))]

    n_camiones = df["id_camion"].nunique()
    paquetes_total = int(df_paradas["paquetes"].sum())
    km_total = round(df["km_tramo"].sum(), 1)
    
    # OPEX
    coste_km = km_total * COSTE_KM
    horas_cond = df.groupby("Id_Transportista")["tiempo_acumulado_min"].max() / 60.0
    coste_cond = horas_cond.sum() * COSTE_HORA
    opex_dia = round(coste_km + coste_cond, 2)
    
    # Sostenibilidad
    co2 = round(km_total * CO2_KG_POR_KM, 1)
    
    # Extraer Nodos
    slugs = _slugs_desde_df(df)
    n_depots = len(slugs) if slugs else 1
    if not slugs and "DQA4" in str(ruta_csv): slugs = ["DQA4"]
    
    # Servicio (OSRM)
    cob = _coberturas_osrm(slugs)
    
    # CAPEX e Integración Financiera
    capex_dia = n_depots * COSTE_FIJO_HUB_DIA
    coste_financiero_total = capex_dia + opex_dia

    return {
        "modo": etiqueta_modo,
        "categoria": categoria_str,
        "n_depots": n_depots,
        "depot_nombres": " | ".join(slugs),
        "n_furgonetas": n_camiones,
        "km_total": km_total,
        "capex_dia": capex_dia,
        "opex_dia": opex_dia,
        "coste_financiero_total": coste_financiero_total,
        "cobertura_60min_pct": cob["cobertura_60min_pct"],
        "tiempo_medio_pond_min": cob["tiempo_medio_pond_min"],
        "co2_kg_dia": co2
    }

# ============================================================
# 4. BUCLE DE RECOPILACIÓN (Campeones + Control DQA4)
# ============================================================
print("\nEjecutando extracción analítica...")
datos_comparativa = []

# A. Procesar los ganadores oficiales indexados en el torneo
if RUTA_CAMPEONES.exists():
    df_camp = pd.read_csv(RUTA_CAMPEONES)
    for _, fila in df_camp.iterrows():
        cat = fila["Categoria"]
        ruta_raw = _ruta_abs(fila["Ruta_Completa"])
        if os.path.exists(ruta_raw):
            print(f" -> Procesando Ganador Técnico de la alternativa: {cat}")
            res = procesar_archivo_rutas(ruta_raw, f"Ganador {cat}", cat)
            datos_comparativa.append(res)
        else:
            print(f" !! FALTA el fichero de rutas de {cat}: {ruta_raw}")
            print("    La comparativa quedaria incompleta. Ejecuta antes src/06_rutas_*.py")
else:
    print("⚠️ Alerta: No se encontró el índice 'campeones_tecnicos_red.csv'.")

# B. Inyectar obligatoriamente la opción DQA4 (Línea base de control)
if RUTA_DQA4_CONTROL.exists():
    print(" -> Rescatando línea base de control 'DQA4' (1 Centro Manual)...")
    res_dqa4 = procesar_archivo_rutas(RUTA_DQA4_CONTROL, "Control Manual (DQA4)", "1_Centro")
    datos_comparativa.append(res_dqa4)
else:
    print(f"❌ Error Crítico: No se localiza el archivo de control en: {RUTA_DQA4_CONTROL}")

df_final = pd.DataFrame(datos_comparativa)

# ============================================================
# 5. MODELO MULTICRITERIO (MCDA) Y CLASIFICACIÓN
# ============================================================
print("\nEvaluando alternativas bajo matriz de decisión unificada...")

# Scores Inversos (Menos es mejor)
for col, score_name in [("coste_financiero_total", "score_coste"), ("co2_kg_dia", "score_co2")]:
    mx, mn = df_final[col].max(), df_final[col].min()
    df_final[score_name] = 100 * (1 - (df_final[col] - mn) / max(1, mx - mn))

# Scores Directos (Más es mejor)
mx_cob, mn_cob = df_final["cobertura_60min_pct"].max(), df_final["cobertura_60min_pct"].min()
df_final["score_servicio"] = 100.0 if mx_cob == mn_cob else 100 * (df_final["cobertura_60min_pct"] - mn_cob) / (mx_cob - mn_cob)

# Puntuación de Negocio Global
df_final["mcda_puntuacion"] = (
    df_final["score_coste"] * W_COSTES +
    df_final["score_servicio"] * W_SERVICIO +
    df_final["score_co2"] * W_SOSTENIBILIDAD
).round(2)

df_final = df_final.sort_values(by="mcda_puntuacion", ascending=False).reset_index(drop=True)

# Exportación definitiva
os.makedirs(RUTA_INFORME_FIN.parent, exist_ok=True)
df_final.to_csv(RUTA_INFORME_FIN, index=False, encoding="utf-8-sig")

# ============================================================
# 6. CUADRO DE MANDOS POR CONSOLA
# ============================================================
print(f"\n{'='*95}")
print(f"🏆 CLASIFICACIÓN FINAL ESTRATÉGICA DE LA RED (CAPEX Asumido: {COSTE_FIJO_HUB_DIA} €/hub/día)")
print(f"{'='*95}")
for idx, row in df_final.iterrows():
    print(f"Pos {idx+1:d} | {row['modo']:28s} | Score: {row['mcda_puntuacion']:6.2f} pts | "
          f"Financiero: {row['coste_financiero_total']:7,.0f} €/día (OPEX: {row['opex_dia']:5,.0f}€) | "
          f"Cob60: {row['cobertura_60min_pct']:5.1f}% | CO2: {row['co2_kg_dia']:5,.0f} kg")
print(f"{'='*95}")
print(f"🚀 ARQUITECTURA GANADORA RECOMENDADA: {df_final.iloc[0]['modo']} -> Nodos: ({df_final.iloc[0]['depot_nombres']})")
print(f"💾 Guardado completo en: {RUTA_INFORME_FIN}\n")