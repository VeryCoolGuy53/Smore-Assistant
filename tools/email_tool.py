import os
import re
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

def strip_html_tags(html):
    """
    Strip HTML tags and decode entities to get plain text content.

    Args:
        html: HTML string

    Returns:
        str: Plain text content
    """
    import html as html_module

    # Remove script and style elements
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)

    # Replace common block elements with newlines
    text = re.sub(r'</(div|p|br|tr|h[1-6]|li)>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

    # Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = html_module.unescape(text)

    # Clean up whitespace
    lines = [line.strip() for line in text.split('\n')]
    lines = [line for line in lines if line]  # Remove empty lines
    text = '\n'.join(lines)

    return text

def extract_body_from_payload(payload):
    """
    Recursively extract email body from Gmail API payload.
    Handles nested multipart structures (multipart/alternative, multipart/related, etc.)

    Args:
        payload: Gmail message payload dict

    Returns:
        tuple: (plain_text_body, html_body)
    """
    def extract_from_parts(parts, body_type):
        """Recursively search for specific MIME type in nested parts."""
        for part in parts:
            mime_type = part.get("mimeType", "")

            # Direct match - found the content!
            if mime_type == body_type:
                body_data = part.get("body", {}).get("data")
                if body_data:
                    return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

            # Nested multipart - recurse deeper
            if mime_type.startswith("multipart/") and "parts" in part:
                result = extract_from_parts(part["parts"], body_type)
                if result:
                    return result

        return None

    plain_body = None
    html_body = None

    # Handle nested parts structure
    if "parts" in payload:
        plain_body = extract_from_parts(payload["parts"], "text/plain")
        html_body = extract_from_parts(payload["parts"], "text/html")

    # Handle simple single-part messages
    elif "body" in payload and "data" in payload["body"]:
        mime_type = payload.get("mimeType", "")
        body_data = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        if mime_type == "text/plain":
            plain_body = body_data
        elif mime_type == "text/html":
            html_body = body_data

    return plain_body, html_body

@register_tool
class ReadEmailTool(Tool):
    name = "read_email"
    description = "Read email content from a specific account. Format: 'account@email.com query' or 'account@email.com query|offset'. Put account FIRST, then Gmail query. For long emails, use offset to read next chunk. Example: 'ytsmore27@gmail.com subject:GPU order' or 'ytsmore27@gmail.com subject:GPU order|2000' to read starting from char 2000."

    async def run(self, params):
        # Parse offset from params (format: query|offset)
        offset = 0
        if "|" in params:
            # Find the last | to handle cases where query itself might contain |
            last_pipe = params.rfind("|")
            offset_str = params[last_pipe + 1:].strip()
            if offset_str.isdigit():
                offset = int(offset_str)
                params = params[:last_pipe]

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
            
            payload = msg["payload"]

            # Extract email body using recursive parser (handles nested multipart structures)
            plain_body, html_body = extract_body_from_payload(payload)

            # Prefer plain text, fall back to HTML (strip tags if HTML-only)
            if plain_body:
                body = plain_body
            elif html_body:
                # Strip HTML tags to make it readable
                body = strip_html_tags(html_body)
            else:
                body = "[Email body could not be extracted]"

            # Extract URLs from HTML if we don't have plain text or to supplement it
            urls = []
            if html_body:
                # Extract URLs from href attributes
                url_pattern = r'href=["\']([^"\']+)["\']'
                urls = list(set(re.findall(url_pattern, html_body)))
                # Filter out common non-useful links (mailto, #anchors, etc.)
                urls = [url for url in urls if url.startswith('http')]

            # Also extract plain URLs from text body
            if body:
                text_url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                text_urls = re.findall(text_url_pattern, body)
                urls.extend(text_urls)
                urls = list(set(urls))  # Remove duplicates

            # Apply offset and truncation
            total_length = len(body)
            if offset >= total_length:
                return f"From: {sender}\nSubject: {subject}\nDate: {date}\n\nOffset {offset} exceeds email length ({total_length} chars). Email ends at char {total_length}."

            body = body[offset:]
            chunk_size = 2000

            if len(body) > chunk_size:
                body = body[:chunk_size]
                next_offset = offset + chunk_size
                truncation_msg = f"... [truncated at char {next_offset} of {total_length}, use offset {next_offset} to read more]"
                body += truncation_msg
            elif offset > 0:
                # This is a continuation chunk that's complete
                body = f"[Continuing from char {offset}]\n" + body

            # Build response with links section
            response = f"From: {sender}\nSubject: {subject}\nDate: {date}\n\n{body}"

            # Add links section if URLs were found (only on first chunk, not continuations)
            if urls and offset == 0:
                response += "\n\n--- Links found in email ---\n"
                for i, url in enumerate(urls[:10], 1):  # Limit to 10 links to avoid overwhelming
                    response += f"{i}. {url}\n"
                if len(urls) > 10:
                    response += f"... and {len(urls) - 10} more links"

            return response
            
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
