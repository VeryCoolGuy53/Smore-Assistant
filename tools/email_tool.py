import os
import base64
from email.mime.text import MIMEText
from pathlib import Path
from tools.base import Tool
from core.tools import register_tool

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]

BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKENS_DIR = BASE_DIR / "tokens"

_services = {}

def get_authorized_accounts():
    if not TOKENS_DIR.exists():
        return []
    return [f.stem for f in TOKENS_DIR.glob("*.json")]

def get_gmail_service(account=None):
    global _services
    
    if not CREDENTIALS_FILE.exists():
        return None, "credentials.json not found. Download from Google Cloud Console."
    
    accounts = get_authorized_accounts()
    
    if not accounts:
        return None, "No accounts authorized yet. Run: python ~/assistant/auth_gmail.py"
    
    if account is None:
        account = accounts[0]
    else:
        account_lower = account.lower()
        matches = [a for a in accounts if account_lower in a.lower()]
        if not matches:
            return None, f"Account not found. Available: {', '.join(accounts)}"
        account = matches[0]
    
    if account in _services:
        return _services[account], account
    
    token_file = TOKENS_DIR / f"{account}.json"
    creds = None
    
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        else:
            return None, f"Token expired for {account}. Re-run auth_gmail.py"
    
    service = build("gmail", "v1", credentials=creds)
    _services[account] = service
    return service, account

@register_tool
class ListAccountsTool(Tool):
    name = "list_email_accounts"
    description = "List all authorized email accounts"
    
    async def run(self, params):
        accounts = get_authorized_accounts()
        if not accounts:
            return "No email accounts authorized yet."
        return f"Authorized accounts: {', '.join(accounts)}"

@register_tool
class SearchEmailsTool(Tool):
    name = "search_emails"
    description = "Search emails IN a specific account. Format: 'account@email.com query' or 'account@email.com:query'. IMPORTANT: Put the account FIRST, then the Gmail search query. Examples: 'ytsmore27@gmail.com subject:GPU' searches the ytsmore27 account for emails about GPU. 'ytsmore27@gmail.com from:ebay' searches ytsmore27 account for emails FROM ebay."

    async def run(self, params):
        # Parse account prefix - support both "account query" and "account:query" formats
        # IMPORTANT: Account prefix must be at the VERY START (not Gmail query syntax like "from:email@domain")
        account = None
        query = params

        # Check if params starts with an email address (not preceded by query keywords)
        # Common Gmail query keywords that contain `:` before the email
        gmail_keywords = ['from:', 'to:', 'cc:', 'bcc:', 'subject:', 'in:', 'is:', 'has:', 'after:', 'before:']

        # If params starts with a Gmail keyword, treat entire params as query (no account prefix)
        starts_with_keyword = any(params.lower().startswith(kw) for kw in gmail_keywords)

        if not starts_with_keyword:
            first_word = params.split(None, 1)[0] if params else ""

            # Space-separated format: "email@domain query"
            if "@" in first_word and ":" not in first_word:
                parts = params.split(None, 1)
                if len(parts) == 2:
                    account = parts[0]
                    query = parts[1]
            # Colon-separated format: "email@domain:query" (email must come FIRST)
            elif ":" in params and "@" in params:
                colon_pos = params.index(":")
                at_pos = params.index("@")
                # @ must come before : AND be in the first word (before any space)
                if at_pos < colon_pos and (":  " not in params or at_pos < params.index(" ")):
                    account, query = params.split(":", 1)
        
        service, acct = get_gmail_service(account)
        if service is None:
            return acct
        
        try:
            results = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
            messages = results.get("messages", [])
            
            if not messages:
                return f"No emails found for query in {acct}"
            
            output = [f"Found {len(messages)} email(s) in {acct}:"]
            
            for msg in messages:
                msg_data = service.users().messages().get(
                    userId="me", id=msg["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "Date"]
                ).execute()
                
                headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
                subject = headers.get("Subject", "(no subject)")[:50]
                sender = headers.get("From", "unknown")[:30]
                date = headers.get("Date", "")[:16]
                
                output.append(f"- \"{subject}\" from {sender} ({date})")
            
            return "\n".join(output)
            
        except Exception as e:
            return f"Error searching: {str(e)}"

@register_tool
class ReadEmailTool(Tool):
    name = "read_email"
    description = "Read email content from a specific account. Format: 'account@email.com query'. Put account FIRST, then Gmail query. Example: 'ytsmore27@gmail.com subject:GPU order' reads from ytsmore27 account."

    async def run(self, params):
        # Parse account prefix - same logic as SearchEmailsTool
        account = None
        query = params

        # Gmail query keywords that shouldn't be confused with account prefix
        gmail_keywords = ['from:', 'to:', 'cc:', 'bcc:', 'subject:', 'in:', 'is:', 'has:', 'after:', 'before:']
        starts_with_keyword = any(params.lower().startswith(kw) for kw in gmail_keywords)

        if not starts_with_keyword:
            first_word = params.split(None, 1)[0] if params else ""

            # Space-separated: "email@domain query"
            if "@" in first_word and ":" not in first_word:
                parts = params.split(None, 1)
                if len(parts) == 2:
                    account = parts[0]
                    query = parts[1]
            # Colon-separated: "email@domain:query"
            elif ":" in params and "@" in params:
                colon_pos = params.index(":")
                at_pos = params.index("@")
                if at_pos < colon_pos and (" " not in params or at_pos < params.index(" ")):
                    account, query = params.split(":", 1)
        
        service, acct = get_gmail_service(account)
        if service is None:
            return acct
        
        try:
            results = service.users().messages().list(userId="me", q=query, maxResults=1).execute()
            messages = results.get("messages", [])
            
            if not messages:
                return "Email not found."
            
            msg = service.users().messages().get(userId="me", id=messages[0]["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "unknown")
            date = headers.get("Date", "")
            
            body = ""
            payload = msg["payload"]
            if "parts" in payload:
                for part in payload["parts"]:
                    if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        break
            elif "body" in payload and "data" in payload["body"]:
                body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
            
            if len(body) > 500:
                body = body[:500] + "... [truncated]"
            
            return f"From: {sender}\nSubject: {subject}\nDate: {date}\n\n{body}"
            
        except Exception as e:
            return f"Error reading email: {str(e)}"

@register_tool
class CreateDraftTool(Tool):
    name = "create_draft"
    description = "Create email draft. Params: [from_account ]to|subject|body or [from_account:]to|subject|body"

    async def run(self, params):
        # Parse account prefix - same logic but watch for | separator
        account = None
        rest = params

        first_word = params.split(None, 1)[0] if params else ""

        if "@" in first_word and ":" not in first_word and "|" in params:
            parts = params.split(None, 1)
            if len(parts) == 2:
                account = parts[0]
                rest = parts[1]
        elif ":" in params and "@" in params and "|" in params:
            colon_pos = params.index(":")
            pipe_pos = params.index("|")
            at_pos = params.index("@")

            if at_pos < colon_pos < pipe_pos:
                account, rest = params.split(":", 1)
        
        parts = rest.split("|")
        if len(parts) < 3:
            return "Error: Format is [from_account:]to|subject|body"
        
        to_addr = parts[0].strip()
        subject = parts[1].strip()
        body = "|".join(parts[2:]).strip()
        
        service, acct = get_gmail_service(account)
        if service is None:
            return acct
        
        try:
            message = MIMEText(body)
            message["to"] = to_addr
            message["subject"] = subject
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
            
            return f"Draft created in {acct}! To: {to_addr}, Subject: {subject}. Check Gmail Drafts."
            
        except Exception as e:
            return f"Error creating draft: {str(e)}"
