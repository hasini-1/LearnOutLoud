import os
import re
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
import PyPDF2
from collections import deque

# Groq is optional
try:
    from groq import Groq
    GROQ_AVAILABLE = True
    client = Groq(api_key="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")
except:
    GROQ_AVAILABLE = False
    print("Note: Groq unavailable → summary & general chat disabled")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Globals
current_document_text = ""
current_position = 0
current_document_name = ""
current_document_type = ""

# Speech rate control
speech_rate = 1.0

# History
conversation_history = deque(maxlen=12)

DOCUMENT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents")

class VoiceRequest(BaseModel):
    text: str

# ───────────────────────────────────────────────
# Document extraction functions
# ───────────────────────────────────────────────

def extract_pdf(path):
    text = ""
    try:
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages, 1):
                content = page.extract_text() or ""
                text += f"[Page {i}]\n{content.strip()}\n\n"
        return text.strip()
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def extract_docx(path):
    text = ""
    try:
        doc = Document(path)
        for para in doc.paragraphs:
            if para.text.strip():
                if para.style.name.lower().startswith('heading'):
                    text += f"[HEADING] {para.text}\n"
                else:
                    text += para.text + "\n"
        return text.strip()
    except Exception as e:
        return f"Error reading DOCX: {str(e)}"

