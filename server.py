import os
import re
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
import PyPDF2
from collections import deque  # for limited-size history

# Groq optional
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

# History: list of (user_said, assistant_replied) tuples – newest first
# Using deque with maxlen → automatically drops oldest entries
conversation_history = deque(maxlen=12)

DOCUMENT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents")

class VoiceRequest(BaseModel):
    text: str

# ───────────────────────────────────────────────
# Document extraction (unchanged)
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
# Smart extraction (your latest friendly version)
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

    # Named sections with friendly fallback
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

            # Friendly message for normal documents
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

    return "Didn't understand which part to extract. Examples:\n• extract page 5\n• extract abstract\n• extract first 4 paragraphs"

# ───────────────────────────────────────────────
# Add entry to history
# ───────────────────────────────────────────────

def add_to_history(user_text: str, assistant_reply: str):
    conversation_history.appendleft((user_text.strip(), assistant_reply.strip()))

# ───────────────────────────────────────────────
# Main endpoint
# ───────────────────────────────────────────────

@app.post("/talk")
async def talk(req: VoiceRequest):
    global current_document_text, current_position, current_document_name, current_document_type

    spoken = req.text.strip()
    cmd = spoken.lower()
    print(f"→ Heard: {spoken}")

    reply_text = ""

    # ── History commands ────────────────────────────────────────────────
    if any(w in cmd for w in ["history", "what did i say", "repeat last", "last message", "previous"]):
        if not conversation_history:
            reply_text = "No conversation history yet."
        elif "read" in cmd or "tell" in cmd:
            lines = []
            for i, (u, a) in enumerate(list(conversation_history)[:5], 1):
                lines.append(f"{i}. You said: {u}")
                lines.append(f"   I said: {a[:180]}{'...' if len(a)>180 else ''}")
            reply_text = "Recent conversation:\n" + "\n".join(lines)
        elif "clear" in cmd:
            conversation_history.clear()
            reply_text = "Conversation history cleared."
        else:
            # show last exchange
            u, a = conversation_history[0]
            reply_text = f"Last: You said '{u}'. I replied: {a}"

    # ── Document commands ───────────────────────────────────────────────
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

    else:
        matched = find_matching_file(spoken)
        if matched and (any(x in cmd for x in ["load","open","read","start"]) or len(spoken.split()) <= 4):
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

        elif not current_document_text:
            reply_text = "No document open. Say a filename or 'list documents'."

        elif "extract" in cmd:
            result = smart_extract(cmd)
            if result:
                reply_text = result

        elif any(x in cmd for x in ["read", "start", "begin"]):
            current_position = 0
            chunk = current_document_text[:650]
            reply_text = f"Reading {current_document_name}...\n{chunk}\n\nSay continue, pause, stop."

        elif any(x in cmd for x in ["continue", "more", "next"]):
            chunk = current_document_text[current_position:current_position+650]
            if not chunk:
                reply_text = f"End of {current_document_name}."
            else:
                current_position += 650
                perc = round(current_position / len(current_document_text) * 100)
                reply_text = f"{chunk}\n[Progress: {perc}%]"

        elif "pause" in cmd:
            reply_text = "Paused. Say continue or resume."

        elif "resume" in cmd:
            reply_text = "Resuming... Say continue."

        elif any(x in cmd for x in ["stop", "end", "close"]):
            current_document_text = ""
            current_position = 0
            current_document_name = ""
            current_document_type = ""
            reply_text = "Document closed."

        elif any(x in cmd for x in ["summary", "summarize"]) and GROQ_AVAILABLE:
            try:
                short = current_document_text[:3000] + "..." if len(current_document_text) > 3000 else current_document_text
                r = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": f"Summarize concisely:\n{short}"}],
                    temperature=0.3,
                    max_tokens=250
                )
                reply_text = "Summary:\n" + r.choices[0].message.content.strip()
            except:
                reply_text = "Could not generate summary right now."

        else:
            reply_text = "Sorry, didn't understand. Try 'list documents', filename, 'read', 'extract page 3', 'summary'..."

    # ── Save to history (except pure history commands) ──────────────────
    if not any(w in cmd for w in ["history", "repeat last", "clear history"]):
        add_to_history(spoken, reply_text)

    print(f"→ Replied: {reply_text[:120]}...")
    return {"reply": reply_text}

if __name__ == "__main__":
    print("LearnOutLoud server with history support")
    print(f"Documents: {DOCUMENT_FOLDER}")
    print("New commands: 'show history', 'read history', 'repeat last', 'clear history'")
    uvicorn.run(app, host="0.0.0.0", port=8000)