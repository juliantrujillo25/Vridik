"""
Vridik — procesal/
Fase 2 (Copiloto Procesal, Q4-2026): evento judicial → clasificación IA →
término calculado → borrador JuliX. Arranca sin proveedor de monitoreo de
procesos contratado (decisión de negocio pendiente, ver vridik_roadmap.md
"Fase 2" -- "decisión temprana build-vs-integrate") -- lo que sí es
independiente de esa decisión se construye acá primero:

  - `clasificador_actuaciones.py`: clasificación IA de una actuación ya
    en texto (auto_admisorio/requerimiento/fallo/traslado/otro) sobre
    Haiku, reusando julix/client.py -- no depende de CÓMO llegó el texto
    de la actuación, solo de que ya esté en texto.
  - `calendario_judicial.py`: motor de cálculo de términos procesales
    (días hábiles) sobre el calendario judicial colombiano real
    (festivos + vacancia judicial) -- tampoco depende de un feed de
    actuaciones en vivo, solo de una fecha de inicio y una cantidad de
    días.

La ingesta de actuaciones en sí (conectar contra un proveedor real o
scraping propio) y el borrador automático vía JuliX con el expediente
completo del caso quedan para cuando se resuelva esa decisión de negocio.
"""
