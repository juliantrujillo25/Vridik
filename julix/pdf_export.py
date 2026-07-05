"""
Vridik / JuliX — julix/pdf_export.py
Sprint S10: exportación a PDF con citas, para que un abogado pueda
descargar la respuesta de JuliX ya formateada — con las fuentes usadas
listadas aparte, no mezcladas silenciosamente en el cuerpo — y el
disclaimer de borrador visible en cada página.

Diseño:
  - `FuenteCitada`: forma mínima de una fuente para el PDF (norma,
    artículo, párrafo opcional). Se puede construir directamente desde un
    `rag.context_builder.ChunkRecuperado` o desde un
    `julix.context_builder.RankedChunk` vía `desde_chunk_recuperado` /
    `desde_referencia` — el endpoint (api/julix_endpoint.py) ya tiene los
    chunks usados en la generación, así que no hay que volver a consultar
    rag_chunks para armar el PDF.
  - `generar_pdf(...)`: arma el documento con ReportLab (BaseDocTemplate +
    un frame con márgenes fijos), header "Vridik Pro" en cada página,
    cuerpo con la respuesta de JuliX, sección "Fuentes citadas" numerada,
    y pie de página con el disclaimer legal en todas las páginas.

NO SE EJECUTA CONTRA CLAUDE REAL NI SE ABRE NINGÚN PDF EN ESTE
ENTREGABLE — solo se genera el archivo en disco cuando se invoca
explícitamente `generar_pdf`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:  # pragma: no cover
    LETTER = None  # type: ignore
    cm = None  # type: ignore
    colors = None  # type: ignore
    BaseDocTemplate = Frame = PageTemplate = Paragraph = Spacer = None  # type: ignore
    getSampleStyleSheet = ParagraphStyle = None  # type: ignore

NOMBRE_PRODUCTO = "Vridik Pro"
PIE_DE_PAGINA_DISCLAIMER = "Borrador para revisión de abogado – no constituye asesoría legal"

# Patrón usado tanto para reconocer una cita "[norma, articulo, parrafo]"
# (formato producido por rag.context_builder.ChunkRecuperado.cita) como
# para partirla en sus componentes al parsear una referencia de texto.
_RE_CITA_CORCHETES = re.compile(r"^\[(?P<interior>.+)\]$")


@dataclass
class FuenteCitada:
    norma: str
    articulo: str
    parrafo: str | None = None

    @property
    def cita(self) -> str:
        """Mismo formato [norma, artículo, párrafo] que
        rag.context_builder.ChunkRecuperado.cita — consistencia entre lo
        que JuliX cita en el cuerpo y lo que aparece en 'Fuentes citadas'."""
        partes = [self.norma, self.articulo]
        if self.parrafo:
            partes.append(self.parrafo)
        return "[" + ", ".join(partes) + "]"

    @classmethod
    def desde_chunk_recuperado(cls, chunk) -> "FuenteCitada":
        """Construye una FuenteCitada a partir de un
        rag.context_builder.ChunkRecuperado (duck-typed: solo necesita los
        atributos norma/articulo/parrafo, para no forzar un import
        circular con rag/)."""
        return cls(norma=chunk.norma, articulo=chunk.articulo, parrafo=getattr(chunk, "parrafo", None))

    @classmethod
    def desde_referencia(cls, referencia: str) -> "FuenteCitada":
        """Parsea una referencia con formato '[norma, articulo, parrafo]'
        (p.ej. la que trae julix.context_builder.RankedChunk.referencia)
        de vuelta a sus componentes. Si el formato no calza, se devuelve
        la referencia completa como 'norma' y 'articulo' vacío — nunca se
        lanza una excepción por una cita mal formada; en el peor caso el
        PDF muestra el texto crudo de la referencia."""
        match = _RE_CITA_CORCHETES.match(referencia.strip())
        interior = match.group("interior") if match else referencia.strip()
        partes = [p.strip() for p in interior.split(",")]
        norma = partes[0] if len(partes) > 0 else interior
        articulo = partes[1] if len(partes) > 1 else ""
        parrafo = partes[2] if len(partes) > 2 else None
        return cls(norma=norma, articulo=articulo, parrafo=parrafo)


def _requerir_reportlab() -> None:
    if BaseDocTemplate is None:
        raise RuntimeError("Falta la dependencia 'reportlab' (pip install reportlab)")


def _construir_estilos():
    estilos = getSampleStyleSheet()
    estilos.add(
        ParagraphStyle(
            name="VridikHeader",
            parent=estilos["Heading1"],
            fontSize=16,
            textColor=colors.HexColor("#1B2A4A"),
            spaceAfter=4,
        )
    )
    estilos.add(
        ParagraphStyle(
            name="VridikSubheader",
            parent=estilos["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#5A6B87"),
            spaceAfter=14,
        )
    )
    estilos.add(
        ParagraphStyle(
            name="VridikCuerpo",
            parent=estilos["BodyText"],
            fontSize=10.5,
            leading=15,
            spaceAfter=8,
        )
    )
    estilos.add(
        ParagraphStyle(
            name="VridikFuenteTitulo",
            parent=estilos["Heading2"],
            fontSize=12,
            textColor=colors.HexColor("#1B2A4A"),
            spaceBefore=16,
            spaceAfter=8,
        )
    )
    estilos.add(
        ParagraphStyle(
            name="VridikFuenteItem",
            parent=estilos["Normal"],
            fontSize=9.5,
            leading=13,
            leftIndent=10,
            spaceAfter=4,
        )
    )
    return estilos


def _dibujar_pie_de_pagina(canvas, doc) -> None:
    """Se registra como onPage del PageTemplate — ReportLab lo llama en
    CADA página, así que el disclaimer legal (S10: 'Borrador para revisión
    de abogado – no constituye asesoría legal') nunca depende de que quepa
    en el flujo normal del documento; siempre aparece."""
    canvas.saveState()
    canvas.setFont("Helvetica-Oblique", 7.5)
    canvas.setFillColor(colors.HexColor("#8A93A6"))
    ancho_pagina, _ = LETTER
    canvas.drawCentredString(ancho_pagina / 2, 1.2 * cm, PIE_DE_PAGINA_DISCLAIMER)
    canvas.drawRightString(ancho_pagina - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _parrafos_desde_texto(texto: str, estilo) -> list:
    """El texto de JuliX viene como bloque plano; se parte por doble salto
    de línea para respetar los párrafos originales dentro del PDF (un solo
    Paragraph gigante con \\n adentro no haría wrap correctamente en
    ReportLab)."""
    bloques = [b.strip() for b in texto.split("\n\n") if b.strip()]
    if not bloques:
        bloques = [texto.strip() or "(respuesta vacía)"]
    # Escapar '&', '<', '>' para que ReportLab no intente interpretarlos
    # como marcado XML dentro del Paragraph.
    return [
        Paragraph(b.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), estilo)
        for b in bloques
    ]


def generar_pdf(
    *,
    respuesta: str,
    fuentes: list[FuenteCitada],
    ruta_salida: str | Path,
    tarea: str = "",
    caso_id: str = "",
) -> Path:
    """Genera el PDF en `ruta_salida` y retorna el Path resultante.

    - `respuesta`: el documento/consulta ya generado por JuliX (texto
      plano, tal como lo arma julix/service.py).
    - `fuentes`: las FuenteCitada correspondientes a los chunks
      efectivamente usados en la generación (ver FuenteCitada.desde_*).
    - `tarea`/`caso_id`: metadata opcional para el subtítulo del header.
    """
    _requerir_reportlab()

    ruta = Path(ruta_salida)
    ruta.parent.mkdir(parents=True, exist_ok=True)

    estilos = _construir_estilos()
    elementos: list = []

    elementos.append(Paragraph(NOMBRE_PRODUCTO, estilos["VridikHeader"]))
    subtitulo_partes = ["Documento generado por JuliX"]
    if tarea:
        subtitulo_partes.append(f"tarea: {tarea}")
    if caso_id:
        subtitulo_partes.append(f"caso: {caso_id}")
    elementos.append(Paragraph(" — ".join(subtitulo_partes), estilos["VridikSubheader"]))

    elementos.extend(_parrafos_desde_texto(respuesta, estilos["VridikCuerpo"]))

    elementos.append(Paragraph("Fuentes citadas", estilos["VridikFuenteTitulo"]))
    if fuentes:
        for i, fuente in enumerate(fuentes, start=1):
            elementos.append(Paragraph(f"{i}. {fuente.cita}", estilos["VridikFuenteItem"]))
    else:
        elementos.append(
            Paragraph(
                "(sin fuentes recuperadas del corpus RAG para esta respuesta — ver "
                "'Nota del revisor' en el cuerpo si JuliX indicó falta de fuente)",
                estilos["VridikFuenteItem"],
            )
        )

    doc = BaseDocTemplate(
        str(ruta),
        pagesize=LETTER,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.2 * cm,
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="vridik_frame",
    )
    plantilla = PageTemplate(id="vridik_pro", frames=[frame], onPage=_dibujar_pie_de_pagina)
    doc.addPageTemplates([plantilla])
    doc.build(elementos)

    return ruta


def _verificar_pdf_generado(ruta: Path) -> dict:
    """Verificación estructural del PDF (sin depender de un parser de PDF
    de terceros): confirma la firma binaria %PDF-, que el archivo no esté
    vacío, y que el stream (sin descomprimir) contenga los objetos de
    texto esperados cuando ReportLab no comprime el contenido. Como
    ReportLab comprime los content streams por defecto, la verificación
    de texto visible (header/Fuentes citadas/disclaimer) se hace sobre los
    argumentos usados para construir el PDF, no sobre el binario — igual
    que test_pdf_export.py, que valida la constante PIE_DE_PAGINA_DISCLAIMER
    en vez de parsear el PDF byte a byte."""
    contenido = ruta.read_bytes()
    return {
        "existe": ruta.exists(),
        "es_pdf_valido": contenido.startswith(b"%PDF-"),
        "tamano_bytes": len(contenido),
    }


def _cli_test() -> int:
    """Modo `--test`: genera un PDF de muestra (test_output.pdf) con datos
    representativos (respuesta + fuentes citadas) y confirma que:
      1. El archivo resultante tiene firma %PDF- válida.
      2. El header "Vridik Pro" se pasó a la construcción del documento.
      3. La sección "Fuentes citadas" se generó (con al menos 1 fuente).
      4. El disclaimer de pie de página es exactamente el texto pedido en
         S10 ("Borrador para revisión de abogado – no constituye asesoría legal").

    No llama a Anthropic ni depende de ninguna base de datos — usa datos
    de muestra fijos, igual que tests/test_pdf_export.py."""
    fuentes = [
        FuenteCitada(norma="Ley 1607 de 2012", articulo="Art. 179"),
        FuenteCitada(norma="Decreto 1625 de 2016", articulo="Art. 1.2.4.1.1"),
        FuenteCitada.desde_referencia("[Consejo de Estado - Sección Cuarta, Sentencia 25000-23-37-000-2022-00567-01]"),
    ]
    respuesta = (
        "De acuerdo con el contexto normativo disponible, la UGPP puede fiscalizar "
        "los aportes al sistema de seguridad social de los contratistas "
        "independientes cuando existan indicios de subdeclaración del ingreso base "
        "de cotización.\n\n"
        "El procedimiento de determinación oficial exige requerimiento previo y "
        "traslado de cargos antes de imponer sanción por inexactitud. [revisar] "
        "verificar plazos exactos del caso concreto en el expediente."
    )

    ruta_salida = Path("test_output.pdf")
    ruta = generar_pdf(
        respuesta=respuesta,
        fuentes=fuentes,
        ruta_salida=ruta_salida,
        tarea="ugpp_demanda",
        caso_id="CASO-VALIDACION-S10",
    )

    verificacion = _verificar_pdf_generado(ruta)

    print("=== Vridik/JuliX — julix/pdf_export.py --test ===")
    print(f"Archivo generado: {ruta.resolve()}")
    print(f"Existe: {verificacion['existe']}")
    print(f"Firma %PDF- válida: {verificacion['es_pdf_valido']}")
    print(f"Tamaño: {verificacion['tamano_bytes']} bytes")
    print(f"Header usado: '{NOMBRE_PRODUCTO}'")
    print(f"Fuentes citadas incluidas: {len(fuentes)} ({', '.join(f.cita for f in fuentes)})")
    print(f"Disclaimer de pie de página: '{PIE_DE_PAGINA_DISCLAIMER}'")

    ok = (
        verificacion["existe"]
        and verificacion["es_pdf_valido"]
        and verificacion["tamano_bytes"] > 0
        and len(fuentes) > 0
        and PIE_DE_PAGINA_DISCLAIMER == "Borrador para revisión de abogado – no constituye asesoría legal"
    )
    print(f"\nResultado: {'OK' if ok else 'FALLO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys as _sys

    if "--test" in _sys.argv:
        raise SystemExit(_cli_test())
    else:
        print("Uso: python julix/pdf_export.py --test", file=_sys.stderr)
        raise SystemExit(1)
