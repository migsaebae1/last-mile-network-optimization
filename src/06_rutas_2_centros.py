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
RUTA_CANDIDATOS = os.path.join(BASE_DIR, "data", "raw", "candidatos_filtrados.csv")
DIRECTORIO_CHECKPOINTS = os.path.join(BASE_DIR, "outputs", "csv", "checkpoints_tiempos")
RUTA_RESULTADOS = os.path.join(BASE_DIR, "outputs", "rutas_parejas_generadas")

os.makedirs(RUTA_RESULTADOS, exist_ok=True)

# Restricciones operativas
CAPACIDAD_FURGONETA = 140
JORNADA_MAX_MIN = 480
TIEMPO_CARGA_MIN = 35
TIEMPO_ENTREGA_MIN = 3
VELOCIDAD_MEDIA_KMH = 50.0

# Configuración del Torneo
TOP_CANDIDATOS_POR_ZONA = 5 

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

# ==========================================
# 3. CARGA DE DATOS Y PRE-SEGMENTACIÓN
# ==========================================
print("Cargando y normalizando datos...")
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

# 3.3 Bisección Inicial (Exclusiva para diversificar la búsqueda de candidatos Este/Oeste)
total_demanda = df_nodos_activos['Demanda'].sum()
mitad_demanda = total_demanda / 2.0

rango_lat = df_nodos_activos['Latitud'].max() - df_nodos_activos['Latitud'].min()
rango_lon = df_nodos_activos['Longitud'].max() - df_nodos_activos['Longitud'].min()
eje_corte = 'Longitud' if rango_lon > rango_lat else 'Latitud'

df_nodos_activos = df_nodos_activos.sort_values(eje_corte).reset_index(drop=True)
df_nodos_activos['Demanda_Acumulada'] = df_nodos_activos['Demanda'].cumsum()

df_nodos_activos['Zona'] = np.where(df_nodos_activos['Demanda_Acumulada'] <= mitad_demanda, 0, 1)
mapa_zonas_nodos = df_nodos_activos.set_index('seccion_ine')['Zona'].to_dict()

ultimo_nodo_z0 = df_nodos_activos[df_nodos_activos['Zona'] == 0].iloc[-1]
valor_corte_mapa = ultimo_nodo_z0[eje_corte]

df_candidatos = pd.read_csv(RUTA_CANDIDATOS)
df_candidatos['Zona'] = np.where(df_candidatos[eje_corte] <= valor_corte_mapa, 0, 1)

# ==========================================
# 4. PRE-SELECCIÓN (SCORING) DE CANDIDATOS
# ==========================================
print("\nEvaluando rendimiento de almacenes disponibles...")
patron_busqueda = os.path.join(DIRECTORIO_CHECKPOINTS, "tiempos_*_checkpoint.csv")
archivos_checkpoints = glob.glob(patron_busqueda)

candidatos_evaluados = {'0': [], '1': []}

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

top_z0 = sorted(candidatos_evaluados['0'], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA]
top_z1 = sorted(candidatos_evaluados['1'], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA]

print(f"🏆 Top {TOP_CANDIDATOS_POR_ZONA} Zona 0: {[c['nombre'] for c in top_z0]}")
print(f"🏆 Top {TOP_CANDIDATOS_POR_ZONA} Zona 1: {[c['nombre'] for c in top_z1]}")

# ==========================================
# 5. MOTOR DE GENERACIÓN DE RUTAS
# ==========================================
def generar_rutas_para_centro(candidato, id_zona, id_camion_inicio, id_transp_inicio, mapa_zonas_dinamico):
    df_check = pd.read_csv(candidato['archivo'])
    df_check['seccion_ine'] = df_check['seccion_ine'].astype(str).str.strip()
    tiempos_candidato = df_check.set_index('seccion_ine')[['distancia_km', 'tiempo_mins']].to_dict('index')
    
    # Filtro usando el mapa balanceado concéntrico dinámico recalculado para esta pareja
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
# 6. CRUCE DE PAREJAS Y CLUSTERIZACIÓN DINÁMICA
# ==========================================
print("\nGenerando simulaciones óptimas con Clusterización Balanceada de Parejas (Regret)...")
total_combinaciones = len(top_z0) * len(top_z1)
contador = 1

