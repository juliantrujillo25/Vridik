# Perfil de estilo — Ana Luisa (socia UGPP)

Generado por `scripts/build_ana_profile.py` a partir de una muestra determinística de 200 conversaciones del export real de ChatGPT (`~/Desktop/ChatGPT`), filtradas por menciones a "UGPP"/"Ana"/"pensión". Corrida autorizada explícitamente por el dev lead (dato personal sensible) — ver nota pendiente en `julix/prompt_v3.txt`.

**Privacidad:** este perfil contiene solo patrones agregados de estilo y temas por categoría amplia. Ningún número de cédula, NIT, tarjeta profesional, radicado de proceso o nombre de cliente/contraparte distinto de Ana Luisa se incluye aquí — se redactaron automáticamente si aparecían cerca de los fragmentos ilustrativos. El export crudo no se subió a ningún lado ni se envió a Anthropic; este script corre 100% local.

- Conversaciones en la muestra: **200**
- Conversaciones con menciones a UGPP/Ana/pensión: **99** (50% de la muestra)

## Temas frecuentes (categorías amplias, no casos individuales)

- UGPP / seguridad social: 79 conversaciones (80%)
- Derecho laboral: 56 conversaciones (57%)
- Contratos y documentos corporativos: 47 conversaciones (47%)
- Actos administrativos / litigio: 25 conversaciones (25%)

## Validación de la hipótesis de estilo (julix/prompt_v3.txt)

La hipótesis fija actualmente en `julix/prompt_v3.txt` es: *"primero 3 bullets accionables, luego explicación simple, evita tecnicismos DIAN a menos que los definas, usa ejemplo numérico siempre"*. Evidencia observada en la muestra (sobre las conversaciones que sí mencionan UGPP/Ana/pensión):

- Mensajes de Ana Luisa pidiendo explicación **simple/sin tecnicismos**: 0 (0%)
- Mensajes de Ana Luisa **rechazando o pidiendo definir jerga**: 5 (5%)
- Mensajes de Ana Luisa pidiendo explícitamente **bullets/puntos**: 0 (0%)
- Respuestas del asistente que **empiezan con ≥3 bullets**: 72 (73%)
- Respuestas del asistente con **ejemplo numérico**: 67 (68%)

**Ejemplos ilustrativos (redactados, truncados) — rechaza/pide definir jerga:**
  - "…de cujus que significa…"
  - "…MFCL qué significa esta sigla?…"
  - "…comunicación con efecto suspensivo, lo que significa que no producirá efectos jurídicos defi…"

## Recomendación para julix/prompt_v3.txt

- La muestra no da señal fuerte en ninguna dirección — mantener el texto actual de prompt_v3.txt sin cambios hasta tener más evidencia.
