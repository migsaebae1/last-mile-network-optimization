# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import glob
import pandas as pd

# ==========================================
# 1. CONSTANTES Y CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directorios actualizados con los nombres exactos (añadidos 5 y 8 centros)
DIR_1_CENTRO = os.path.join(BASE_DIR, "outputs", "rutas_individuales_generadas") 
DIR_2_CENTROS = os.path.join(BASE_DIR, "outputs", "rutas_parejas_generadas")
DIR_3_CENTROS = os.path.join(BASE_DIR, "outputs", "rutas_trios_generados")
DIR_4_CENTROS = os.path.join(BASE_DIR, "outputs", "rutas_cuartetos_generados")
DIR_5_CENTROS = os.path.join(BASE_DIR, "outputs", "rutas_quintetos_generados")
DIR_8_CENTROS = os.path.join(BASE_DIR, "outputs", "rutas_octetos_generados")

DIRECTORIOS_A_EVALUAR = {
    "1_Centro": DIR_1_CENTRO,
    "2_Centros": DIR_2_CENTROS,
    "3_Centros": DIR_3_CENTROS,
    "4_Centros": DIR_4_CENTROS,
    "5_Centros": DIR_5_CENTROS,
    "8_Centros": DIR_8_CENTROS
}

RUTA_SALIDA_RESUMEN = os.path.join(BASE_DIR, "outputs", "campeones_tecnicos_red.csv")

# ==========================================
# 2. MOTOR DE EVALUACIÓN
# ==========================================
def evaluar_escenarios(nombre_categoria, ruta_directorio):
    if not os.path.exists(ruta_directorio):
        print(f"⚠️ El directorio no existe o está vacío: {ruta_directorio}")
        return None

    archivos_csv = glob.glob(os.path.join(ruta_directorio, "*.csv"))
    if not archivos_csv:
        print(f"⚠️ No hay archivos CSV en: {ruta_directorio}")
        return None
    
    print(f"\n🔍 Analizando {len(archivos_csv)} escenarios para la categoría: {nombre_categoria}...")
    resultados = []

    for archivo in archivos_csv:
        try:
            # Cargamos solo las columnas necesarias según la estructura real de tu CSV
            df = pd.read_csv(archivo, usecols=['id_camion', 'km_tramo', 'tiempo_tramo_min'])
            
            # Cálculo de las 3 métricas vitales
            total_transportistas = int(df['id_camion'].max())
            total_km = float(df['km_tramo'].sum())
            total_tiempo = float(df['tiempo_tramo_min'].sum())
            
            nombre_archivo = os.path.basename(archivo)
            
            resultados.append({
                "Categoria": nombre_categoria,
                "Archivo": nombre_archivo,
                "Transportistas": total_transportistas,
                "KM_Totales": total_km,
                "Tiempo_Total_Mins": total_tiempo,
                # Ruta relativa a la raiz del repositorio: evita filtrar rutas
                # absolutas (y el nombre de usuario del SO) al CSV versionado.
                "Ruta_Completa": os.path.relpath(archivo, BASE_DIR).replace(os.sep, "/")
            })
            
        except Exception as e:
            print(f"   ❌ Error procesando {archivo}: {e}")
            continue
            
    if not resultados:
        return None
        
    df_resultados = pd.DataFrame(resultados)
    
    # ==========================================
    # 3. FILTRO EN CASCADA (OPCIÓN A)
    # ==========================================
    # Ordenamos estrictamente: 
    # 1º Transportistas (Ascendente)
    # 2º KM_Totales (Ascendente)
    # 3º Tiempo_Total (Ascendente)
    df_ordenado = df_resultados.sort_values(
        by=['Transportistas', 'KM_Totales', 'Tiempo_Total_Mins'], 
        ascending=[True, True, True]
    ).reset_index(drop=True)
    
    # El ganador absoluto es la fila 0
    ganador = df_ordenado.iloc[0]
    
    print(f"🏆 GANADOR {nombre_categoria}: {ganador['Archivo']}")
    print(f"   🚚 Flota requerida: {ganador['Transportistas']} furgonetas")
    print(f"   🛣️ Distancia total: {ganador['KM_Totales']:.2f} km")
    print(f"   ⏱️ Tiempo total: {ganador['Tiempo_Total_Mins']:.2f} minutos")
    
    return df_ordenado.iloc[0:1]

# ==========================================
# 4. EJECUCIÓN PRINCIPAL
# ==========================================
print("Iniciando torneo de selección técnica de la red logística (1 a 8 centros)...")
campeones = []

for categoria, ruta in DIRECTORIOS_A_EVALUAR.items():
    df_ganador = evaluar_escenarios(categoria, ruta)
    if df_ganador is not None:
        campeones.append(df_ganador)

if campeones:
    df_campeones_final = pd.concat(campeones, ignore_index=True)
    
    # Guardamos la tabla con los 6 ganadores definitivos (1, 2, 3, 4, 5 y 8 centros)
    df_campeones_final.to_csv(RUTA_SALIDA_RESUMEN, index=False, encoding='utf-8')
    print(f"\n✅ Análisis completado. El resumen de los campeones se ha guardado en:")
    print(f"   📂 {os.path.abspath(RUTA_SALIDA_RESUMEN)}")
else:
    print("\n❌ No se pudo encontrar ningún ganador. Revisa las rutas de las carpetas.")