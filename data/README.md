# Fuentes de datos

Todos los datos de partida son **abiertos y públicos**. Este directorio contiene únicamente
los ficheros ligeros necesarios para reproducir el análisis; las descargas pesadas se
regeneran ejecutando los scripts indicados.

## Atribución obligatoria

> Datos cartográficos y de infraestructura: **© OpenStreetMap contributors**, disponibles bajo
> [Open Database License (ODbL)](https://www.openstreetmap.org/copyright).
> Los mapas interactivos de `docs/mapas/` usan teselas de OpenStreetMap bajo la misma licencia.

> Datos demográficos y de renta: **Instituto Nacional de Estadística (INE)**.

## Contenido versionado

| Fichero | Contenido | Origen | Generado por |
|---|---|---|---|
| `processed/Datos.xlsx` | 657 secciones censales con `Seccion INE`, `Latitud`, `Longitud`, `Peso` socioeconómico + hojas de población provincial | INE (Padrón, Atlas de Renta, GeoServer WFS) | `src/01_extraccion_secciones_ine.py` |
| `raw/Todas_Coordenadas_Secciones_INE.xlsx` | Centroides de las 46.929 secciones censales de España | INE GeoServer WFS | `src/01_extraccion_secciones_ine.py` |
| `raw/candidatos_poligonos_industriales.csv` | ~500 polígonos industriales/comerciales candidatos tras deduplicación a 500 m | OpenStreetMap vía OSMnx / Overpass | `src/03_generador_candidatos.py` |
| `raw/candidatos_filtrados.csv` | **47 candidatos** que superan los 12 filtros de viabilidad | Derivado | `src/04_filtro_candidatos.py` |
| `raw/candidatos_filtrados_detalle.csv` | Los ~500 candidatos con el motivo de rechazo de cada uno, filtro a filtro | Derivado | `src/04_filtro_candidatos.py` |
| `raw/accesos_autopista_osm.csv` | 1.164 nodos `motorway_junction` de las 4 provincias | OpenStreetMap | `src/03_generador_candidatos.py` |

## No versionado (regenerable)

Se excluyen por tamaño o por ser redescargables desde la fuente original:

- **Atlas de Distribución de Renta de los Hogares (INE)** — ~76 MB.
  Descarga: <https://www.ine.es/dynt3/inebase/es/index.htm?padre=7132>
- **Ficheros `.px` de población provincial** (Sevilla, Huelva, Córdoba, Cádiz) — INEbase.
- **Callejero / base geográfica auxiliar** (`.sql`).

## APIs consultadas en tiempo de ejecución

| API | Uso | Nota |
|---|---|---|
| [OSRM](https://project-osrm.org) (`router.project-osrm.org`) | Matriz de tiempos de conducción reales sobre la red viaria | Instancia pública de demostración. El pipeline hace pausas de 1,5 s entre peticiones y cae a Haversine si falla. **Para reproducir el estudio completo conviene levantar una instancia local**: son ~30.000 consultas. |
| [Overpass / OSMnx](https://overpass-api.de) | Polígonos industriales, espacios protegidos, cauces, usos del suelo, subestaciones | |
| [Open-Elevation](https://api.open-elevation.com) | Pendiente del terreno (filtro F1) | |

Los tiempos ya calculados están cacheados en `outputs/csv/checkpoints_tiempos/`
(48 ficheros, uno por depósito candidato), de modo que **el análisis de rutas y la
comparativa final pueden ejecutarse sin volver a consultar OSRM**.
