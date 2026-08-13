// ---------------------------------------------------------------------------
// Elements
// ---------------------------------------------------------------------------
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const fileList = document.getElementById("fileList");
const useKbToggle = document.getElementById("useKbToggle");
const kbStatus = document.getElementById("kbStatus");
const resetBtn = document.getElementById("resetBtn");

const messagesEl = document.getElementById("messages");
const typingIndicator = document.getElementById("typingIndicator");
const chatForm = document.getElementById("chatForm");
const textInput = document.getElementById("textInput");
const micBtn = document.getElementById("micBtn");
const speakToggle = document.getElementById("speakToggle");
const listeningIndicator = document.getElementById("listeningIndicator");

let userInteracted = false;
document.addEventListener("click", () => { userInteracted = true; }, { once: true });

// ---------------------------------------------------------------------------
// File tray state + rendering
// ---------------------------------------------------------------------------
let files = {}; // filename -> {status, chunks, used_ocr}

function renderFiles() {
  fileList.innerHTML = "";
  const names = Object.keys(files);
  if (names.length === 0) {
    fileList.innerHTML = `<li class="file-item" style="justify-content:center;color:var(--text-muted);">No files uploaded yet</li>`;
    return;
  }
  names.forEach((name) => {
    const f = files[name];
    const li = document.createElement("li");
    li.className = "file-item";

    const icon = name.toLowerCase().endsWith(".pdf") ? "fa-file-pdf" : "fa-file-image";
    const statusBadge =
      f.status === "processing"
        ? `<span class="badge badge-processing">processing</span>`
        : f.status === "error"
        ? `<span class="badge badge-error">error</span>`
        : `<span class="badge badge-ready">ready</span>`;
    const ocrBadge = f.used_ocr ? `<span class="badge badge-ocr">OCR</span>` : "";
    const meta =
      f.status === "error"
        ? (f.message || "Failed to process")
        : f.status === "processing"
        ? "reading document…"
        : `${f.chunks ?? 0} chunks indexed`;

    li.innerHTML = `
      <i class="fas ${icon} f-icon"></i>
      <div class="f-body">
        <div class="f-name">${name}</div>
        <div class="f-meta">${statusBadge}${ocrBadge}<span>${meta}</span></div>
      </div>
      <button class="f-remove" title="Remove"><i class="fas fa-times"></i></button>
    `;
    li.querySelector(".f-remove").addEventListener("click", () => removeFile(name));
    fileList.appendChild(li);
  });
}

async function removeFile(name) {
  delete files[name];
  renderFiles();
  try {
    await fetch("/remove_file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: name }),
    });
  } catch (e) {
    console.error(e);
  }
}

async function refreshFilesFromServer() {
  try {
    const res = await fetch("/files");
    const data = await res.json();
    files = {};
    (data.files || []).forEach((f) => {
      files[f.filename] = { status: "ready", chunks: f.chunks, used_ocr: f.used_ocr };
    });
    renderFiles();
  } catch (e) {
    console.error(e);
  }
}

async function uploadFiles(fileArray) {
  if (!fileArray.length) return;

  fileArray.forEach((f) => {
    files[f.name] = { status: "processing" };
  });
  renderFiles();

  const formData = new FormData();
  fileArray.forEach((f) => formData.append("files", f));

  try {
    const res = await fetch("/upload", { method: "POST", body: formData });
    const data = await res.json();
    (data.results || []).forEach((r) => {
      files[r.filename] = {
        status: r.status,
        chunks: r.chunks,
        used_ocr: r.used_ocr,
        message: r.message,
      };
    });
  } catch (e) {
    fileArray.forEach((f) => {
      files[f.name] = { status: "error", message: "Upload failed" };
    });
  }
  renderFiles();
}

