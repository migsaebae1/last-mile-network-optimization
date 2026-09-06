# `legacy/` — Motor OR-Tools CVRPTW (vía explorada, no consolidada)

> **Este código no produce los resultados del estudio.** Los resultados publicados salen del
> motor *greedy* de [`../src/`](../src/). Esta carpeta se conserva porque documenta una
> alternativa técnica seria que se implementó por completo y se acabó descartando con
> criterio. El razonamiento está en el capítulo 7 de la memoria del proyecto.
<!-- MEMORIA:INICIO — al publicar la memoria, sustituir la linea de arriba (con su ">") por:
> criterio. El razonamiento está en el capítulo 7 de [la memoria](../docs/memoria_proyecto.pdf).
MEMORIA:FIN -->

## Qué hay aquí

| Fichero | Qué hace |
|---|---|
| `vrp_ortools_cvrptw.py` | Resolución del VRP con [OR-Tools](https://developers.google.com/optimization) en modo CVRPTW, con descomposición en zonas, segundo pase GLS y rutas de rescate |
| `analisis_k_optimo.py` | Barrido de K=1..6 comparando el ahorro anual de *routing* contra el coste fijo de cada centro (OPEX + amortización del CAPEX) |
| `postproceso_multitrip.py` | Agrupación de rutas en turnos de conductor mediante *bin packing* LPT, con recarga en depósito |

## Por qué se descartó

El motor OR-Tools es **más fiel a la realidad operativa** —jornada estricta, cobertura
garantizada del 100 % de las secciones— pero resultó **peor en coste** que el greedy de
referencia: 100.720 €/día frente a 48.518 €/día en la alternativa de un solo centro.

La causa no es el solver, es la descomposición. Un CVRP monolítico de 843 nodos y ~400
vehículos es inabordable para OR-Tools en tiempo razonable, así que hubo que trocear el
problema en zonas geográficas de ≤60 nodos y resolver cada una por separado. **Esa
descomposición impide la optimización global**, y con los límites de tiempo por zona que
el proyecto podía permitirse, el resultado no compitió con el baseline.

Con más presupuesto de cómputo y un ajuste fino del *clustering* la conclusión podría
invertirse. Es la línea de mejora número 1 del capítulo 7.

## Detalles de implementación que merece la pena conocer

Tres problemas reales que costó resolver y que pueden ser útiles a quien monte algo parecido:

**1. Colisión de DLLs entre OR-Tools y NumPy en Windows.**
`abseil_dll.dll` de OR-Tools provoca un `WinError 0xc06d007f` a través de una falsa
detección de threadpoolctl 3.x, y NumPy carga una versión de `libprotobuf` anterior a la
que OR-Tools trae empaquetada (`WinError 127`). La solución es un *shim* que precarga los
`.libs/*.dll` con `os.add_dll_directory` + `ctypes.WinDLL` **antes** de importar OR-Tools,
y respetar el orden de importación (OR-Tools primero, NumPy después). También obligó a
sustituir el K-Means de scikit-learn por una implementación equivalente en NumPy puro
(`_kmeans_np`), con soporte de `sample_weight` y `n_init`.

**2. Modelo de tiempo de servicio.**
La matriz de costes debe sumar `round(TIEMPO_ENTREGA_MIN * demanda)` por nodo, **no** una
constante. Una sección censal con 60 paquetes tarda 60 × 3 = 180 min en descargarse, no 3.
Usar la constante plana hacía que las rutas parecieran mucho más cortas de lo real y el
solver empaquetaba demasiadas paradas por ruta.

**3. Disyunciones y rutas de rescate.**
Sin `routing.AddDisjunction([index], penalty)`, un único nodo inalcanzable hace que
OR-Tools devuelva `None` para la zona entera. Con disyunciones el solver descarta ese nodo
y sirve el resto. Para garantizar aun así el 100 % de cobertura, las secciones que quedan
sin servir tras los dos pases reciben una ruta directa dedicada depósito → sección →
depósito, aceptando horas extra en las zonas genuinamente remotas.

## Supuestos

`analisis_k_optimo.py` necesita el coste fijo anual de cada instalación, dato que el caso
de estudio no proporciona. Se emplea una estimación propia a partir de referencias del
sector logístico español:

| Concepto | Referencia | €/año/centro |
|---|---|---|
| Personal (15–20 FTE) | 12 operarios × 25 k€ + 3 supervisores × 30 k€ | ~390.000 |
| Electricidad y suministros | ~500 MWh/año × ~0,13 €/kWh (tarifa industrial) | ~150.000 |
| Mantenimiento de edificio y equipos | ~1 % del CAPEX (6 M€) | ~110.000 |
| Seguros, seguridad, limpieza | Estimación estándar logística | ~80.000 |
| Otros (IT, consumibles, residuos) | Estimación estándar logística | ~70.000 |
| **OPEX total** | | **~800.000** |

Más la amortización del CAPEX a 20 años (6 M€ / 20 = 300.000 €/año), lo que da un coste
fijo de ~1,1 M€/año por centro. Se ajusta con las constantes `OPEX_CENTRO_ANIO` y
`VIDA_UTIL_ANOS`.

## Ejecución

```bash
pip install ortools>=9.8
python legacy/vrp_ortools_cvrptw.py    # ajustar MODO en la cabecera
python legacy/analisis_k_optimo.py
python legacy/postproceso_multitrip.py
```
