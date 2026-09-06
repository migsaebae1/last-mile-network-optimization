# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import glob
import math
import pandas as pd
import numpy as np

# ==========================================
# 1. CONSTANTES Y CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_DEMANDA = os.path.join(BASE_DIR, "outputs", "xlsx", "Demanda_Amazon_365_Mejorada.xlsx")
RUTA_DATOS = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
DIRECTORIO_CHECKPOINTS = os.path.join(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")

# Corregido typo 'idividuales' -> 'individuales' para sincronizar con el evaluador
RUTA_RESULTADOS = os.path.join(BASE_DIR, "outputs", "rutas_individuales_generadas")
os.makedirs(RUTA_RESULTADOS, exist_ok=True)

# Restricciones
CAPACIDAD_FURGONETA = 140
JORNADA_MAX_MIN = 480
TIEMPO_CARGA_MIN = 40
TIEMPO_ENTREGA_MIN = 3
VELOCIDAD_MEDIA_KMH = 50.0

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================
def calcular_haversine(lat1, lon1, lat2, lon2):
    """Calcula la distancia en km entre dos puntos en la Tierra."""
    R = 6371.0 # Radio de la Tierra en km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def tiempo_viaje_vecino(km):
    """Convierte kilómetros a minutos usando la velocidad media."""
    return (km / VELOCIDAD_MEDIA_KMH) * 60.0

# ==========================================
# 3. CARGA Y NORMALIZACIÓN DE DATOS PRINCIPALES
# ==========================================
print("Cargando y normalizando datos principales...")
df_datos = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
df_datos['Seccion INE'] = df_datos['Seccion INE'].astype(str).str.strip()
coordenadas = df_datos.set_index('Seccion INE')[['Latitud', 'Longitud']].to_dict('index')

df_demanda = pd.read_excel(RUTA_DEMANDA, index_col=0)
df_demanda.columns = df_demanda.columns.astype(str).str.strip()

# Agrupación y redondeo de demanda media diaria
demanda_dia_original = np.ceil(df_demanda.mean(axis=0)).astype(int).to_dict()

# ==========================================
# 4. PROCESAMIENTO DE CANDIDATOS
# ==========================================
patron_busqueda = os.path.join(DIRECTORIO_CHECKPOINTS, "tiempos_*_checkpoint.csv")
archivos_checkpoints = glob.glob(patron_busqueda)

print(f"\n▶️ Se han detectado {len(archivos_checkpoints)} archivos checkpoint para procesar.")

for archivo_check in archivos_checkpoints:
    nombre_archivo_original = os.path.basename(archivo_check)
    nombre_candidato = nombre_archivo_original.replace("tiempos_", "").replace("_checkpoint.csv", "")
    
    df_check = pd.read_csv(archivo_check)
    df_check['seccion_ine'] = df_check['seccion_ine'].astype(str).str.strip()
    tiempos_candidato = df_check.set_index('seccion_ine')[['distancia_km', 'tiempo_mins']].to_dict('index')
    
    demanda_pendiente = {nodo: dem for nodo, dem in demanda_dia_original.items() 
                         if dem > 0 and nodo in tiempos_candidato and nodo in coordenadas}
    
    if len(demanda_pendiente) == 0:
        print(f"❌ Candidato '{nombre_candidato}' ignorado: No hay demanda activa coincidente.")
        continue

    # --- VALIDACIÓN MATEMÁTICA ---
    candidato_valido = True
    for nodo, dem in demanda_pendiente.items():
        t_ida = tiempos_candidato[nodo]['tiempo_mins']
        t_minimo_posible = TIEMPO_CARGA_MIN + (t_ida * 2) + TIEMPO_ENTREGA_MIN
        if t_minimo_posible > JORNADA_MAX_MIN:
            print(f"⚠️ [DESCARTADO] El candidato '{nombre_candidato}' se descartó porque el nodo {nodo} exige {t_minimo_posible:.1f} min (Máx: 480).")
            candidato_valido = False
            break
    
    if not candidato_valido:
        continue 
        
    # --- GENERACIÓN DE RUTAS ---
    rutas_generadas = []
    id_transportista = 1
    id_camion = 1 
    
    while sum(demanda_pendiente.values()) > 0:
        tiempo_jornada_consumido = 0
        rutas_en_jornada = 0
        
        while tiempo_jornada_consumido < JORNADA_MAX_MIN and sum(demanda_pendiente.values()) > 0:
            nodo_inicial = None
            paquetes_arranque = 0
            
            for nodo, dem in demanda_pendiente.items():
                if dem <= 0: continue
                
                t_ida = tiempos_candidato[nodo]['tiempo_mins']
                t_vuelta = tiempos_candidato[nodo]['tiempo_mins']
                t_base_necesario = TIEMPO_CARGA_MIN + t_ida + t_vuelta
                
                tiempo_disponible_para_entregas = JORNADA_MAX_MIN - tiempo_jornada_consumido - t_base_necesario
                
                if tiempo_disponible_para_entregas >= TIEMPO_ENTREGA_MIN:
                    max_paquetes_por_tiempo = int(tiempo_disponible_para_entregas // TIEMPO_ENTREGA_MIN)
                    paquetes_arranque = min(CAPACIDAD_FURGONETA, dem, max_paquetes_por_tiempo)
                    if paquetes_arranque > 0:
                        nodo_inicial = nodo
                        break 
            
            if not nodo_inicial:
                break
                
            # INICIAR NUEVA RUTA (Carga en almacén)
            orden_parada = 1
            tiempo_ruta_actual = TIEMPO_CARGA_MIN
            capacidad_restante = CAPACIDAD_FURGONETA
            
            # ➕ Se añade la columna 'Centro_Origen' de forma nativa
            rutas_generadas.append({
                'id_camion': id_camion,
                'orden_parada': orden_parada,
                'nodo_ine': f"Inicio_{nombre_candidato}",
                'paquetes': 0,
                'km_tramo': 0,
                'tiempo_tramo_min': TIEMPO_CARGA_MIN,
                'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual,
                'Id_Transportista': id_transportista,
                'Centro_Origen': nombre_candidato
            })
            
            # PARADA 1: NODO INICIAL
            orden_parada += 1
            t_ida = tiempos_candidato[nodo_inicial]['tiempo_mins']
            km_ida = tiempos_candidato[nodo_inicial]['distancia_km']
            t_entregas = paquetes_arranque * TIEMPO_ENTREGA_MIN
            
            tiempo_ruta_actual += t_ida + t_entregas
            capacidad_restante -= paquetes_arranque
            demanda_pendiente[nodo_inicial] -= paquetes_arranque
            nodo_actual = nodo_inicial
            
            # ➕ Se añade la columna 'Centro_Origen' de forma nativa
            rutas_generadas.append({
                'id_camion': id_camion,
                'orden_parada': orden_parada,
                'nodo_ine': nodo_actual,
                'paquetes': paquetes_arranque,
                'km_tramo': km_ida,
                'tiempo_tramo_min': t_ida,
                'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual,
                'Id_Transportista': id_transportista,
                'Centro_Origen': nombre_candidato
            })
            
            # PARADAS SUBSIGUIENTES (Vecinos cercanos por Haversine)
            while capacidad_restante > 0 and sum(demanda_pendiente.values()) > 0:
                vecinos = []
                lat_actual, lon_actual = coordenadas[nodo_actual]['Latitud'], coordenadas[nodo_actual]['Longitud']
                
                for vec, dem in demanda_pendiente.items():
                    if dem > 0:
                        lat_vec, lon_vec = coordenadas[vec]['Latitud'], coordenadas[vec]['Longitud']
                        dist_km = calcular_haversine(lat_actual, lon_actual, lat_vec, lon_vec)
                        vecinos.append((dist_km, vec))
                
                vecinos.sort()
                
                vecino_visitado = False
                for dist_km, vec in vecinos:
                    t_viaje_vec = tiempo_viaje_vecino(dist_km)
                    t_regreso_desde_vec = tiempos_candidato[vec]['tiempo_mins']
                    t_disponible = JORNADA_MAX_MIN - (tiempo_jornada_consumido + tiempo_ruta_actual + t_viaje_vec + t_regreso_desde_vec)
                    
                    if t_disponible >= TIEMPO_ENTREGA_MIN:
                        max_paquetes = int(t_disponible // TIEMPO_ENTREGA_MIN)
                        paquetes_a_entregar = min(capacidad_restante, demanda_pendiente[vec], max_paquetes)
                        
                        if paquetes_a_entregar > 0:
                            orden_parada += 1
                            t_entregas = paquetes_a_entregar * TIEMPO_ENTREGA_MIN
                            tiempo_ruta_actual += t_viaje_vec + t_entregas
                            capacidad_restante -= paquetes_a_entregar
                            demanda_pendiente[vec] -= paquetes_a_entregar
                            nodo_actual = vec
                            
                            # ➕ Se añade la columna 'Centro_Origen' de forma nativa
                            rutas_generadas.append({
                                'id_camion': id_camion,
                                'orden_parada': orden_parada,
                                'nodo_ine': nodo_actual,
                                'paquetes': paquetes_a_entregar,
                                'km_tramo': dist_km,
                                'tiempo_tramo_min': t_viaje_vec,
                                'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual,
                                'Id_Transportista': id_transportista,
                                'Centro_Origen': nombre_candidato
                            })
                            vecino_visitado = True
                            break 
                            
                if not vecino_visitado:
                    break 
                    
            # REGRESO AL CENTRO DE ÚLTIMA MILLA
            orden_parada += 1
            t_vuelta = tiempos_candidato[nodo_actual]['tiempo_mins']
            km_vuelta = tiempos_candidato[nodo_actual]['distancia_km']
            tiempo_ruta_actual += t_vuelta
            
            # ➕ Se añade la columna 'Centro_Origen' de forma nativa
            rutas_generadas.append({
                'id_camion': id_camion,
                'orden_parada': orden_parada,
                'nodo_ine': f"Regreso_{nombre_candidato}",
                'paquetes': 0,
                'km_tramo': km_vuelta,
                'tiempo_tramo_min': t_vuelta,
                'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual,
                'Id_Transportista': id_transportista,
                'Centro_Origen': nombre_candidato
            })
            
            tiempo_jornada_consumido += tiempo_ruta_actual
            id_camion += 1
            rutas_en_jornada += 1
            
        if rutas_en_jornada == 0:
            break
            
        id_transportista += 1
        
    # Guardar CSV resultado con éxito
    if candidato_valido and rutas_generadas:
        df_resultados = pd.DataFrame(rutas_generadas)
        nombre_salida = nombre_archivo_original.replace("tiempos_", "rutas_optimizadas_")
        ruta_guardado = os.path.join(RUTA_RESULTADOS, nombre_salida)
        df_resultados.to_csv(ruta_guardado, index=False, encoding='utf-8')
        print(f"✅ CSV generado con éxito: {nombre_salida}")
        print(f"   Transportistas: {id_transportista - 1} | Total Rutas: {id_camion - 1}")

print(f"\n📂 Archivos listos en: {os.path.abspath(RUTA_RESULTADOS)}")