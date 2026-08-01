import os
import time
import imaplib
import smtplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, time as dtime
import json
import google.genai as genai

# --- Configuration & Envs ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
IMAP_SERVER = os.environ.get("IMAP_SERVER", "imap.gmail.com")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
OBSIDIAN_TASKS_PATH = os.environ.get("OBSIDIAN_TASKS_PATH", "/obsidian/Tasks.md")

client = genai.Client(api_key=GEMINI_API_KEY)


def calculate_business_slot(target_dt: datetime) -> datetime:
    """Adjusts date to ensure it lands on a weekday during business hours (9 AM - 5 PM)."""
    # If weekend, push to Monday
    if target_dt.weekday() == 5:  # Saturday
        target_dt += timedelta(days=2)
    elif target_dt.weekday() == 6:  # Sunday
        target_dt += timedelta(days=1)

    # Set default time to 9:00 AM if outside 9 AM - 5 PM
    if target_dt.hour < 9 or target_dt.hour >= 17:
        target_dt = datetime.combine(target_dt.date(), dtime(9, 0))

    return target_dt


def create_ics_content(summary: str, start_dt: datetime, duration_minutes: int = 30) -> str:
    """Generates standard iCalendar (.ics) content string."""
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    fmt = "%Y%m%dT%H%M%SZ"

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//AI Secretary//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:ai-sec-{int(time.time())}@secretary.local
DTSTAMP:{datetime.utcnow().strftime(fmt)}
DTSTART:{start_dt.strftime(fmt)}
DTEND:{end_dt.strftime(fmt)}
SUMMARY:{summary}
DESCRIPTION:Follow-up reminder set by your AI Secretary.
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""
    return ics


def append_to_obsidian(task_text: str, due_date: str):
    """Appends task in Markdown format to Obsidian vault."""
    markdown_entry = f"- [ ] {task_text} 📅 {due_date}\n"
    os.makedirs(os.path.dirname(OBSIDIAN_TASKS_PATH), exist_ok=True)
    with open(OBSIDIAN_TASKS_PATH, "a") as f:
        f.write(markdown_entry)


def send_reply_with_ics(to_email: str, subject: str, body: str, ics_data: str):
    """Sends email reply with attached .ics invite."""
    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    msg['Subject'] = f"Re: {subject}" if not subject.lower().startswith("re:") else subject

    msg.attach(MIMEText(body, 'plain'))

    # Attach ICS File
    part = MIMEBase('text', 'calendar', method='REQUEST', name='invite.ics')
    part.set_payload(ics_data.encode('utf-8'))
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="invite.ics"')
    msg.attach(part)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)


def process_inbox():
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, 'UNSEEN')
        
        # Check if UNSEEN email search returned valid messages
        if status == 'OK' and messages[0]:
            for e_id in messages[0].split():
                _, msg_data = mail.fetch(e_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        sender = msg.get("From")
                        subject = msg.get("Subject") or "No Subject"

                        # Read Plaintext Body
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode(errors='ignore')
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode(errors='ignore')

                        print(f"📩 Processing request from: {sender}")

                        # Ask Gemini to extract details structured as JSON
                        prompt = f"""
                        Extract the task action and relative requested time from this email.
                        Current date/time: {datetime.now().isoformat()}
                        Email content: "{body}"

                        Respond strictly in JSON format:
                        {{
                            "task": "<description of task>",
                            "target_iso_date": "<ISO 8601 string of requested time>"
                        }}
                        """

                        response = client.models.generate_content(
                            model=GEMINI_MODEL,
                            contents=prompt,
                            config={"response_mime_type": "application/json"}
                        )

                        # Clean response text in case Gemini wraps JSON in markdown blocks
                        raw_json = response.text.strip().removeprefix("```json").removesuffix("```").strip()
                        data = json.loads(raw_json)

                        # Parse ISO date safely (handles 'Z' suffix if present)
                        iso_str = data["target_iso_date"].replace("Z", "+00:00")
                        raw_dt = datetime.fromisoformat(iso_str)

                        # Enforce Business Days/Hours
                        scheduled_dt = calculate_business_slot(raw_dt)
                        date_str = scheduled_dt.strftime("%Y-%m-%d %H:%M")

                        # 1. Update Obsidian
                        append_to_obsidian(data["task"], date_str)

                        # 2. Generate ICS & Email Reply
                        ics_content = create_ics_content(data["task"], scheduled_dt)
                        reply_body = (
                            f"Hello!\n\n"
                            f"I have logged your task in Obsidian:\n"
                            f"- Task: {data['task']}\n"
                            f"- Scheduled: {date_str}\n\n"
                            f"Attached is your calendar invite."
                        )

                        send_reply_with_ics(sender, subject, reply_body, ics_content)
                        print(f"✅ Successfully processed task: {data['task']}")

        mail.logout()
    except Exception as e:
        print(f"❌ Error during loop execution: {e}")


# --- Main Daemon Loop ---
if __name__ == "__main__":
    print("🤖 AI Secretary operational. Listening for incoming tasks...")
    while True:
        process_inbox()
        time.sleep(60)
