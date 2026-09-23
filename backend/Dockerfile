FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /app/backend
ARG INSTALL_OCR=true
RUN if [ "$INSTALL_OCR" = "true" ]; then pip install --no-cache-dir -r backend/requirements-ocr.txt; fi
COPY separador_materiais /app/separador_materiais
RUN useradd --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
