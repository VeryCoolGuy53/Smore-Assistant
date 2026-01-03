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
    description = "Search emails. Params: [account:]query (e.g., from:mom or work@gmail.com:subject:meeting)"
    
    async def run(self, params):
        if ":" in params and "@" in params.split(":")[0]:
            account, query = params.split(":", 1)
        else:
            account = None
            query = params
        
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
    description = "Read email content. Params: [account:]search query to find the email"
    
    async def run(self, params):
        if ":" in params and "@" in params.split(":")[0]:
            account, query = params.split(":", 1)
        else:
            account = None
            query = params
        
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
    description = "Create email draft. Params: [from_account:]to|subject|body"
    
    async def run(self, params):
        if ":" in params and "@" in params.split(":")[0] and "|" in params:
            account, rest = params.split(":", 1)
        else:
            account = None
            rest = params
        
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
