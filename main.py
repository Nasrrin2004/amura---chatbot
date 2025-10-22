from fastapi import FastAPI, Request, Form
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq
from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load env variables
load_dotenv()

app = FastAPI()

# Connect to MongoDB
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client["chatbot_db"]
messages_col = db["messages"]

# Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

@app.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...)
):
    """Handles incoming WhatsApp messages from Twilio"""
    user_message = Body.strip()
    user_number = From

    # Save incoming message to MongoDB
    messages_col.insert_one({
        "user": user_number,
        "role": "user",
        "message": user_message
    })

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

    # Save bot reply to MongoDB
    messages_col.insert_one({
        "user": user_number,
        "role": "assistant",
        "message": bot_reply
    })

    # Reply to Twilio (WhatsApp)
    twilio_resp = MessagingResponse()
    twilio_resp.message(bot_reply)
    return str(twilio_resp)