def extract_txt(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read().strip()
    except Exception as e:
        return f"Error reading TXT: {str(e)}"

def read_document(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        return extract_pdf(path)
    if ext == '.docx':
        return extract_docx(path)
    if ext == '.txt':
        return extract_txt(path)
    return "Unsupported file format (only pdf, docx, txt)"

# ───────────────────────────────────────────────
# File matching
# ───────────────────────────────────────────────

def find_matching_file(spoken: str):
    if not os.path.exists(DOCUMENT_FOLDER):
        return None

    spoken_clean = re.sub(r'[^a-z0-9]', '', spoken.lower())
    candidates = []

    for filename in os.listdir(DOCUMENT_FOLDER):
        if not filename.lower().endswith(('.pdf', '.docx', '.txt')):
            continue
        name_clean = re.sub(r'[^a-z0-9]', '', os.path.splitext(filename)[0].lower())
        if spoken_clean in name_clean or name_clean in spoken_clean:
            candidates.append(filename)

    return candidates[0] if candidates else None

# ───────────────────────────────────────────────
# Smart extraction
# ───────────────────────────────────────────────

def smart_extract(cmd_lower: str):
    global current_document_text, current_document_name, current_document_type

    if not current_document_text:
        return "No document is loaded. Say the filename or 'list documents' first."

    text = current_document_text
    doc_type = current_document_type.lower()

    def preview(s: str, maxlen=1400):
        s = s.strip()[:maxlen]
        if len(s) == maxlen:
            s += " … (say continue or read for more)"
        return s.replace('\n', ' ')

    # Page range
    page_match = re.search(r'(?:page|pages)\s*(\d+)(?:\s*(?:to|and|-|till)\s*(\d+))?', cmd_lower)
    if page_match:
        start = int(page_match.group(1))
        end = int(page_match.group(2)) if page_match.group(2) else start

        if 'pdf' in doc_type:
            parts = re.split(r'\[Page\s*(\d+)\]', text)
            page_content = {}
            for i in range(1, len(parts), 2):
                try:
                    page_content[int(parts[i])] = parts[i+1].strip()
                except:
                    pass

            if start not in page_content:
                return f"Page {start} not found."

            result = ""
            for p in range(start, end + 1):
                if p in page_content:
                    result += f"[Page {p}]\n{page_content[p]}\n\n"
            return f"Extracted page(s) {start}–{end}:\n{preview(result)}"

        else:
            words = text.split()
            wpp = 450
            start_i = max(0, (start-1) * wpp)
            end_i = end * wpp
            chunk = " ".join(words[start_i:end_i])
            return f"Approximate pages {start}–{end}:\n{preview(chunk)}"

    # Named sections
    sections = {
        'abstract':     r'(?i)(abstract|अमूर्त|సారాంశం)',
        'introduction': r'(?i)(introduction|intro|परिचय|పరిచయం)',
        'conclusion':   r'(?i)(conclusion|conclusions|निष्कर्ष|సారాంశం)'
    }

    for name, pat in sections.items():
        if name in cmd_lower:
            m = re.search(pat + r'[\s\S]*?(?=\n\s*(?i:(abstract|introduction|conclusion|references|bibliography|appendix|\[Page|\d+\.\d+)))', text, re.DOTALL | re.I)
            if m:
                return f"Extracted {name.title()}:\n{preview(m.group(0))}"

            lines = text.splitlines()
            for i, line in enumerate(lines):
                if re.search(pat, line):
                    block = "\n".join(lines[i:i+35])
                    return f"{name.title()} (approximate):\n{preview(block)}"

            if name == 'abstract':
                return "This document doesn't seem to have a marked abstract section (common in non-research files). Would you like the first few paragraphs? Say 'extract first 5 paragraphs' or 'read'."
            if name == 'introduction':
                return "No clear introduction found. Try 'extract first 4 paragraphs' or 'read' to start from the beginning."
            if name == 'conclusion':
                return "No conclusion section detected. Say 'extract last 5 paragraphs' to hear the ending."

    # Paragraphs
    para_match = re.search(r'(first|last)\s*(\d*)\s*(paragraph|para|paragraphs)', cmd_lower)
    if para_match:
        direction = para_match.group(1)
        count = int(para_match.group(2) or 3)

        paras = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
        if not paras:
            return "No clear paragraphs found."

        if direction == "first":
            selected = paras[:count]
        else:
            selected = paras[-count:]

        return f"{direction.title()} {count} paragraph{'s' if count != 1 else ''}:\n{preview('\n\n'.join(selected))}"

    return "Didn't understand which part to extract. Try:\n• extract page 5\n• extract abstract\n• extract first 4 paragraphs"

# ───────────────────────────────────────────────
# Speed control
# ───────────────────────────────────────────────

def handle_speed_command(cmd_lower: str):
    global speech_rate

    if any(w in cmd_lower for w in ["normal speed", "default speed", "speed 1", "1x"]):
        speech_rate = 1.0
        return "Speed set back to normal (1x)."

    speed_match = re.search(r'(?:set speed to|speed|set to)\s*(\d*\.?\d*)\s*(x|times)?', cmd_lower)
    if speed_match:
        try:
            new_rate = float(speed_match.group(1))
            speech_rate = max(0.5, min(2.5, new_rate))
            return f"Speed set to {speech_rate:.1f}x."
        except:
            pass

    if any(w in cmd_lower for w in ["increase speed", "faster", "speed up", "go faster"]):
        speech_rate = min(2.5, speech_rate + 0.2)
        return f"Speed increased to {speech_rate:.1f}x."

    if any(w in cmd_lower for w in ["decrease speed", "slower", "slow down", "go slower"]):
        speech_rate = max(0.5, speech_rate - 0.2)
        return f"Speed decreased to {speech_rate:.1f}x."

    return None

# ───────────────────────────────────────────────
# Main endpoint – fixed general questions
# ───────────────────────────────────────────────

@app.post("/talk")
async def talk(req: VoiceRequest):
    global current_document_text, current_position, current_document_name, current_document_type, speech_rate

    spoken = req.text.strip()
    cmd = spoken.lower()
    print(f"→ Heard: {spoken}")

    reply_text = ""
    response_data = {"reply": "", "rate": round(speech_rate, 2)}

    # 1. Speed commands
    speed_reply = handle_speed_command(cmd)
    if speed_reply:
        reply_text = speed_reply

    # 2. List documents
    elif any(x in cmd for x in ["list", "files", "documents", "show"]):
        if not os.path.exists(DOCUMENT_FOLDER):
            reply_text = "Documents folder not found."
        else:
            files = [os.path.splitext(f)[0] for f in os.listdir(DOCUMENT_FOLDER)
                     if f.lower().endswith(('.pdf','.docx','.txt'))]
            if not files:
                reply_text = "No supported files found."
            else:
                reply_text = f"Found: {', '.join(files)}. Say the name to open."

    # 3. Load document (auto or explicit)
    elif matched := find_matching_file(spoken):
        if any(x in cmd for x in ["load","open","read","start"]) or len(spoken.split()) <= 4:
            path = os.path.join(DOCUMENT_FOLDER, matched)
            content = read_document(path)

            if "error" in content.lower():
                reply_text = content
            else:
                current_document_text = content
                current_position = 0
                current_document_name = os.path.splitext(matched)[0]
                current_document_type = os.path.splitext(matched)[1][1:].upper()
                words = len(content.split())
                reply_text = f"Loaded {current_document_name} ({current_document_type}) – ~{words} words. Say read, extract abstract, extract page 3, etc."

    # 4. Document-dependent commands
    elif "extract" in cmd:
        result = smart_extract(cmd)
        if result:
            reply_text = result

    elif any(x in cmd for x in ["read", "start", "begin"]):
        if not current_document_text:
            reply_text = "No document loaded. Say a filename or 'list documents' first."
        else:
            current_position = 0
            chunk = current_document_text[:650]
            reply_text = f"Reading {current_document_name}...\n{chunk}\n\nSay continue, pause, stop."

    elif any(x in cmd for x in ["continue", "more", "next"]):
        if not current_document_text:
            reply_text = "No document loaded. Load one first."
        else:
            chunk = current_document_text[current_position:current_position+650]
            if not chunk:
                reply_text = f"End of {current_document_name}."
            else:
                current_position += 650
                perc = round(current_position / len(current_document_text) * 100)
                reply_text = f"{chunk}\n[Progress: {perc}%]"

    elif "pause" in cmd:
        if current_document_text:
            reply_text = "Paused. Say continue or resume."
        else:
            reply_text = "Nothing is playing right now."

    elif "resume" in cmd:
        if current_document_text:
            reply_text = "Resuming... Say continue."
        else:
            reply_text = "No document to resume. Load one first."

    elif any(x in cmd for x in ["stop", "end", "close"]):
        if current_document_text:
            current_document_text = ""
            current_position = 0
            current_document_name = ""
            current_document_type = ""
            reply_text = "Document closed."
        else:
            reply_text = "No document is open."

    # Summary (only when document is loaded)
    elif any(x in cmd for x in ["summary", "summarize"]):
        if not current_document_text:
            reply_text = "No document loaded. Load one first to get a summary."
        elif not GROQ_AVAILABLE:
            reply_text = "Summary unavailable right now."
        else:
            try:
                short = current_document_text[:3000] + "..." if len(current_document_text) > 3000 else current_document_text
                r = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": f"Summarize concisely:\n{short}"}],
                    temperature=0.3,
                    max_tokens=250
                )
                reply_text = "Summary:\n" + r.choices[0].message.content.strip()
            except Exception as e:
                print("Summary failed:", e)
                reply_text = "Could not generate summary right now."

    # ── General / common questions – always allowed, runs last ──────────
    else:
        if GROQ_AVAILABLE:
            try:
                system_prompt = (
                    "You are LearnOutLoud, a friendly voice assistant for visually impaired students. "
                    "Answer clearly, concisely, naturally and helpfully. Use simple language. "
                    "If the question relates to a loaded document, refer to it if relevant. "
                    "Otherwise answer normally like a helpful companion. "
                    "Keep answers suitable for voice output — short, clear, no very long lists."
                )
                r = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": spoken}
                    ],
                    temperature=0.7,
                    max_tokens=400
                )
                reply_text = r.choices[0].message.content.strip()
            except Exception as e:
                print("General QA error:", str(e))
                reply_text = "Sorry, I couldn't answer that right now. Try asking about a loaded document or say 'help'."
        else:
            reply_text = "I'm currently unable to answer general questions. I can still read documents, extract parts, change speed, etc."

    response_data["reply"] = reply_text
    return response_data

if __name__ == "__main__":
    print("LearnOutLoud server – general questions fixed")
    print(f"Documents folder: {DOCUMENT_FOLDER}")
    print("Now supports questions like 'explain linear regression', 'what is photosynthesis', etc. even without a document loaded.")
    uvicorn.run(app, host="0.0.0.0", port=8000)