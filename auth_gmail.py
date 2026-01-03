#!/usr/bin/env python3
"""
Gmail OAuth Authorization Script
Run this to authorize each email account.
"""
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose"
]

BASE_DIR = Path(__file__).parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKENS_DIR = BASE_DIR / "tokens"

REDIRECT_URI = "http://localhost:8889/"

def authorize_account():
    if not CREDENTIALS_FILE.exists():
        print("ERROR: credentials.json not found!")
        return
    
    TOKENS_DIR.mkdir(exist_ok=True)
    
    print("\n=== Gmail OAuth Authorization ===\n")
    
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    auth_url, _ = flow.authorization_url(prompt="consent")
    
    print("1. Open this URL in your browser:\n")
    print(auth_url)
    print("\n2. Sign in and click Allow")
    print("3. You will be redirected to a page that wont load - thats OK!")
    print("4. Copy the ENTIRE URL from your browser address bar and paste it here:\n")
    
    redirect_response = input("Paste the full redirect URL: ").strip()
    
    # Extract the code from the URL
    parsed = urlparse(redirect_response)
    code = parse_qs(parsed.query).get("code", [None])[0]
    
    if not code:
        print("ERROR: Could not find authorization code in URL")
        return
    
    flow.fetch_token(code=code)
    creds = flow.credentials
    
    # Get the email address
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]
    
    # Save token
    token_file = TOKENS_DIR / f"{email}.json"
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    
    print(f"\nAuthorized: {email}")
    print(f"Token saved to: {token_file}")
    
    # List all authorized accounts
    accounts = [f.stem for f in TOKENS_DIR.glob("*.json")]
    print(f"\nAll authorized accounts - {len(accounts)} total:")
    for acc in accounts:
        print(f"  - {acc}")
    
    print("\nRun this script again to add another account.")

if __name__ == "__main__":
    authorize_account()
