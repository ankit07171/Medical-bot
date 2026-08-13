import os
import tempfile
import traceback
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

from langchain_pinecone import PineconeVectorStore

from src import gemini_client, session_store
from src.file_processor import process_uploaded_file
from src.helper import download_hugging_face_embeddings, text_split
from src.prompt import RAG_SYSTEM_PROMPT

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024  # 60 MB per request

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"}

# --- ENV KEYS ---
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not PINECONE_API_KEY or not GEMINI_API_KEY:
    raise RuntimeError("Missing PINECONE_API_KEY or GEMINI_API_KEY in .env")

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY
os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

# --- Embeddings & base (general) knowledge base ---
embeddings = download_hugging_face_embeddings()

INDEX_NAME = "medical-chatbot"
base_docsearch = PineconeVectorStore.from_existing_index(
    index_name=INDEX_NAME,
    embedding=embeddings,
)
base_retriever = base_docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 4})

# --- Gemini config (also used for vision OCR via src/gemini_client.py) ---
# Google retires/renames Gemini model IDs fairly often. Override with the
# GEMINI_MODEL env var if this default ever gets deprecated again — check
# current model IDs at https://ai.google.dev/gemini-api/docs/models
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


def get_session_id() -> str:
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
        session.permanent = True
    return session["sid"]


def build_context(uploaded_docs, kb_docs) -> str:
    parts = []
    for d in uploaded_docs:
        src = d.metadata.get("source", "uploaded file")
        page = d.metadata.get("page")
        tag = f"[Uploaded: {src}" + (f", page {page}]" if page and page > 0 else "]")
        parts.append(f"{tag}\n{d.page_content}")
    for d in kb_docs:
        parts.append(f"[General knowledge base]\n{d.page_content}")
    return "\n\n".join(parts) if parts else "No relevant context was found."


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    get_session_id()
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# File upload / management
# ---------------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    sid = get_session_id()
    files = request.files.getlist("files")
    if not files:
        return jsonify({"results": []})

    results = []
    for f in files:
        filename = secure_filename(f.filename or "")
        ext = os.path.splitext(filename)[1].lower()

        if not filename or ext not in ALLOWED_EXTENSIONS:
            results.append(
                {"filename": f.filename, "status": "error", "message": "Unsupported file type"}
            )
            continue

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                f.save(tmp.name)
                tmp_path = tmp.name

            docs, used_ocr = process_uploaded_file(tmp_path, filename, GEMINI_API_KEY)
            chunks = text_split(docs) if docs else []
            count = session_store.add_documents(sid, embeddings, filename, chunks, used_ocr)

            results.append(
                {
                    "filename": filename,
                    "status": "ready",
                    "chunks": count,
                    "pages": len(docs),
                    "used_ocr": used_ocr,
                }
            )
        except Exception as e:
            traceback.print_exc()
            results.append({"filename": filename, "status": "error", "message": str(e)})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    return jsonify({"results": results})


@app.route("/files", methods=["GET"])
def list_files():
    sid = get_session_id()
    manifest = session_store.load_manifest(sid)
    files = [
        {"filename": m["filename"], "chunks": m["chunk_count"], "used_ocr": m["used_ocr"]}
        for m in manifest
    ]
    return jsonify({"files": files})


@app.route("/remove_file", methods=["POST"])
def remove_file():
    sid = get_session_id()
    filename = (request.get_json(silent=True) or {}).get("filename", "")
    ok = session_store.remove_file(sid, embeddings, filename)
    return jsonify({"removed": ok})


@app.route("/reset", methods=["POST"])
def reset_session():
    sid = get_session_id()
    session_store.clear_session(sid)
    session.pop("sid", None)
    return jsonify({"status": "cleared"})


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.route("/get", methods=["POST"])
def chat():
    try:
        sid = get_session_id()
        msg = request.form.get("msg", "").strip()
        use_kb = request.form.get("use_kb", "true").lower() != "false"

        if not msg:
            return jsonify({"answer": "Please type a question.", "sources": []})

        uploaded_docs = session_store.retrieve(sid, embeddings, msg, k=4)
        kb_docs = base_retriever.invoke(msg) if use_kb else []

        context = build_context(uploaded_docs, kb_docs)
        system_message = RAG_SYSTEM_PROMPT.format(context=context)

        answer = gemini_client.generate_text(
            api_key=GEMINI_API_KEY,
            user_message=msg,
            system_prompt=system_message,
            model=GEMINI_MODEL,
            temperature=0.4,
            max_output_tokens=1024,
        )

        sources = sorted({d.metadata.get("source", "uploaded file") for d in uploaded_docs})
        return jsonify({"answer": answer, "sources": sources})
    except gemini_client.GeminiError as e:
        traceback.print_exc()
        return jsonify({"answer": f"Gemini error: {str(e)}", "sources": []}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"answer": f"Error: {str(e)}", "sources": []}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
