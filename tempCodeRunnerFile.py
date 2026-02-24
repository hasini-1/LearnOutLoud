import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Replace with your actual Groq API Key
GROQ_KEY = os.getenv("GROQ_API_KEY") or "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"
client = Groq(api_key=GROQ_KEY)

class ChatRequest(BaseModel):
    text: str

@app.post("/talk")
async def talk(request: ChatRequest):
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": """You are an elite spatial reasoning assistant for blind users.
                    
                    LOGIC PROTOCOL:
                    - If a user describes a room (e.g., 'window on left, door in front') and turns, you must calculate the new orientation.
                    - 90 deg RIGHT turn: Old Left -> Back, Old Front -> Left, Old Right -> Front, Old Back -> Right.
                    - 90 deg LEFT turn: Old Right -> Back, Old Front -> Right, Old Left -> Front, Old Back -> Left.
                    
                    LANGUAGE PROTOCOL:
                    - Default is English. Switch to Hindi, Telugu, Malayalam, or Kannada if the user speaks it or asks.
                    
                    VOICE OPTIMIZATION:
                    - Keep answers short (max 2 sentences).
                    - Plain text only. No bolding or markdown."""
                },
                {"role": "user", "content": request.text}
            ]
        )
        reply = completion.choices[0].message.content
        return {"reply": reply}
    except Exception as e:
        print(f"Server Error: {e}")
        return {"reply": "I'm having trouble processing that right now."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)