import imaplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import os
from datetime import datetime
from tools.base import Tool
from core.tools import register_tool

# Load credentials from environment or .env file
def load_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value

load_env()

GMAIL_USER = os.environ.get('GMAIL_USER', '')
GMAIL_APP_PASSWORD = os.environ.get('GMAIL_APP_PASSWORD', '')

def decode_mime_header(header):
    """Decode email header properly."""
    if header is None:
        return ''
    decoded = decode_header(header)
    parts = []
    for content, charset in decoded:
        if isinstance(content, bytes):
            parts.append(content.decode(charset or 'utf-8', errors='replace'))
        else:
            parts.append(content)
    return ''.join(parts)

@register_tool
class SearchEmailsTool(Tool):
    name = "search_emails"
    description = "Search Gmail. Params: search query (e.g., 'from:mom', 'subject:meeting', 'newer_than:7d')"

    async def run(self, params: str) -> str:
        if not GMAIL_USER or not GMAIL_APP_PASSWORD:
            return "Error: Gmail credentials not configured. Add GMAIL_USER and GMAIL_APP_PASSWORD to .env file."

        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select('INBOX')

            # Build IMAP search query
            # Convert common search terms to IMAP format
            query = params.strip()
            if query.startswith('from:'):
                imap_query = f'FROM "{query[5:]}"'
            elif query.startswith('subject:'):
                imap_query = f'SUBJECT "{query[8:]}"'
            elif query.startswith('newer_than:'):
                # e.g., newer_than:7d
                imap_query = 'ALL'  # Simplified, would need date calc
            else:
                # General search
                imap_query = f'OR FROM "{query}" SUBJECT "{query}"'

            # Search emails
            status, messages = mail.search(None, imap_query)

            if status != 'OK':
                mail.logout()
                return f"Search failed: {status}"

            email_ids = messages[0].split()
            if not email_ids:
                mail.logout()
                return "No emails found matching your search."

            # Get last 5 emails (most recent)
            email_ids = email_ids[-5:]
            results = []

            for eid in reversed(email_ids):
                status, msg_data = mail.fetch(eid, '(RFC822)')
                if status != 'OK':
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                subject = decode_mime_header(msg['Subject'])
                sender = decode_mime_header(msg['From'])
                date = msg['Date']

                # Truncate long fields
                if len(subject) > 50:
                    subject = subject[:47] + '...'
                if len(sender) > 30:
                    sender = sender[:27] + '...'

                results.append(f"- '{subject}' from {sender} ({date[:16]})")

            mail.logout()

            count = len(results)
            return f"Found {count} email(s):\n" + "\n".join(results)

        except Exception as e:
            return f"Error searching emails: {str(e)}"

@register_tool
class ReadEmailTool(Tool):
    name = "read_email"
    description = "Read an email's content. Params: subject or sender to identify the email"

    async def run(self, params: str) -> str:
        if not GMAIL_USER or not GMAIL_APP_PASSWORD:
            return "Error: Gmail credentials not configured."

        try:
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select('INBOX')

            # Search for the email
            query = params.strip()
            status, messages = mail.search(None, f'OR FROM "{query}" SUBJECT "{query}"')

            if status != 'OK' or not messages[0]:
                mail.logout()
                return "Email not found."

            # Get the most recent match
            email_id = messages[0].split()[-1]
            status, msg_data = mail.fetch(email_id, '(RFC822)')

            if status != 'OK':
                mail.logout()
                return "Failed to fetch email."

            msg = email.message_from_bytes(msg_data[0][1])
            subject = decode_mime_header(msg['Subject'])
            sender = decode_mime_header(msg['From'])
            date = msg['Date']

            # Get body
            body = ''
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        body = part.get_payload(decode=True).decode('utf-8', errors='replace')
                        break
            else:
                body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

            # Truncate body to save context
            if len(body) > 500:
                body = body[:500] + '... [truncated]'

            mail.logout()
            return f"From: {sender}\nSubject: {subject}\nDate: {date}\n\n{body}"

        except Exception as e:
            return f"Error reading email: {str(e)}"

@register_tool
class CreateDraftTool(Tool):
    name = "create_draft"
    description = "Create email draft in Gmail. Params: to|subject|body (separated by |)"

    async def run(self, params: str) -> str:
        if not GMAIL_USER or not GMAIL_APP_PASSWORD:
            return "Error: Gmail credentials not configured."

        try:
            parts = params.split('|')
            if len(parts) < 3:
                return "Error: Format is to|subject|body"

            to_addr = parts[0].strip()
            subject = parts[1].strip()
            body = '|'.join(parts[2:]).strip()  # Body might contain |

            # Create message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = to_addr
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            # Connect to Gmail IMAP and save as draft
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select('[Gmail]/Drafts')

            # Append to drafts
            mail.append('[Gmail]/Drafts', '', imaplib.Time2Internaldate(datetime.now()), msg.as_bytes())
            mail.logout()

            return f"Draft created! To: {to_addr}, Subject: '{subject}'. Check Gmail Drafts to review and send."

        except Exception as e:
            return f"Error creating draft: {str(e)}"
