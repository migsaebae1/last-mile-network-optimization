# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import pandas as pd
import numpy as np

# Semilla fija: la simulacion de demanda es estocastica, y fijarla
# garantiza que el estudio sea reproducible cifra a cifra.
SEMILLA = 42
np.random.seed(SEMILLA)
from datetime import datetime, timedelta

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz del repositorio

# ==========================================
# 1. CARGA DE DATOS
# ==========================================
ruta_lectura = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
df_nodos = pd.read_excel(ruta_lectura, sheet_name='Dat')

pesos = df_nodos['Peso'].values
nombres_nodos = df_nodos['Seccion INE'].astype(str).values
n_nodos = len(pesos)

# Pesos base normalizados
pesos_normalizados = pesos / pesos.sum()

# ==========================================
# 2. CONFIGURACIÓN DEL MODELO DE DEMANDA
# ==========================================
demanda_base = 38900

# Variaciones macro (Trimestrales)
variaciones_mes = {
    (1, 2, 3): -0.15,   # Enero-Marzo (Valle post-Reyes)
    (4, 5, 6): 0.00,    # Abril-Junio (Plano)
    (7, 8, 9): 0.08,    # Julio-Septiembre (Ligero repunte)
    (10, 11, 12): 0.25  # Octubre-Diciembre (Pico anual)
}

# Factor de día de la semana (Media = 1.0 para no alterar la demanda base)
# Lunes(0) es el día más fuerte, Domingo(6) el más flojo
factores_semana = {0: 1.3, 1: 1.2, 2: 1.1, 3: 1.0, 4: 0.9, 5: 0.8, 6: 0.7}

# ==========================================
# 3. GENERACIÓN DE INSTANCIAS (365 DÍAS)
# ==========================================
fecha_inicio = datetime(2025, 1, 1)
datos_demanda = []
fechas = []

for dia in range(365):
    fecha_actual = fecha_inicio + timedelta(days=dia)
    fechas.append(fecha_actual.strftime('%Y-%m-%d'))
    mes = fecha_actual.month
    
    # --- A. FACTORES TEMPORALES ---
    var_temporada = next(valor for meses, valor in variaciones_mes.items() if mes in meses)
    f_semana = factores_semana[fecha_actual.weekday()]
    
    # --- B. EVENTOS ESPECIALES (Cisnes Negros Logísticos) ---
    f_evento = 1.0
    # Ejemplo: Prime Day (15-16 de Julio) -> +60% demanda
    if mes == 7 and 15 <= fecha_actual.day <= 16:
        f_evento = 1.6
    # Ejemplo: Black Friday & Cyber Monday (24-27 de Noviembre) -> +90% demanda
    elif mes == 11 and 24 <= fecha_actual.day <= 27:
        f_evento = 1.90

    # --- C. CÁLCULO DEMANDA TOTAL DEL DÍA ---
    # Multiplicamos la base por todos los factores logísticos
    demanda_total_dia = demanda_base * (1 + var_temporada) * f_semana * f_evento
    
    # Añadimos un ruido global del 3% para simular incertidumbre diaria
    ruido_diario = np.random.normal(0, demanda_total_dia * 0.03)
    demanda_final_dia = max(0, demanda_total_dia + ruido_diario)
    
    # --- D. DISTRIBUCIÓN ESPACIAL (NODOS) ---
    # Generamos variabilidad por barrio/nodo (±5%)
    variabilidad_local = np.random.uniform(0.95, 1.05, size=n_nodos)
    
    # Aplicamos el ruido a los pesos base y RENORMALIZAMOS
    # Esto asegura que la suma de los paquetes de los nodos sea exactamente 'demanda_final_dia'
    pesos_del_dia = pesos_normalizados * variabilidad_local
    pesos_del_dia /= pesos_del_dia.sum() 
    
    # Reparto final y redondeo a enteros
    demanda_nodos = (demanda_final_dia * pesos_del_dia).round().astype(int)
    datos_demanda.append(demanda_nodos)

# ==========================================
# 4. EXPORTACIÓN
# ==========================================
df_final = pd.DataFrame(datos_demanda, columns=nombres_nodos)
df_final.insert(0, 'Fecha', fechas)

ruta_salida = os.path.join(BASE_DIR, "outputs", "xlsx", "Demanda_Amazon_365_Mejorada.xlsx")

try:
    df_final.to_excel(ruta_salida, index=False)
    print(f"✅ ¡Éxito! Archivo generado en: {ruta_salida}")
    # Pequeño reporte por consola para validar
    print("-" * 30)
    print("📊 RESUMEN DE LA SIMULACIÓN:")
    print(f"Total de nodos: {n_nodos}")
    print(f"Demanda media diaria generada: {int(df_final.iloc[:, 1:].sum(axis=1).mean())} paquetes")
    print(f"Pico máximo generado (ej. Black Friday): {int(df_final.iloc[:, 1:].sum(axis=1).max())} paquetes")
    print(f"Día más flojo generado: {int(df_final.iloc[:, 1:].sum(axis=1).min())} paquetes")
    print("-" * 30)
except Exception as e:
    print(f"❌ Error al guardar el archivo: {e}")