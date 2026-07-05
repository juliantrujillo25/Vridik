---
v: 1
tarea: clasificacion_documento
modelo_sugerido: claude-haiku-4-5-20251001
hipotesis: "Clasificacion corta con salida JSON estricta, sin razonamiento libre"
---

Clasifica el siguiente documento de entrada en exactamente una de estas
categorías: "auto_admisorio", "requerimiento", "fallo", "traslado", "otro".

Responde ÚNICAMENTE con un objeto JSON de la forma:
{"categoria": "<una de las categorías>", "confianza": <0.0 a 1.0>}

No agregues texto antes ni después del JSON. Si no puedes determinar la
categoría con confianza razonable, usa "otro" con confianza baja — nunca
inventes una categoría fuera de la lista.
