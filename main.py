from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from groq import Groq
from pymongo import MongoClient
from dotenv import load_dotenv
import requests
import os
import logging

load_dotenv()
app = FastAPI()
logging.basicConfig(level=logging.INFO)

# ----- ENV -----
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID", "")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MONGO_URI = os.getenv("MONGO_URI", "")

if not (META_VERIFY_TOKEN and META_ACCESS_TOKEN and META_PHONE_NUMBER_ID and GROQ_API_KEY):
    raise RuntimeError("One or more required env vars are missing. Check META_* and GROQ_API_KEY.")

# ----- Mongo (optional) -----
messages_col = None
if MONGO_URI:
    try:
        mongo_client = MongoClient(MONGO_URI)
        db = mongo_client["chatbot_db"]
        messages_col = db["messages"]
        mongo_client.admin.command("ping")
        logging.info("✅ MongoDB connected")
    except Exception as e:
        logging.warning(f"⚠️  MongoDB connection failed: {e}")
        messages_col = None

# ----- Groq -----
groq_client = Groq(api_key=GROQ_API_KEY)

# ----- Helpers -----
GRAPH_URL = f"https://graph.facebook.com/v21.0/{META_PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {META_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

def send_whatsapp_text(to_number: str, body: str) -> None:
    """Send a text message via Meta WhatsApp Cloud API."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body},
    }
    r = requests.post(GRAPH_URL, headers=HEADERS, json=payload, timeout=20)
    if not r.ok:
        logging.error("WhatsApp send error %s: %s", r.status_code, r.text)
    else:
        logging.info("WhatsApp send ok: %s", r.text)

def generate_reply(user_text: str) -> str:
    """Generate a short reply via Groq."""
    try:
        comp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a helpful WhatsApp chatbot assistant."},
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
        )
        return (comp.choices[0].message.content or "").strip() or "I'm here!"
    except Exception as e:
        logging.error("Groq error: %s", e)
        return "Sorry, I ran into an issue. Please try again."

# ----- Health -----
@app.get("/")
def home():
    return JSONResponse({
        "status": "running",
        "webhook": "/webhook",
        "app": "CURA WhatsApp (Meta) 🚀"
    })

# ----- META VERIFY (GET) + INBOUND (POST) -----
@app.get("/webhook")
def verify(mode: str = None, hub_mode: str = None,
           hub_challenge: str = None, hub_verify_token: str = None,
           challenge: str = None, verify_token: str = None):
    """
    Meta will call GET /webhook with:
      hub.mode, hub.challenge, hub.verify_token
    Some proxies rename params; accept both.
    """
    mode_val = hub_mode or mode
    token = hub_verify_token or verify_token
    chall = hub_challenge or challenge or ""
    if mode_val == "subscribe" and token == META_VERIFY_TOKEN:
        return PlainTextResponse(chall, status_code=200)
    return PlainTextResponse("Verification failed", status_code=403)

@app.post("/webhook")
async def receive(req: Request):
    """
    Handles WhatsApp incoming messages.
    Body format: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples/
    """
    data = await req.json()
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                messages = value.get("messages", [])

                for m in messages:
                    from_number = m.get("from")            # e.g., "9198xxxx"
                    msg_type = m.get("type")
                    text_body = ""
                    if msg_type == "text":
                        text_body = (m.get("text") or {}).get("body", "").strip()
                    elif msg_type == "interactive":
                        # buttons/list replies
                        interactive = m.get("interactive") or {}
                        if interactive.get("type") == "button_reply":
                            text_body = (interactive.get("button_reply") or {}).get("title", "")
                        elif interactive.get("type") == "list_reply":
                            text_body = (interactive.get("list_reply") or {}).get("title", "")
                    else:
                        text_body = f"[{msg_type}] message"

                    # Persist inbound
                    if messages_col:
                        try:
                            messages_col.insert_one({
                                "user": from_number,
                                "role": "user",
                                "type": msg_type,
                                "message": text_body,
                                "raw": data
                            })
                        except Exception as e:
                            logging.warning("Mongo insert inbound failed: %s", e)

                    # Create reply
                    reply = generate_reply(text_body or "Hello")

                    # Send reply back
                    send_whatsapp_text(from_number, reply)

                    # Persist outbound
                    if messages_col:
                        try:
                            messages_col.insert_one({
                                "user": from_number,
                                "role": "assistant",
                                "type": "text",
                                "message": reply
                            })
                        except Exception as e:
                            logging.warning("Mongo insert outbound failed: %s", e)

        return JSONResponse({"ok": True})
    except Exception as e:
        logging.exception("Webhook error")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
