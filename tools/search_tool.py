import re
import ipaddress
from urllib.parse import urlparse
from tools.base import Tool
from core.tools import register_tool
from duckduckgo_search import AsyncDDGS
import httpx
from bs4 import BeautifulSoup
import html2text


@register_tool
class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the internet for information. Params: query or query|max_results (e.g., 'python async' or 'AI news|10')"

    async def run(self, params: str) -> str:
        """
        Search the web using DuckDuckGo and return detailed results.

        Args:
            params: Search query, optionally with |max_results suffix

        Returns:
            Formatted search results with titles, snippets, and URLs
        """
        if not params or not params.strip():
            return "Error: Search query cannot be empty"

        # Parse params for optional max_results
        if "|" in params:
            parts = params.rsplit("|", 1)
            query = parts[0].strip()
            try:
                max_results = int(parts[1].strip())
                max_results = min(max(1, max_results), 20)  # Clamp between 1-20
            except ValueError:
                query = params.strip()
                max_results = 5
        else:
            query = params.strip()
            max_results = 5

        try:
            # Use AsyncDDGS for async search
            async with AsyncDDGS() as ddgs:
                # Get results
                results = []
                async for result in ddgs.text(
                    query,
                    max_results=max_results,
                    safesearch='moderate'
                ):
                    results.append(result)

                if not results:
                    return f"No search results found for: {query}"

                # Format results concisely
                output = [f"Search results for '{query}':\n"]

                for i, result in enumerate(results, 1):
                    title = result.get('title', 'No title')
                    if len(title) > 60:
                        title = title[:60] + "..."

                    snippet = result.get('body', 'No description')
                    if len(snippet) > 150:
                        snippet = snippet[:150] + "..."

                    url = result.get('href', '')

                    output.append(f"{i}. {title}")
                    output.append(f"   {snippet}")
                    output.append(f"   URL: {url}\n")

                # Join and ensure we don't exceed reasonable context size
                result_text = "\n".join(output)
                if len(result_text) > 1500:
                    result_text = result_text[:1500] + "\n... [results truncated]"

                return result_text

        except Exception as e:
            return f"Error searching web: {str(e)}"


@register_tool
class WebSearchQuickTool(Tool):
    name = "quick_search"
    description = "Quick internet search returning only titles and URLs. Params: query or query|max_results"

    async def run(self, params: str) -> str:
        """
        Quick search returning minimal information to save context.
        """
        if not params or not params.strip():
            return "Error: Search query cannot be empty"

        # Parse params for optional max_results
        if "|" in params:
            parts = params.rsplit("|", 1)
            query = parts[0].strip()
            try:
                max_results = int(parts[1].strip())
                max_results = min(max(1, max_results), 20)
            except ValueError:
                query = params.strip()
                max_results = 5
        else:
            query = params.strip()
            max_results = 5

        try:
            async with AsyncDDGS() as ddgs:
                results = []
                async for result in ddgs.text(query, max_results=max_results, safesearch='moderate'):
                    results.append(result)

                if not results:
                    return f"No results for: {query}"

                output = [f"Quick results for '{query}':\n"]
                for i, result in enumerate(results, 1):
                    title = result.get('title', 'No title')
                    if len(title) > 50:
                        title = title[:50] + "..."
                    url = result.get('href', '')
                    output.append(f"{i}. {title} - {url}")

                return "\n".join(output)

        except Exception as e:
            return f"Error: {str(e)}"


