FROM python:3.12-slim

WORKDIR /app

# poppler-utils: renders scanned PDF pages to images for OCR (pdf2image)
# tesseract-ocr: local OCR fallback if the Gemini vision call fails
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Per-session vector stores and temp uploads live here at runtime
RUN mkdir -p chroma_store

# Railway uses PORT environment variable
ENV PORT=8080

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]
