import os
import re
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from docx import Document
import PyPDF2

# Groq is optional now – basic features work without it
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

DOCUMENT_FOLDER = os.path.join(os.path.expanduser("~"), "Documents")

class VoiceRequest(BaseModel):
    text: str

# ───────────────────────────────────────────────
# Document extraction
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
                # Mark headings if possible
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
# File matching – very forgiving for short names
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

    if candidates:
        return candidates[0]  # take the first/best match
    return None

# ───────────────────────────────────────────────
# Smart section / page / paragraph extraction
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

    # Page or page range
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
            # Rough page approximation
            words = text.split()
            wpp = 450
            start_i = (start-1) * wpp
            end_i = end * wpp
            chunk = " ".join(words[start_i:end_i])
            return f"Approximate pages {start}–{end}:\n{preview(chunk)}"

    # Named sections (abstract, introduction, conclusion)
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

            # Fallback keyword + ~30 lines
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if re.search(pat, line):
                    block = "\n".join(lines[i:i+35])
                    return f"{name.title()} (approximate):\n{preview(block)}"
            return f"Could not find '{name}' section."

    # Paragraphs first/last
    para_pat = r'(first|last)\s*(\d*)\s*(paragraph|para|paragraphs)'
    m = re.search(para_pat, cmd_lower)
    if m:
        direction = m.group(1)
        count = int(m.group(2) or 1)

        paras = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
        if not paras:
            return "No paragraphs detected."

        if direction == "first":
            selected = paras[:count]
        else:
            selected = paras[-count:]

        return f"{direction.title()} {count} paragraph{'s' if count != 1 else ''}:\n{preview('\n\n'.join(selected))}"

    return None

# ───────────────────────────────────────────────
# Main voice processing
# ───────────────────────────────────────────────

@app.post("/talk")
async def talk(req: VoiceRequest):
    global current_document_text, current_position, current_document_name, current_document_type

    spoken = req.text.strip()
    cmd = spoken.lower()
    print(f"→ Heard: {spoken}")

    # List files
    if any(x in cmd for x in ["list", "files", "documents", "show"]):
        if not os.path.exists(DOCUMENT_FOLDER):
            return {"reply": "Documents folder not found."}
        files = [os.path.splitext(f)[0] for f in os.listdir(DOCUMENT_FOLDER)
                 if f.lower().endswith(('.pdf','.docx','.txt'))]
        if not files:
            return {"reply": "No supported files found."}
        return {"reply": f"Found: {', '.join(files)}. Say the name to open."}

    # Load file (explicit or just saying name)
    matched = find_matching_file(spoken)
    if matched and (any(x in cmd for x in ["load","open","read","start"]) or len(spoken.split()) <= 4):
        path = os.path.join(DOCUMENT_FOLDER, matched)
        content = read_document(path)

        if "error" in content.lower():
            return {"reply": content}

        current_document_text = content
        current_position = 0
        current_document_name = os.path.splitext(matched)[0]
        current_document_type = os.path.splitext(matched)[1][1:].upper()
        words = len(content.split())
        return {"reply": f"Loaded {current_document_name} ({current_document_type}) – ~{words} words. Say read, extract abstract, extract page 3, etc."}

    if not current_document_text:
        return {"reply": "No document open. Say a filename or 'list documents'."}

    # Smart extraction
    if "extract" in cmd:
        result = smart_extract(cmd)
        if result:
            return {"reply": result}

    # Read commands
    if any(x in cmd for x in ["read", "start", "begin"]):
        current_position = 0
        chunk = current_document_text[:650]
        return {"reply": f"Reading {current_document_name}...\n{chunk}\n\nSay continue, pause, stop."}

    if any(x in cmd for x in ["continue", "more", "next"]):
        chunk = current_document_text[current_position:current_position+650]
        if not chunk:
            return {"reply": f"End of {current_document_name}."}
        current_position += 650
        perc = round(current_position / len(current_document_text) * 100)
        return {"reply": f"{chunk}\n[Progress: {perc}%]"}

    if "pause" in cmd:
        return {"reply": "Paused. Say continue or resume."}

    if "resume" in cmd:
        return {"reply": "Resuming... Say continue."}

    if any(x in cmd for x in ["stop", "end", "close"]):
        current_document_text = ""
        current_position = 0
        current_document_name = ""
        current_document_type = ""
        return {"reply": "Document closed."}

    # Summary (only if Groq works)
    if any(x in cmd for x in ["summary", "summarize"]):
        if not GROQ_AVAILABLE:
            return {"reply": "Summary unavailable right now. You can still read the document."}
        try:
            short = current_document_text[:3000] + "..." if len(current_document_text) > 3000 else current_document_text
            r = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": f"Summarize this document concisely:\n{short}"}],
                temperature=0.3,
                max_tokens=250
            )
            return {"reply": "Summary:\n" + r.choices[0].message.content.strip()}
        except:
            return {"reply": "Could not generate summary – connection issue."}

    return {"reply": "Sorry, I didn't understand. Try 'list documents', file name, 'read', 'continue', 'extract abstract', 'extract page 3'..."}

if __name__ == "__main__":
    print("LearnOutLoud server starting...")
    print(f"Documents folder: {DOCUMENT_FOLDER}")
    print("Supported: PDF, DOCX, TXT")
    print("Commands: list documents | filename | read | continue | extract abstract | extract page 3 | extract first 3 paragraphs | etc.")
    uvicorn.run(app, host="0.0.0.0", port=8000)