dropzone.addEventListener("click", (e) => {
  // label already opens file picker; avoid double trigger from inner click bubbling twice
});
fileInput.addEventListener("change", () => {
  uploadFiles(Array.from(fileInput.files));
  fileInput.value = "";
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (e) => {
  const dropped = Array.from(e.dataTransfer.files || []);
  uploadFiles(dropped);
});

useKbToggle.addEventListener("change", () => {
  kbStatus.innerHTML = `<i class="fas fa-database"></i> knowledge base: ${useKbToggle.checked ? "on" : "off"}`;
});

resetBtn.addEventListener("click", async () => {
  if (!confirm("Start a new session? This clears your uploaded files and chat history on the server.")) return;
  try {
    await fetch("/reset", { method: "POST" });
  } catch (e) {
    console.error(e);
  }
  window.location.reload();
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
function appendMessage(role, text, sources) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}`;

  const avatar = document.createElement("div");
  avatar.className = `avatar avatar-${role}`;
  avatar.innerHTML = role === "bot" ? '<i class="fas fa-stethoscope"></i>' : '<i class="fas fa-user"></i>';

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  if (sources && sources.length) {
    const src = document.createElement("div");
    src.className = "sources";
    src.innerHTML = sources.map((s) => `<span><i class="fas fa-paperclip"></i> ${s}</span>`).join("");
    bubble.appendChild(src);
  }

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage(text) {
  appendMessage("user", text);
  typingIndicator.hidden = false;
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {
    const body = new URLSearchParams();
    body.set("msg", text);
    body.set("use_kb", useKbToggle.checked ? "true" : "false");

    const res = await fetch("/get", { method: "POST", body });
    const data = await res.json();
    const answer = data.answer || "Sorry, something went wrong.";

    typingIndicator.hidden = true;
    appendMessage("bot", answer, data.sources);
    if (speakToggle.classList.contains("active")) speak(answer);
  } catch (e) {
    typingIndicator.hidden = true;
    appendMessage("bot", "Sorry, I couldn't reach the server. Please try again.");
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = "";
  sendMessage(text);
});

// ---------------------------------------------------------------------------
// Text-to-speech: chunk long answers into sentences so browsers (esp. Chrome)
// don't cut speech off after ~15s, and queue them for smooth playback.
// ---------------------------------------------------------------------------
let preferredVoice = null;
function pickVoice() {
  const voices = window.speechSynthesis.getVoices();
  preferredVoice =
    voices.find((v) => /en-US|en_GB|en-GB/.test(v.lang) && /female|natural|google/i.test(v.name)) ||
    voices.find((v) => v.lang && v.lang.startsWith("en")) ||
    voices[0] ||
    null;
}
if ("speechSynthesis" in window) {
  window.speechSynthesis.onvoiceschanged = pickVoice;
  pickVoice();
}

function splitIntoChunks(text, maxLen = 200) {
  const sentences = text.match(/[^.!?]+[.!?]*/g) || [text];
  const chunks = [];
  let current = "";
  for (const s of sentences) {
    if ((current + s).length > maxLen && current) {
      chunks.push(current.trim());
      current = s;
    } else {
      current += s;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  if (!userInteracted) return; // respect browser autoplay policies
  window.speechSynthesis.cancel();

  const chunks = splitIntoChunks(text);
  chunks.forEach((chunk) => {
    const utter = new SpeechSynthesisUtterance(chunk);
    utter.rate = 1;
    utter.pitch = 1;
    utter.volume = 1;
    utter.lang = "en-US";
    if (preferredVoice) utter.voice = preferredVoice;
    window.speechSynthesis.speak(utter);
  });
}

speakToggle.addEventListener("click", () => {
  const nowActive = !speakToggle.classList.contains("active");
  speakToggle.classList.toggle("active", nowActive);
  speakToggle.querySelector("i").className = nowActive ? "fas fa-volume-up" : "fas fa-volume-mute";
  localStorage.setItem("medbot_speak", nowActive ? "1" : "0");
  if (!nowActive) window.speechSynthesis.cancel();
});
(function restoreSpeakPref() {
  const saved = localStorage.getItem("medbot_speak");
  const active = saved === null ? true : saved === "1";
  speakToggle.classList.toggle("active", active);
  speakToggle.querySelector("i").className = active ? "fas fa-volume-up" : "fas fa-volume-mute";
})();

// ---------------------------------------------------------------------------
// Speech-to-text
// ---------------------------------------------------------------------------
const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognitionImpl) {
  const recognition = new SpeechRecognitionImpl();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = "en-US";
  let running = false;
  let micTimeout = null;

  micBtn.addEventListener("click", () => {
    userInteracted = true;
    if (running) {
      recognition.stop();
      return;
    }
    try {
      recognition.start();
      running = true;
      micBtn.classList.add("recording");
      listeningIndicator.hidden = false;
      micTimeout = setTimeout(() => running && recognition.stop(), 6000);
    } catch (err) {
      console.error(err);
    }
  });

  recognition.onresult = (event) => {
    const last = event.results[event.results.length - 1];
    if (last.isFinal) {
      const text = last[0].transcript.trim();
      if (text) {
        textInput.value = text;
        chatForm.requestSubmit();
      }
    }
  };
  recognition.onend = () => {
    running = false;
    micBtn.classList.remove("recording");
    listeningIndicator.hidden = true;
    clearTimeout(micTimeout);
  };
  recognition.onerror = () => {
    running = false;
    micBtn.classList.remove("recording");
    listeningIndicator.hidden = true;
    clearTimeout(micTimeout);
  };
} else {
  micBtn.style.display = "none";
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
refreshFilesFromServer();
