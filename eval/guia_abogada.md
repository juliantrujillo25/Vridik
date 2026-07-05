# Vridik — Guía para Ana Luisa: Banco de Evaluación de JuliX (Sprint S5)

**Archivo a llenar:** `banco_casos_vridik.xlsx`, columna **`respuesta_esperada`** (resaltada en amarillo). **Tiempo estimado: 90 minutos.** No toques ninguna otra columna.

## Qué es esto y por qué importa

JuliX (el redactor de IA de Vridik) va a responder estos mismos 20 casos por su cuenta. Un "Claude juez" comparará su respuesta contra la tuya. Si JuliX acierta en al menos 8 de cada 10 casos sin inventarse ninguna norma, pasa el filtro de calidad (el "Gate") y seguimos adelante con el proyecto. Si no, hay que ajustar antes de mostrárselo a nadie más. Tu respuesta es la vara con la que se mide todo esto — por eso tiene que ser la que tú realmente darías en el despacho, no una versión "perfecta de manual".

## Cómo llenar cada fila

1. Lee la columna `pregunta` como si te la hiciera un cliente o un abogado junior.
2. Escribe en `respuesta_esperada` la respuesta que tú le darías **en la práctica real del despacho** — con la misma extensión y nivel de detalle que usarías normalmente. No hace falta redactar un memorando completo; 3-6 frases claras con la conclusión y el fundamento bastan.
3. Cita la norma que uses, aunque ya esté sugerida en la columna `norma_clave` — confírmala o corrígela si crees que aplica otra.
4. Si un caso tiene información insuficiente para responder con certeza, dilo explícitamente en tu respuesta (así lo haría un abogado responsable, y así debe evaluarse a JuliX también).
5. No necesitas hacerlos en orden ni en una sola sesión. Guarda el archivo cuando termines cada tanda.

## Calificar a ciegas (importante)

Cuando llegue el momento de calificar las respuestas de JuliX (eso lo coordina el equipo técnico, no tú sola): las vas a ver **sin saber cuál caso es cuál en términos de "fácil" o "difícil"**, y sin ver tu propia respuesta al lado hasta el final, para no sesgarte. Simplemente compara lo que JuliX escribió contra lo que tú esperarías, con la misma exigencia que tendrías con un abogado junior del despacho. No hay respuesta "correcta única" — hay respuestas jurídicamente sólidas y respuestas que no lo son.

## Qué NO hacer

- No investigues jurisprudencia nueva para esto — usa tu criterio actual, el mismo que aplicarías hoy en una consulta real.
- No le muestres el archivo a JuliX ni lo uses como referencia para nada más hasta que el equipo confirme que la corrida terminó.
- No cambies la columna `id`, `área`, `pregunta`, `norma_clave` ni `dificultad` — el sistema los usa para procesar el archivo automáticamente.

## Si algo no te queda claro

Marca la celda con un comentario de Excel (clic derecho → Insertar comentario) explicando la duda, y sigue con el siguiente caso. No te detengas por un caso difícil — la meta es completar los 20 en la sesión de 90 minutos.

## Checklist final (5 minutos, antes de avisar que ya terminaste)

Revisa esto una sola vez, al final, sobre las 20 filas completas:

- [ ] Las 20 filas de `respuesta_esperada` tienen texto (ninguna quedó vacía ni con un simple "N/A" sin explicación).
- [ ] Cada respuesta cita al menos una norma (la de `norma_clave` u otra si corregiste).
- [ ] En los casos donde señalaste un vacío de información, quedó explícito en el texto (no solo en tu cabeza).
- [ ] No modificaste `id`, `área`, `pregunta`, `norma_clave` ni `dificultad` en ninguna fila.
- [ ] Guardaste el archivo en formato `.xlsx` (no lo exportaste a PDF ni a Word).
- [ ] Le avisaste al equipo técnico que ya terminaste (para que arranquen la corrida de JuliX).

Si todo lo anterior está en orden, ya cumpliste tu parte — el resto de la evaluación corre sola.
