# Vridik / JuliX — docker/pdf-worker.Dockerfile
# Sprint S10 (roadmap) / railway.json (vridik-pdf-worker): imagen propia con
# LibreOffice headless + fuentes instaladas, para evitar la sustitución
# silenciosa de fuentes que rompe la fidelidad visual de los PDFs generados
# a partir de los documentos del Generador de Vridik.
#
# NO SE CONSTRUYÓ NI SE EJECUTÓ ESTA IMAGEN EN ESTE ENTREGABLE — es el
# Dockerfile de referencia que railway.json apunta como dockerfilePath de
# vridik-pdf-worker.

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# LibreOffice headless + fuentes comunes (Liberation, DejaVu, MS-compatibles
# vía ttf-mscorefonts-installer) — evita que Word/LibreOffice sustituyan
# fuentes en silencio al convertir un .docx a PDF. Sin Redis: la cola de
# trabajos vive en la tabla `pdf_jobs` de PostgreSQL (ver workers/pdf_worker.py),
# no se necesita ningún cliente de Redis en esta imagen.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-calc \
        fonts-liberation \
        fonts-dejavu \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# Perfil de usuario de LibreOffice efímero por conversión (ver roadmap S10:
# "perfil UserInstallation efímero por conversión") — se crea en tiempo de
# ejecución dentro de workers/pdf_worker.py, no aquí en la imagen.
ENV HOME=/tmp/libreoffice-home

CMD ["python3", "workers/pdf_worker.py"]
