from dotenv import load_dotenv
import os

from src.helper import (
    load_pdf_file,
    filter_to_minimal_docs,
    text_split,
    download_hugging_face_embeddings,
)
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore

load_dotenv()

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
if not PINECONE_API_KEY:
    raise RuntimeError("Missing PINECONE_API_KEY in .env")

# --- Load & split docs ---
extracted_data = load_pdf_file(data="data/")     # place PDFs in ./data
filter_data = filter_to_minimal_docs(extracted_data)
text_chunks = text_split(filter_data)

# --- Embeddings ---
embeddings = download_hugging_face_embeddings()  # 384-dim (MiniLM-L6-v2)

# --- Pinecone ---
pc = Pinecone(api_key=PINECONE_API_KEY)
INDEX_NAME = "medical-chatbot"

if not pc.has_index(INDEX_NAME):
    pc.create_index(
        name=INDEX_NAME,
        dimension=384,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )

# Write to index
docsearch = PineconeVectorStore.from_documents(
    documents=text_chunks,
    index_name=INDEX_NAME,
    embedding=embeddings,
)

print("✅ Ingestion complete.")