@register_tool
class FetchWebpageTool(Tool):
    name = "fetch_webpage"
    description = "Fetch and read content from a webpage. Params: URL (e.g., 'https://example.com/article')"

    def _is_private_ip(self, ip_str: str) -> bool:
        """Check if IP address is private/localhost."""
        try:
            ip = ipaddress.ip_address(ip_str)
            return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        except ValueError:
            return False

    def _validate_url(self, url: str) -> tuple[bool, str]:
        """
        Validate URL for security.
        Returns: (is_valid, error_message)
        """
        try:
            parsed = urlparse(url)

            # Only allow HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False, f"Invalid protocol: {parsed.scheme}. Only HTTP/HTTPS allowed"

            # Check for hostname
            if not parsed.netloc:
                return False, "Invalid URL: no hostname"

            # Extract hostname (remove port if present)
            hostname = parsed.hostname
            if not hostname:
                return False, "Invalid URL: cannot extract hostname"

            # Block localhost variants
            localhost_patterns = ['localhost', '0.0.0.0', '127.', '::1', '0:0:0:0:0:0:0:1']
            if any(hostname.startswith(pattern) or hostname == pattern.strip('.') for pattern in localhost_patterns):
                return False, "Security: Cannot access localhost"

            # Check if hostname is an IP address
            # Try to resolve as IP
            try:
                if self._is_private_ip(hostname):
                    return False, f"Security: Cannot access private IP addresses ({hostname})"
            except Exception:
                # Not an IP, that's fine - it's a domain name
                pass

            # Block private IP ranges in domain names (rare but possible)
            private_ranges = ['10.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.',
                            '172.21.', '172.22.', '172.23.', '172.24.', '172.25.', '172.26.',
                            '172.27.', '172.28.', '172.29.', '172.30.', '172.31.', '192.168.']
            if any(hostname.startswith(pattern) for pattern in private_ranges):
                return False, f"Security: Cannot access private network ({hostname})"

            return True, ""

        except Exception as e:
            return False, f"Invalid URL: {str(e)}"

    async def run(self, params: str) -> str:
        """
        Fetch and extract clean text content from a webpage.

        Args:
            params: URL to fetch

        Returns:
            Cleaned text content from the webpage (max 3000 chars)
        """
        if not params or not params.strip():
            return "Error: URL cannot be empty"

        url = params.strip()

        # Validate URL
        is_valid, error_msg = self._validate_url(url)
        if not is_valid:
            return f"Error: {error_msg}"

        try:
            # Create async HTTP client with security settings
            async with httpx.AsyncClient(
                timeout=10.0,  # 10 second timeout
                follow_redirects=True,
                max_redirects=5,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; AssistantBot/1.0)'
                }
            ) as client:
                # Fetch the page
                response = await client.get(url)
                response.raise_for_status()

                # Check content type
                content_type = response.headers.get('content-type', '').lower()
                allowed_types = ['text/html', 'text/plain', 'application/json', 'application/xml', 'text/xml']

                if not any(allowed in content_type for allowed in allowed_types):
                    return f"Error: Unsupported content type: {content_type}. Only text-based content allowed."

                # Check content size (5MB limit)
                content_length = len(response.content)
                if content_length > 5 * 1024 * 1024:  # 5MB
                    return f"Error: Content too large ({content_length} bytes). Maximum 5MB allowed."

                # Get text content
                text = response.text

                # If HTML, parse and extract text
                if 'html' in content_type:
                    soup = BeautifulSoup(text, 'html.parser')

                    # Remove script, style, nav, footer, header elements
                    for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
                        element.decompose()

                    # Convert to markdown for better readability
                    h = html2text.HTML2Text()
                    h.ignore_links = False
                    h.ignore_images = True
                    h.ignore_emphasis = False
                    h.body_width = 0  # Don't wrap text

                    cleaned_text = h.handle(str(soup))
                else:
                    # For non-HTML content, use as-is
                    cleaned_text = text

                # Remove excessive whitespace
                cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)
                cleaned_text = cleaned_text.strip()

                # Truncate to 3000 chars to preserve context
                if len(cleaned_text) > 3000:
                    cleaned_text = cleaned_text[:3000] + "\n\n... [Content truncated at 3000 characters]"

                if not cleaned_text:
                    return "Error: No text content found on page"

                return f"Content from {url}:\n\n{cleaned_text}"

        except httpx.TimeoutException:
            return f"Error: Request timed out after 10 seconds for {url}"
        except httpx.HTTPStatusError as e:
            return f"Error: HTTP {e.response.status_code} for {url}"
        except httpx.RequestError as e:
            return f"Error: Failed to fetch {url}: {str(e)}"
        except Exception as e:
            return f"Error: {str(e)}"
