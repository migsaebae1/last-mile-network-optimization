# Salida por consola en UTF-8: evita UnicodeEncodeError en terminales
# Windows con codepage heredada (cp1252) al imprimir simbolos o acentos.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import glob
import math
import itertools
import pandas as pd
import numpy as np

# ==========================================
# 1. CONSTANTES Y CONFIGURACIÓN
# ==========================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_DEMANDA = os.path.join(BASE_DIR, "outputs", "xlsx", "Demanda_Amazon_365_Mejorada.xlsx")
RUTA_DATOS = os.path.join(BASE_DIR, "data", "processed", "Datos.xlsx")
RUTA_CANDIDATOS = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
DIRECTORIO_CHECKPOINTS = os.path.join(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")

# Carpeta específica para los octetos
RUTA_RESULTADOS = os.path.join(BASE_DIR, "outputs", "rutas_octetos_generados")
os.makedirs(RUTA_RESULTADOS, exist_ok=True)

# Restricciones operativas
CAPACIDAD_FURGONETA = 140
JORNADA_MAX_MIN = 480
TIEMPO_CARGA_MIN = 12
TIEMPO_ENTREGA_MIN = 3
VELOCIDAD_MEDIA_KMH = 50.0

# ¡CRÍTICO! 3^8 = max 6561 combinaciones óptimas. Súper eficiente y rápido.
TOP_CANDIDATOS_POR_ZONA = 3 

# ==========================================
# 2. FUNCIONES AUXILIARES
# ==========================================
def calcular_haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    a = math.sin((lat2 - lat1)/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1)/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def tiempo_viaje_vecino(km):
    return (km / VELOCIDAD_MEDIA_KMH) * 60.0

def normalizar_texto(texto):
    return str(texto).strip().lower()

def acortar_hub(nombre_largo):
    return (nombre_largo
            .replace("Poligono_Nave_industrial_", "Nave_")
            .replace("Poligono_Industrial_", "Ind_")
            .replace("Poligono_Almacen_", "Alm_"))

# ==========================================
# 3. CARGA DE DATOS Y PRE-SEGMENTACIÓN (OCTETOS)
# ==========================================
print("Cargando y normalizando bases de datos...")
df_datos = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
df_datos['Seccion INE'] = df_datos['Seccion INE'].astype(str).str.strip()
coordenadas = df_datos.set_index('Seccion INE')[['Latitud', 'Longitud']].to_dict('index')

df_demanda = pd.read_excel(RUTA_DEMANDA, index_col=0)
df_demanda.columns = df_demanda.columns.astype(str).str.strip()
demanda_dia_original = np.ceil(df_demanda.mean(axis=0)).astype(int).to_dict()

nodos_activos = []
for nodo, dem in demanda_dia_original.items():
    if dem > 0 and nodo in coordenadas:
        nodos_activos.append({
            'seccion_ine': nodo,
            'Latitud': coordenadas[nodo]['Latitud'],
            'Longitud': coordenadas[nodo]['Longitud'],
            'Demanda': dem
        })

df_nodos_activos = pd.DataFrame(nodos_activos)

# 3.3 División Geográfica Inicial en 8 zonas (Octavos de demanda)
total_demanda = df_nodos_activos['Demanda'].sum()
octavo_demanda = total_demanda / 8.0

rango_lat = df_nodos_activos['Latitud'].max() - df_nodos_activos['Latitud'].min()
rango_lon = df_nodos_activos['Longitud'].max() - df_nodos_activos['Longitud'].min()
eje_corte = 'Longitud' if rango_lon > rango_lat else 'Latitud'

df_nodos_activos = df_nodos_activos.sort_values(eje_corte).reset_index(drop=True)
df_nodos_activos['Demanda_Acumulada'] = df_nodos_activos['Demanda'].cumsum()

# Crear límites dinámicos para los 8 bloques geográficos
condiciones = [df_nodos_activos['Demanda_Acumulada'] <= octavo_demanda]
for i in range(2, 8):
    condiciones.append((df_nodos_activos['Demanda_Acumulada'] > (octavo_demanda * (i-1))) & 
                       (df_nodos_activos['Demanda_Acumulada'] <= (octavo_demanda * i)))
condiciones.append(df_nodos_activos['Demanda_Acumulada'] > (octavo_demanda * 7))

elecciones = list(range(8))
df_nodos_activos['Zona'] = np.select(condiciones, elecciones, default=7)
mapa_zonas_nodos = df_nodos_activos.set_index('seccion_ine')['Zona'].to_dict()

# 3.4 Clasificar los almacenes candidatos en las 8 regiones base
cortes_valores = [df_nodos_activos[df_nodos_activos['Zona'] == idx].iloc[-1][eje_corte] for idx in range(7)]

df_candidatos = pd.read_csv(RUTA_CANDIDATOS)
condiciones_cand = [df_candidatos[eje_corte] <= cortes_valores[0]]
for i in range(1, 7):
    condiciones_cand.append((df_candidatos[eje_corte] > cortes_valores[i-1]) & (df_candidatos[eje_corte] <= cortes_valores[i]))
condiciones_cand.append(df_candidatos[eje_corte] > cortes_valores[6])

df_candidatos['Zona'] = np.select(condiciones_cand, elecciones, default=7)

# ==========================================
# 4. PRE-SELECCIÓN (SCORING) DE CANDIDATOS
# ==========================================
print("Evaluando y puntuando rendimiento de almacenes...")
patron_busqueda = os.path.join(DIRECTORIO_CHECKPOINTS, "tiempos_*_checkpoint.csv")
archivos_checkpoints = glob.glob(patron_busqueda)

candidatos_evaluados = {str(i): [] for i in range(8)}

for archivo_check in archivos_checkpoints:
    nombre_archivo_original = os.path.basename(archivo_check)
    nombre_candidato = nombre_archivo_original.replace("tiempos_", "").replace("_checkpoint.csv", "")
    
    match_candidato = df_candidatos[df_candidatos['Nombre'].apply(normalizar_texto) == normalizar_texto(nombre_candidato)]
    if match_candidato.empty: continue
        
    zona_candidato = str(match_candidato.iloc[0]['Zona'])
    df_check = pd.read_csv(archivo_check)
    df_check['seccion_ine'] = df_check['seccion_ine'].astype(str).str.strip()
    tiempos = df_check.set_index('seccion_ine')['tiempo_mins'].to_dict()
    
    es_viable = True
    score_tiempo_total = 0
    
    for nodo, zona_nodo in mapa_zonas_nodos.items():
        if str(zona_nodo) == zona_candidato:
            if nodo not in tiempos:
                es_viable = False; break
            t_ida = tiempos[nodo]
            t_minimo = TIEMPO_CARGA_MIN + (t_ida * 2) + TIEMPO_ENTREGA_MIN
            if t_minimo > JORNADA_MAX_MIN:
                es_viable = False; break
            score_tiempo_total += t_ida 
            
    if es_viable:
        candidatos_evaluados[zona_candidato].append({
            'nombre': nombre_candidato,
            'archivo': archivo_check,
            'score': score_tiempo_total
        })

# Extraer el TOP 2 para cada una de las 8 regiones
tops_zonas = [sorted(candidatos_evaluados[str(i)], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA] for i in range(8)]

# ==========================================
# 5. MOTOR DE GENERACIÓN DE RUTAS
# ==========================================
def generar_rutas_para_centro(candidato, id_zona, id_camion_inicio, id_transp_inicio, mapa_zonas_dinamico):
    df_check = pd.read_csv(candidato['archivo'])
    df_check['seccion_ine'] = df_check['seccion_ine'].astype(str).str.strip()
    tiempos_candidato = df_check.set_index('seccion_ine')[['distancia_km', 'tiempo_mins']].to_dict('index')
    
    demanda_pendiente = {
        nodo: dem for nodo, dem in demanda_dia_original.items() 
        if dem > 0 and nodo in tiempos_candidato and nodo in coordenadas and mapa_zonas_dinamico.get(nodo, -1) == id_zona
    }
    
    rutas_generadas = []
    id_camion = id_camion_inicio 
    id_transportista = id_transp_inicio
    
    while sum(demanda_pendiente.values()) > 0:
        tiempo_jornada_consumido = 0
        rutas_en_jornada = 0
        
        while tiempo_jornada_consumido < JORNADA_MAX_MIN and sum(demanda_pendiente.values()) > 0:
            nodo_inicial = None
            paquetes_arranque = 0
            
            for nodo, dem in demanda_pendiente.items():
                if dem <= 0: continue
                t_ida = tiempos_candidato[nodo]['tiempo_mins']
                t_base = TIEMPO_CARGA_MIN + (t_ida * 2)
                t_disponible = JORNADA_MAX_MIN - tiempo_jornada_consumido - t_base
                
                if t_disponible >= TIEMPO_ENTREGA_MIN:
                    paq = min(CAPACIDAD_FURGONETA, dem, int(t_disponible // TIEMPO_ENTREGA_MIN))
                    if paq > 0:
                        nodo_inicial = nodo; paquetes_arranque = paq; break 
            
            if not nodo_inicial: break
                
            orden_parada = 1
            tiempo_ruta_actual = TIEMPO_CARGA_MIN
            capacidad_restante = CAPACIDAD_FURGONETA - paquetes_arranque
            
            rutas_generadas.append({'id_camion': id_camion, 'orden_parada': orden_parada, 'nodo_ine': f"Inicio_{candidato['nombre']}", 'paquetes': 0, 'km_tramo': 0, 'tiempo_tramo_min': TIEMPO_CARGA_MIN, 'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual, 'Id_Transportista': id_transportista, 'Centro_Origen': candidato['nombre'], 'Zona_Geografica': f"Zona_{id_zona}"})
            
            orden_parada += 1
            t_ida, km_ida = tiempos_candidato[nodo_inicial]['tiempo_mins'], tiempos_candidato[nodo_inicial]['distancia_km']
            tiempo_ruta_actual += t_ida + (paquetes_arranque * TIEMPO_ENTREGA_MIN)
            demanda_pendiente[nodo_inicial] -= paquetes_arranque
            nodo_actual = nodo_inicial
            
            rutas_generadas.append({'id_camion': id_camion, 'orden_parada': orden_parada, 'nodo_ine': nodo_actual, 'paquetes': paquetes_arranque, 'km_tramo': km_ida, 'tiempo_tramo_min': t_ida, 'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual, 'Id_Transportista': id_transportista, 'Centro_Origen': candidato['nombre'], 'Zona_Geografica': f"Zona_{id_zona}"})
            
            while capacidad_restante > 0 and sum(demanda_pendiente.values()) > 0:
                vecinos = []
                lat_act, lon_act = coordenadas[nodo_actual]['Latitud'], coordenadas[nodo_actual]['Longitud']
                
                for vec, dem in demanda_pendiente.items():
                    if dem > 0:
                        lat_vec, lon_vec = coordenadas[vec]['Latitud'], coordenadas[vec]['Longitud']
                        vecinos.append((calcular_haversine(lat_act, lon_act, lat_vec, lon_vec), vec))
                
                vecino_visitado = False
                for dist_km, vec in sorted(vecinos):
                    t_viaje_vec = tiempo_viaje_vecino(dist_km)
                    t_regreso = tiempos_candidato[vec]['tiempo_mins']
                    t_disp = JORNADA_MAX_MIN - (tiempo_jornada_consumido + tiempo_ruta_actual + t_viaje_vec + t_regreso)
                    
                    if t_disp >= TIEMPO_ENTREGA_MIN:
                        paq_entregar = min(capacidad_restante, demanda_pendiente[vec], int(t_disp // TIEMPO_ENTREGA_MIN))
                        if paq_entregar > 0:
                            orden_parada += 1
                            tiempo_ruta_actual += t_viaje_vec + (paq_entregar * TIEMPO_ENTREGA_MIN)
                            capacidad_restante -= paq_entregar
                            demanda_pendiente[vec] -= paq_entregar
                            nodo_actual = vec
                            
                            rutas_generadas.append({'id_camion': id_camion, 'orden_parada': orden_parada, 'nodo_ine': nodo_actual, 'paquetes': paq_entregar, 'km_tramo': dist_km, 'tiempo_tramo_min': t_viaje_vec, 'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual, 'Id_Transportista': id_transportista, 'Centro_Origen': candidato['nombre'], 'Zona_Geografica': f"Zona_{id_zona}"})
                            vecino_visitado = True; break 
                            
                if not vecino_visitado: break 
                    
            orden_parada += 1
            t_vuelta, km_vuelta = tiempos_candidato[nodo_actual]['tiempo_mins'], tiempos_candidato[nodo_actual]['distancia_km']
            tiempo_ruta_actual += t_vuelta
            rutas_generadas.append({'id_camion': id_camion, 'orden_parada': orden_parada, 'nodo_ine': f"Regreso_{candidato['nombre']}", 'paquetes': 0, 'km_tramo': km_vuelta, 'tiempo_tramo_min': t_vuelta, 'tiempo_acumulado_min': tiempo_jornada_consumido + tiempo_ruta_actual, 'Id_Transportista': id_transportista, 'Centro_Origen': candidato['nombre'], 'Zona_Geografica': f"Zona_{id_zona}"})
            
            tiempo_jornada_consumido += tiempo_ruta_actual
            id_camion += 1
            rutas_en_jornada += 1
            
        if rutas_en_jornada == 0: break
        id_transportista += 1
        
    return rutas_generadas, id_camion, id_transportista

# ==========================================
# 6. CRUCE DE OCTETOS Y CLUSTERIZACIÓN DINÁMICA
# ==========================================
print("\nGenerando simulaciones optimizadas con Clusterización Balanceada (Regret)...")
dict_candidatos_coor = df_candidatos.set_index('Nombre')[['Latitud', 'Longitud']].to_dict('index')

# Generamos las combinaciones cruzadas de las 8 zonas usando itertools
todas_combinaciones = list(itertools.product(*tops_zonas))
total_combinaciones = len(todas_combinaciones)
contador = 1

for combo in todas_combinaciones:
    nombres_octeto = [c['nombre'] for c in combo]
    print(f"🔄 Octeto {contador}/{total_combinaciones}: {' 🤝 '.join([acortar_hub(n) for n in nombres_octeto])}")
    
    # 6.1 Coordenadas de los 8 almacenes
    coords_centros = {}
    for name in nombres_octeto:
        coords_centros[name] = dict_candidatos_coor.get(name, {'Latitud': df_nodos_activos['Latitud'].mean(), 'Longitud': df_nodos_activos['Longitud'].mean()})
    
    # 6.2 Capacidad máxima: un octavo de la demanda total (12.5%) + 5% margen de balanceo
    total_demanda_global = df_nodos_activos['Demanda'].sum()
    capacidad_maxima_hub = (total_demanda_global / 8.0) * 1.05  
    
    datos_matriz_regret = []
    for idx, row in df_nodos_activos.iterrows():
        nodo = row['seccion_ine']
        lat_n, lon_n = row['Latitud'], row['Longitud']
        
        distancias_hubs = {}
        for c_name in nombres_octeto:
            distancias_hubs[c_name] = calcular_haversine(lat_n, lon_n, coords_centros[c_name]['Latitud'], coords_centros[c_name]['Longitud'])
        
        ordenados = sorted(distancias_hubs.items(), key=lambda x: x[1])
        regret_valor = ordenados[1][1] - ordenados[0][1] 
        
        datos_matriz_regret.append({
            'seccion_ine': nodo,
            'Demanda': row['Demanda'],
            'distancias_todas': distancias_hubs,
            'regret': regret_valor
        })
    
    df_ejecucion_regret = pd.DataFrame(datos_matriz_regret).sort_values(by='regret', ascending=False)
    
    # 6.3 Asignación por Regret
    carga_hubs = {name: 0 for name in nombres_octeto}
    mapa_zonas_dinamico = {}
    centro_to_zona_id = {name: i for i, name in enumerate(nombres_octeto)}
    
    for idx, row in df_ejecucion_regret.iterrows():
        nodo = row['seccion_ine']
        dem_n = row['Demanda']
        hubs_por_cercania = sorted(row['distancias_todas'].items(), key=lambda x: x[1])
        
        asignado = False
        for c_cand, dist_km in hubs_por_cercania:
            if carga_hubs[c_cand] + dem_n <= capacidad_maxima_hub:
                carga_hubs[c_cand] += dem_n
                mapa_zonas_dinamico[nodo] = centro_to_zona_id[c_cand]
                asignado = True
                break
                
        if not asignado: 
            c_emergencia = hubs_por_cercania[0][0]
            carga_hubs[c_emergencia] += dem_n
            mapa_zonas_dinamico[nodo] = centro_to_zona_id[c_emergencia]
    
    # 6.4 Lanzamiento secuencial del enrutador para las 8 bases
    rutas_acumuladas = []
    curr_camion = 1
    curr_transp = 1
    
    for i, cand in enumerate(combo):
        rutas_c, curr_camion, curr_transp = generar_rutas_para_centro(
            cand, id_zona=i, id_camion_inicio=curr_camion, id_transp_inicio=curr_transp, mapa_zonas_dinamico=mapa_zonas_dinamico
        )
        rutas_acumuladas.extend(rutas_c)
        
    if rutas_acumuladas:
        df_resultados = pd.DataFrame(rutas_acumuladas)
        
        # Nombres ultra acortados para saltar el bloqueo de Windows (MAX_PATH)
        n_cortos = [acortar_hub(c['nombre']) for c in combo]
        nombre_salida = f"alianza_octeto_{'_'.join(n_cortos)}.csv"
        
        df_resultados.to_csv(os.path.join(RUTA_RESULTADOS, nombre_salida), index=False, encoding='utf-8')
    
    contador += 1

print(f"\n🚀 ¡Optimización finalizada! Las simulaciones de 8 centros se guardaron en: {os.path.abspath(RUTA_RESULTADOS)}")
