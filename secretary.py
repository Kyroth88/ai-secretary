Python
import os
import time
import google.genai as genai

# Read API Key passed from Docker environment variables
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("❌ Error: GEMINI_API_KEY is missing!")
    exit(1)

client = genai.Client(api_key=api_key)

print("🤖 AI Secretary initialized and running inside Docker...")

# Basic infinite loop to keep the script running in the background
while True:
    print("⏳ Secretary is checking for new tasks/emails...")
    time.sleep(60) # Sleep for 60 seconds between checks
