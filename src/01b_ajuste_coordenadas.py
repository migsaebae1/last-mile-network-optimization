# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import requests
import time
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz del repositorio

# --- 1. CONFIGURACIÓN DE RUTAS ---
ruta_entrada = os.path.join(BASE_DIR, "data", "raw", "Todas_Coordenadas_Secciones_INE.xlsx")
ruta_salida  = os.path.join(BASE_DIR, "data", "raw", "Secciones_CCHS_Corregidas_Vial.xlsx")

# Providencias de estudio (Filtro CCHS)
provincias_objetivo = ['Cádiz', 'Huelva', 'Córdoba', 'Sevilla']

def ajustar_a_carretera(lat, lon):
    """Proyecta el punto a la carretera más cercana usando OSRM."""
    # OSRM usa formato: lon,lat
    osrm_url = f"http://router.project-osrm.org/nearest/v1/driving/{lon},{lat}?number=1"
    try:
        response = requests.get(osrm_url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 'Ok' and data.get('waypoints'):
                nueva_lon, nueva_lat = data['waypoints'][0]['location']
                return round(nueva_lat, 6), round(nueva_lon, 6)
    except:
        pass
    return lat, lon

# --- 2. CARGA Y FILTRADO ---
print(f"Cargando datos desde: {ruta_entrada}...")
# Cargamos la hoja específica 'CCHS' si existe, si no, la hoja por defecto
try:
    df = pd.read_excel(ruta_entrada, sheet_name='CCHS')
except:
    print("Aviso: No se encontró la hoja 'CCHS', cargando primera hoja y filtrando por columna 'Provincia'...")
    df = pd.read_excel(ruta_entrada)

# Filtrar para asegurarse de que solo procesamos Cádiz, Huelva, Córdoba y Sevilla
# Nota: Usamos str.contains por si el formato es "Andalucía - Sevilla"
print("Filtrando provincias: Cádiz, Huelva, Córdoba y Sevilla...")
df_filtrado = df[df['Provincia'].str.contains('|'.join(provincias_objetivo), case=False, na=False)].copy()

print(f"Registros a procesar tras filtrar: {len(df_filtrado)}")

# --- 3. PROCESO DE AJUSTE VIAL ---
lats_corregidas = []
lons_corregidas = []

print("\nIniciando Road-Snapping (Ajuste a carretera)...")
for idx, row in df_filtrado.iterrows():
    lat_vial, lon_vial = ajustar_a_carretera(row['Latitud'], row['Longitud'])
    lats_corregidas.append(lat_vial)
    lons_corregidas.append(lon_vial)
    
    # Progreso visual
    if (len(lats_corregidas)) % 50 == 0:
        print(f"Progreso: {len(lats_corregidas)}/{len(df_filtrado)} nodos ajustados...")
    
    # Pausa corta para estabilidad de la API
    time.sleep(0.2)

# --- 4. GUARDADO ---
df_filtrado['Latitud_Original'] = df_filtrado['Latitud']
df_filtrado['Longitud_Original'] = df_filtrado['Longitud']
df_filtrado['Latitud'] = lats_corregidas
df_filtrado['Longitud'] = lons_corregidas

df_filtrado.to_excel(ruta_salida, index=False)

print("\n" + "="*60)
print(f"✅ PROCESO COMPLETADO")
print(f"📂 Archivo generado: {ruta_salida}")
print(f"📍 Total nodos corregidos: {len(df_filtrado)}")
print("="*60)