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

# Carpeta específica para los quintetos
RUTA_RESULTADOS = os.path.join(BASE_DIR, "outputs", "rutas_quintetos_generados")
os.makedirs(RUTA_RESULTADOS, exist_ok=True)

# Restricciones operativas
CAPACIDAD_FURGONETA = 140
JORNADA_MAX_MIN = 480
TIEMPO_CARGA_MIN = 20
TIEMPO_ENTREGA_MIN = 3
VELOCIDAD_MEDIA_KMH = 50.0

# 3 (3^5 = 243 escenarios).
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

# ==========================================
# 3. CARGA DE DATOS Y PRE-SEGMENTACIÓN (QUINTETOS)
# ==========================================
print("Cargando y normalizando bases de datos...")
df_datos = pd.read_excel(RUTA_DATOS, sheet_name="Dat")
df_datos['Seccion INE'] = df_datos['Seccion INE'].astype(str).str.strip()
coordenadas = df_datos.set_index('Seccion INE')[['Latitud', 'Longitud']].to_dict('index')

# Cargar demanda y calcular la MEDIA anual
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

# 3.3 División Geográfica Inicial en 5 zonas (Quintos)
total_demanda = df_nodos_activos['Demanda'].sum()
quinto_demanda = total_demanda / 5.0
dos_quintos_demanda = quinto_demanda * 2.0
tres_quintos_demanda = quinto_demanda * 3.0
cuatro_quintos_demanda = quinto_demanda * 4.0

rango_lat = df_nodos_activos['Latitud'].max() - df_nodos_activos['Latitud'].min()
rango_lon = df_nodos_activos['Longitud'].max() - df_nodos_activos['Longitud'].min()
eje_corte = 'Longitud' if rango_lon > rango_lat else 'Latitud'

df_nodos_activos = df_nodos_activos.sort_values(eje_corte).reset_index(drop=True)
df_nodos_activos['Demanda_Acumulada'] = df_nodos_activos['Demanda'].cumsum()

condiciones = [
    df_nodos_activos['Demanda_Acumulada'] <= quinto_demanda,
    (df_nodos_activos['Demanda_Acumulada'] > quinto_demanda) & (df_nodos_activos['Demanda_Acumulada'] <= dos_quintos_demanda),
    (df_nodos_activos['Demanda_Acumulada'] > dos_quintos_demanda) & (df_nodos_activos['Demanda_Acumulada'] <= tres_quintos_demanda),
    (df_nodos_activos['Demanda_Acumulada'] > tres_quintos_demanda) & (df_nodos_activos['Demanda_Acumulada'] <= cuatro_quintos_demanda),
    df_nodos_activos['Demanda_Acumulada'] > cuatro_quintos_demanda
]
elecciones = [0, 1, 2, 3, 4]
df_nodos_activos['Zona'] = np.select(condiciones, elecciones, default=4)
mapa_zonas_nodos = df_nodos_activos.set_index('seccion_ine')['Zona'].to_dict()

# 3.4 Clasificar los almacenes físicos en las 5 regiones base
val_corte_1 = df_nodos_activos[df_nodos_activos['Zona'] == 0].iloc[-1][eje_corte]
val_corte_2 = df_nodos_activos[df_nodos_activos['Zona'] == 1].iloc[-1][eje_corte]
val_corte_3 = df_nodos_activos[df_nodos_activos['Zona'] == 2].iloc[-1][eje_corte]
val_corte_4 = df_nodos_activos[df_nodos_activos['Zona'] == 3].iloc[-1][eje_corte]

df_candidatos = pd.read_csv(RUTA_CANDIDATOS)
condiciones_cand = [
    df_candidatos[eje_corte] <= val_corte_1,
    (df_candidatos[eje_corte] > val_corte_1) & (df_candidatos[eje_corte] <= val_corte_2),
    (df_candidatos[eje_corte] > val_corte_2) & (df_candidatos[eje_corte] <= val_corte_3),
    (df_candidatos[eje_corte] > val_corte_3) & (df_candidatos[eje_corte] <= val_corte_4),
    df_candidatos[eje_corte] > val_corte_4
]
df_candidatos['Zona'] = np.select(condiciones_cand, elecciones, default=4)

# ==========================================
# 4. PRE-SELECCIÓN (SCORING) DE CANDIDATOS
# ==========================================
print("Evaluando y puntuando rendimiento de almacenes...")
patron_busqueda = os.path.join(DIRECTORIO_CHECKPOINTS, "tiempos_*_checkpoint.csv")
archivos_checkpoints = glob.glob(patron_busqueda)

# Añadimos la quinta zona
candidatos_evaluados = {'0': [], '1': [], '2': [], '3': [], '4': []}

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
top_z2 = sorted(candidatos_evaluados['2'], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA]
top_z3 = sorted(candidatos_evaluados['3'], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA]
top_z4 = sorted(candidatos_evaluados['4'], key=lambda x: x['score'])[:TOP_CANDIDATOS_POR_ZONA]

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
# 6. CRUCE DE QUINTETOS Y CLUSTERIZACIÓN DINÁMICA
# ==========================================
print("\nGenerando simulaciones optimizadas con Clusterización Balanceada (Regret)...")
total_combinaciones = len(top_z0) * len(top_z1) * len(top_z2) * len(top_z3) * len(top_z4)
contador = 1

