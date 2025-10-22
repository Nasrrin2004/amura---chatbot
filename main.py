from fastapi import FastAPI, Request, Form
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq
from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load env variables
load_dotenv()

app = FastAPI()
# ----------------------------
# DATABASE CONNECTION (robust init)
# ----------------------------
messages_col = None

mongo_uri = os.getenv("MONGO_URI", "").strip()
if not mongo_uri:
    print("⚠️  MONGO_URI not set; continuing without DB (messages won't be saved)")
elif not mongo_uri.startswith(("mongodb://", "mongodb+srv://")):
    print("❌ Invalid MONGO_URI format. Must start with 'mongodb://' or 'mongodb+srv://'. Continuing without DB.")
else:
    try:
        mongo_client = MongoClient(mongo_uri)
        db = mongo_client["chatbot_db"]
        messages_col = db["messages"]
        print("✅ MongoDB connected successfully!")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}. Continuing without DB.")

# ----------------------------
# GROQ CLIENT SETUP
# ----------------------------
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("❌ GROQ_API_KEY not found in environment")
groq_client = Groq(api_key=groq_api_key)
@app.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...)
):
    """Handles incoming WhatsApp messages from Twilio"""
    user_message = Body.strip()
    user_number = From
    if messages_col is not None:
        try:
            messages_col.insert_one({
                "user": user_number,
                "role": "user",
                "message": user_message
            })
        except Exception as e:
            # Non-fatal: proceed to reply even if DB write fails
            print(f"⚠️  Failed to write incoming message to MongoDB: {e}")
        # Generate AI reply using LLaMA 3.1
    completion = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You are a helpful WhatsApp chatbot assistant."},
            {"role": "user", "content": user_message}
        ],
        temperature=0.6
    )

    bot_reply = completion.choices[0].message["content"]
    if messages_col is not None:
        try:
            messages_col.insert_one({
                "user": user_number,
                "role": "assistant",
                "message": bot_reply
            })
        except Exception as e:
            print(f"⚠️  Failed to write bot reply to MongoDB: {e}")

    # Reply to Twilio (WhatsApp)
    twilio_resp = MessagingResponse()
    twilio_resp.message(bot_reply)
    # Ensure Twilio gets proper XML content type
    return Response(content=str(twilio_resp), media_type="application/xml")