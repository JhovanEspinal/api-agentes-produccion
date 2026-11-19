# Capturas del dashboard

**Esta carpeta todavía no tiene capturas.** Solo pueden salir de una ejecución real con Redis, una clave de LLM y LangSmith, y esa ejecución aún no se ha hecho. No se agregan imágenes simuladas.

Capturas que pide la entrega y cómo obtenerlas, siguiendo los pasos del README principal:

| Archivo esperado | Qué debe mostrar | Dónde se ve en LangSmith |
|---|---|---|
| `01_trazas.png` | Lista de trazas `job_orquestador` de la corrida, con los nodos del grafo anidados | Proyecto `api-agentes-produccion`, pestaña de trazas |
| `02_traza_detalle.png` | Una traza abierta con supervisor, researcher, analyst, validator y synthesizer, y sus tokens | Clic en una traza |
| `03_costo_por_ejecucion.png` | Costo de cada una de las 5 ejecuciones, calculado por la plataforma a partir de los tokens | Columna de costo en la lista de trazas, o el panel de monitoreo |
| `04_latencia_p95.png` | Latencia p95 de la corrida de 5 peticiones concurrentes | Panel de monitoreo del proyecto; si no aparece p95, crear un gráfico de latencia con ese percentil |
| `05_hitl.png` | Una traza detenida en `human_approval` y su reanudación tras la aprobación | Traza de un trabajo con `"publicar": true` |

Los nombres de las secciones de la interfaz de LangSmith pueden variar según su versión.
