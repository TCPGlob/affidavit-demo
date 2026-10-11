# Container image for the document preparation pipeline.
#
# The pipeline turns a folder of mixed documents into numbered PDF bundles for
# Zibbit. It never needs an outbound internet connection.
#
# ---------------------------------------------------------------------------
# CLIENT DEMO (synthetic data, no sign-in). Anyone with the URL can reach it, so
# never put real client material here.
#
#   docker build -t aod .
#   docker run -d --name aod-demo -p 8080:8765 aod \
#     python pipeline.py --root /data review --demo \
#     --host 0.0.0.0 --port 8765 --no-browser
#
# ---------------------------------------------------------------------------
# REAL USE. Create accounts, require sign-in, keep it on a private network, and
# put TLS in front.
#
#   docker run --rm -v aod-data:/data aod \
#     python pipeline.py --root /data create-user \
#     --username you --name "Your Name" --role admin
#
#   docker run -d --name aod -p 127.0.0.1:8765:8765 -v aod-data:/data aod
#
# The default CMD below is the safe one: sign-in required, Secure cookie.

FROM python:3.12-slim

# Tesseract for OCR of scanned documents; LibreOffice for DOCX/XLSX/PPTX.
# Both are optional at runtime - the pipeline degrades gracefully without them -
# but a document pipeline should not be missing either.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libreoffice-writer \
        libreoffice-calc \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyMuPDF for PDF read/write, Pillow for images, openpyxl for the XLSX index.
RUN pip install --no-cache-dir pymupdf pillow openpyxl

COPY affidavit/ ./affidavit/
COPY pipeline.py README.md ./

# Matter data lives in a volume, never in the image.
VOLUME ["/data"]
ENV AOD_ROOT=/data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz',timeout=4).status==200 else 1)"

# Safe default: authentication on, Secure cookie, bound to all interfaces
# inside the container (the port mapping decides what the host exposes).
CMD ["sh", "-c", "python pipeline.py --root /data review --host 0.0.0.0 --port 8765 --require-auth --secure-cookie --no-browser"]
