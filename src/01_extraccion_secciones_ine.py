# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raiz del repositorio

import requests
import pandas as pd
from shapely.geometry import shape
import time

# Aumentamos el límite por petición para ir más rápido, pero sin saturar
url = "https://www.ine.es/geoserver/ogc/features/v1/collections/WMS_INE_SECCIONES_G01:Secciones_2023/items?f=application%2Fgeo%2Bjson&limit=5000"

resultados = []

print("Iniciando descarga de secciones del INE. Esto puede tardar un par de minutos...")

while url:
    print(f"Descargando lote desde servidor...")
    response = requests.get(url)
    
    # Si hay un error de conexión, paramos para no bloquear el programa
    if response.status_code != 200:
        print(f"Error al conectar con el INE: {response.status_code}")
        break
        
    data = response.json()
    
    # Procesar las secciones de este lote
    for feature in data.get("features", []):
        props = feature["properties"]
        geom = shape(feature["geometry"])
        centroide = geom.centroid
        
        # Extraemos el código CUSEC (Sección INE) y datos útiles
        resultados.append({
            "Seccion_INE": props.get("CUSEC", feature.get("id")), 
            "Provincia": props.get("NCA", "") + " - " + props.get("NPRO", ""),
            "Municipio": props.get("NMUN", ""),
            "Distrito": props.get("CDIS", ""),
            "Seccion": props.get("CSEC", ""),
            "Latitud": round(centroide.y, 6),
            "Longitud": round(centroide.x, 6)
        })
        
    # Buscar el enlace a la siguiente página (paginación)
    next_link = None
    for link in data.get("links", []):
        if link.get("rel") == "next":
            next_link = link.get("href")
            break
            
    # Actualizar la URL para la siguiente vuelta del bucle
    url = next_link
    time.sleep(1) # Pequeña pausa de 1 segundo para ser amables con el servidor del INE

# Crear la tabla
df = pd.DataFrame(resultados)

# Guardar en Excel (Ajusta la ruta a tu carpeta del proyecto si quieres)
ruta_excel = os.path.join(BASE_DIR, "data", "raw", "Todas_Coordenadas_Secciones_INE.xlsx")
df.to_excel(ruta_excel, index=False)

print("\n" + "-"*50)
print(f"✅ ¡Proceso terminado! Se han descargado {len(df)} secciones.")
print(f"✅ Archivo guardado con éxito en: {ruta_excel}")