FROM python:3.12-slim

# System-Tools für OCR/Dokumente (wie im Install-Skript)
RUN apt-get update -qq && apt-get install -y -q --no-install-recommends \
        poppler-utils tesseract-ocr tesseract-ocr-deu libreoffice-core \
        libreoffice-writer libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY feeagent ./feeagent
COPY web ./web
COPY subagents ./subagents
COPY run.sh .

ENV FEE_AGENT_PORT=8765 \
    FEE_MANDATE_DIR=/data/mandate
# Mandatsdaten + DB liegen im Volume /data – nicht in der Cloud, nicht im Container
VOLUME ["/data"]
EXPOSE 8765

CMD ["python", "-m", "feeagent.server"]
