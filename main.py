from fastapi import FastAPI, Request, Form
from fastapi.responses import Response, JSONResponse
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq
from pymongo import MongoClient
from dotenv import load_dotenv
import os

# ----------------------------
# LOAD ENV VARIABLES
# ----------------------------
load_dotenv()  # Loads .env file locally

app = FastAPI()

# ----------------------------
# ROOT ENDPOINT
# ----------------------------
@app.get("/")
def home():
    return JSONResponse({
        "status": "running",
        "message": "Welcome to Amura Chatbot API 🚀",
        "endpoints": {
            "webhook": "/webhook (POST)"
        }
    })

# ----------------------------
# MONGO CONNECTION
# ----------------------------
mongo_uri = os.getenv("MONGO_URI", "").strip()

if not mongo_uri:
    raise ValueError("❌ MONGO_URI not found in environment variables. Set it in .env or Render Environment Variables.")

messages_col = None
try:
    mongo_client = MongoClient(mongo_uri)
    db = mongo_client["chatbot_db"]
    messages_col = db["messages"]
    # Verify connection
    mongo_client.admin.command('ping')
    print("✅ MongoDB connected successfully!")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    messages_col = None

# ----------------------------
# GROQ CLIENT SETUP
# ----------------------------
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("❌ GROQ_API_KEY not found in environment variables")

client = Groq(api_key=groq_api_key)

# ----------------------------
# WHATSAPP WEBHOOK
# ----------------------------
@app.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...)
):
    user_message = Body.strip()
    user_number = From

    print(f"📩 Incoming message from {user_number}: {user_message}")

    # Save user message
    if messages_col:
        try:
            messages_col.insert_one({
                "user": user_number,
                "role": "user",
                "message": user_message
            })
        except Exception as e:
            print(f"⚠️  Failed to write incoming message to MongoDB: {e}")

    # Generate AI reply using LLaMA 3.1
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a helpful WhatsApp chatbot assistant."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.6
        )
        # Correct property access for the latest SDK
        bot_reply = completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Error generating Groq reply: {e}")
        bot_reply = "Sorry, I ran into an issue. Please try again later."

    # Save bot reply
    if messages_col:
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

    print(f"🤖 Replied to {user_number}: {bot_reply}")
    return Response(content=str(twilio_resp), media_type="application/xml")