dict_candidatos_coor = df_candidatos.set_index('Nombre')[['Latitud', 'Longitud']].to_dict('index')

for cand0 in top_z0:
    for cand1 in top_z1:
        nombres_pareja = [cand0['nombre'], cand1['nombre']]
        print(f"🔄 Pareja {contador}/{total_combinaciones}: {nombres_pareja[0]} 🤝 {nombres_pareja[1]}")
        
        # 6.1 Extracción de coordenadas de los 2 almacenes
        coords_centros = {}
        for name in nombres_pareja:
            coords_centros[name] = dict_candidatos_coor.get(name, {'Latitud': df_nodos_activos['Latitud'].mean(), 'Longitud': df_nodos_activos['Longitud'].mean()})
        
        # 6.2 Cálculo del Regret (Pesar)
        total_demanda_global = df_nodos_activos['Demanda'].sum()
        capacidad_maxima_hub = (total_demanda_global / 2.0) * 1.05  # Límite estricto: Mitad de demanda perfecta + 10% tolerancia
        
        datos_matriz_regret = []
        for idx, row in df_nodos_activos.iterrows():
            nodo = row['seccion_ine']
            lat_n, lon_n = row['Latitud'], row['Longitud']
            
            distancias_hubs = {}
            for c_name in nombres_pareja:
                distancias_hubs[c_name] = calcular_haversine(lat_n, lon_n, coords_centros[c_name]['Latitud'], coords_centros[c_name]['Longitud'])
            
            ordenados = sorted(distancias_hubs.items(), key=lambda x: x[1])
            regret_valor = ordenados[1][1] - ordenados[0][1]  # Distancia al lejano menos distancia al cercano
            
            datos_matriz_regret.append({
                'seccion_ine': nodo,
                'Demanda': row['Demanda'],
                'distancias_todas': distancias_hubs,
                'regret': regret_valor
            })
        
        # Ordenamos de mayor a menor regret (los nodos fronterizos más críticos eligen primero)
        df_ejecucion_regret = pd.DataFrame(datos_matriz_regret).sort_values(by='regret', ascending=False)
        
        # 6.3 Asignación espacial balanceada
        carga_hubs = {name: 0 for name in nombres_pareja}
        mapa_zonas_dinamico = {}
        centro_to_zona_id = {name: i for i, name in enumerate(nombres_pareja)}
        
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
                    
            if not asignado:  # Resguardo de seguridad ante saturación por volumen
                c_emergencia = hubs_por_cercania[0][0]
                carga_hubs[c_emergencia] += dem_n
                mapa_zonas_dinamico[nodo] = centro_to_zona_id[c_emergencia]
        
        # 6.4 Ejecución del enrutador por zonas concéntricas balanceadas
        rutas_0, next_camion, next_transp = generar_rutas_para_centro(cand0, id_zona=0, id_camion_inicio=1, id_transp_inicio=1, mapa_zonas_dinamico=mapa_zonas_dinamico)
        rutas_1, _, _ = generar_rutas_para_centro(cand1, id_zona=1, id_camion_inicio=next_camion, id_transp_inicio=next_transp, mapa_zonas_dinamico=mapa_zonas_dinamico)
        
        rutas_totales_pareja = rutas_0 + rutas_1
        
        if rutas_totales_pareja:
            df_resultados = pd.DataFrame(rutas_totales_pareja)
            nombre_salida = f"alianza_pareja_{cand0['nombre']}_y_{cand1['nombre']}.csv"
            df_resultados.to_csv(os.path.join(RUTA_RESULTADOS, nombre_salida), index=False, encoding='utf-8')
            
        contador += 1

print(f"\n🚀 Proceso finalizado. Se han guardado todas las parejas balanceadas en: {os.path.abspath(RUTA_RESULTADOS)}")