dict_candidatos_coor = df_candidatos.set_index('Nombre')[['Latitud', 'Longitud']].to_dict('index')

# 5 bucles anidados
for cand0 in top_z0:
    for cand1 in top_z1:
        for cand2 in top_z2:
            for cand3 in top_z3:
                for cand4 in top_z4:
                    nombres_quinteto = [cand0['nombre'], cand1['nombre'], cand2['nombre'], cand3['nombre'], cand4['nombre']]
                    print(f"🔄 Quinteto {contador}/{total_combinaciones}: {' 🤝 '.join(nombres_quinteto)}")
                    
                    # 6.1 Extracción de coordenadas de los 5 almacenes
                    coords_centros = {}
                    for name in nombres_quinteto:
                        coords_centros[name] = dict_candidatos_coor.get(name, {'Latitud': df_nodos_activos['Latitud'].mean(), 'Longitud': df_nodos_activos['Longitud'].mean()})
                    
                    # 6.2 Cálculo de la capacidad máxima dividiendo por 5.0
                    total_demanda_global = df_nodos_activos['Demanda'].sum()
                    capacidad_maxima_hub = (total_demanda_global / 5.0) * 1.05  # Demanda perfecta + 5% tolerancia
                    
                    datos_matriz_regret = []
                    for idx, row in df_nodos_activos.iterrows():
                        nodo = row['seccion_ine']
                        lat_n, lon_n = row['Latitud'], row['Longitud']
                        
                        distancias_hubs = {}
                        for c_name in nombres_quinteto:
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
                    
                    # 6.3 Asignación de Nodos respetando la capacidad volumétrica
                    carga_hubs = {name: 0 for name in nombres_quinteto}
                    mapa_zonas_dinamico = {}
                    centro_to_zona_id = {name: i for i, name in enumerate(nombres_quinteto)}
                    
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
                            
                    # 6.4 Lanzamiento encadenado para las 5 zonas
                    rutas_0, next_camion, next_transp = generar_rutas_para_centro(cand0, id_zona=0, id_camion_inicio=1, id_transp_inicio=1, mapa_zonas_dinamico=mapa_zonas_dinamico)
                    rutas_1, next_camion_2, next_transp_2 = generar_rutas_para_centro(cand1, id_zona=1, id_camion_inicio=next_camion, id_transp_inicio=next_transp, mapa_zonas_dinamico=mapa_zonas_dinamico)
                    rutas_2, next_camion_3, next_transp_3 = generar_rutas_para_centro(cand2, id_zona=2, id_camion_inicio=next_camion_2, id_transp_inicio=next_transp_2, mapa_zonas_dinamico=mapa_zonas_dinamico)
                    rutas_3, next_camion_4, next_transp_4 = generar_rutas_para_centro(cand3, id_zona=3, id_camion_inicio=next_camion_3, id_transp_inicio=next_transp_3, mapa_zonas_dinamico=mapa_zonas_dinamico)
                    rutas_4, _, _ = generar_rutas_para_centro(cand4, id_zona=4, id_camion_inicio=next_camion_4, id_transp_inicio=next_transp_4, mapa_zonas_dinamico=mapa_zonas_dinamico)
                    
                    rutas_totales_quinteto = rutas_0 + rutas_1 + rutas_2 + rutas_3 + rutas_4
                    
                    if rutas_totales_quinteto:
                        df_resultados = pd.DataFrame(rutas_totales_quinteto)
                        
                        # 📝 FUNCIÓN INTERNA PARA EVITAR EL LÍMITE DE 260 CARACTERES DE WINDOWS
                        def acortar_hub(nombre_largo):
                            return (nombre_largo
                                    .replace("Poligono_Nave_industrial_", "Nave_")
                                    .replace("Poligono_Industrial_", "Ind_")
                                    .replace("Poligono_Almacen_", "Alm_"))
                        
                        # Contraemos los 5 nombres a formatos cortos (Ej: Nave_079, Ind_076...)
                        n0 = acortar_hub(cand0['nombre'])
                        n1 = acortar_hub(cand1['nombre'])
                        n2 = acortar_hub(cand2['nombre'])
                        n3 = acortar_hub(cand3['nombre'])
                        n4 = acortar_hub(cand4['nombre'])
                        
                        # El nombre ahora medirá ~60 caracteres en lugar de 154
                        nombre_salida = f"alianza_quinteto_{n0}_{n1}_{n2}_{n3}_{n4}.csv"
                        df_resultados.to_csv(os.path.join(RUTA_RESULTADOS, nombre_salida), index=False, encoding='utf-8')
                    
                    contador += 1

print(f"\n🚀 ¡Optimización finalizada! Las simulaciones de quintetos se guardaron en: {os.path.abspath(RUTA_RESULTADOS)}")