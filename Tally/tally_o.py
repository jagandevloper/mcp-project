import os
import httpx
import logging
from typing import Optional, List, Dict
from mcp.server.fastmcp import FastMCP

# ---------------- CONFIG ----------------
TALLY_API_KEY = os.getenv("TALLY_API_KEY")
TALLY_API_BASE = "https://api.tally.so"

if not TALLY_API_KEY:
    raise ValueError("Set TALLY_API_KEY environment variable or inline key")

HEADERS = {"Authorization": f"Bearer {TALLY_API_KEY}", "Content-Type": "application/json"}

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------- MCP SERVER ----------------
mcp = FastMCP("tally-mcp")

# ---------------- HTTP HELPER ----------------
async def safe_request(method: str, url: str, params: dict = None, json: dict = None):
    """
    Wrapper for all HTTP requests with consistent error handling.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.request(method, url, headers=HEADERS, params=params, json=json)

            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 204:
                return {"status": 204, "message": "Success (no content)"}
            if r.status_code == 401:
                return {"status": 401, "error": "Unauthorized - check API key"}
            if r.status_code == 403:
                return {"status": 403, "error": "Forbidden - insufficient permissions"}
            if r.status_code == 404:
                return {"status": 404, "error": "Not found"}
            if r.status_code == 400:
                return {"status": 400, "error": "Bad request", "response": r.json()}

            # fallback
            try:
                return {"status": r.status_code, "response": r.json()}
            except Exception:
                return {"status": r.status_code, "response": r.text}

        except httpx.RequestError as e:
            logging.error(f"HTTP Request failed: {e}")
            return {"status": 500, "error": str(e)}

# ------------------------------------------------
#            User Info
# ------------------------------------------------
@mcp.tool()
async def TALLY_GET_USER_INFO():
    """Get info about the authenticated user"""
    return await safe_request("GET", f"{TALLY_API_BASE}/users/me")

# ------------------------------------------------
#            Workspaces
# ------------------------------------------------
@mcp.tool()
async def TALLY_GET_WORKSPACE(workspaceId: str):
    """Get info about a workspace"""
    return await safe_request("GET", f"{TALLY_API_BASE}/workspaces/{workspaceId}")

@mcp.tool()
async def TALLY_LIST_WORKSPACES(page: int = 1):
    """List all workspaces"""
    return await safe_request("GET", f"{TALLY_API_BASE}/workspaces", params={"page": page})

@mcp.tool()
async def TALLY_UPDATE_WORKSPACE(workspaceId: str, name: str):
    return await safe_request("PATCH", f"{TALLY_API_BASE}/workspaces/{workspaceId}", json={"name": name})

# ------------------------------------------------
#            Forms
# ------------------------------------------------
@mcp.tool()
async def TALLY_LIST_FORMS(page: int = 1, limit: int = 50, workspaceId: str = None):
    """List all forms"""
    params = {"page": page, "limit": min(limit, 500)}
    if workspaceId:
        params["workspaceIds"] = workspaceId
    return await safe_request("GET", f"{TALLY_API_BASE}/forms", params=params)

@mcp.tool()
async def TALLY_DELETE_FORM(formId: str):
    """Delete a form"""
    return await safe_request("DELETE", f"{TALLY_API_BASE}/forms/{formId}")

@mcp.tool()
async def TALLY_GET_FORM(formId: str):
    """Get a form"""
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}")

@mcp.tool()
async def TALLY_CREATE_FORM(
    status: str,
    blocks: List[Dict],
    workspaceId: Optional[str] = None,
    templateId: Optional[str] = None,
    settings: Optional[Dict] = None
):
    """Create a form"""
    payload = {"status": status, "blocks": blocks}
    if workspaceId: payload["workspaceId"] = workspaceId
    if templateId: payload["templateId"] = templateId
    if settings: payload["settings"] = settings
    return await safe_request("POST", f"{TALLY_API_BASE}/forms", json=payload)

@mcp.tool()
async def TALLY_UPDATE_FORM(
    formId: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    blocks: Optional[List[Dict]] = None,
    settings: Optional[Dict] = None
):
    """Update a form"""
    payload = {}
    if name: payload["name"] = name
    if status: payload["status"] = status
    if blocks: payload["blocks"] = blocks
    if settings: payload["settings"] = settings
    return await safe_request("PATCH", f"{TALLY_API_BASE}/forms/{formId}", json=payload)

@mcp.tool()
async def TALLY_LIST_FORM_QUESTIONS(formId: str) -> Dict:
    """List all questions for a form"""
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}/questions")

@mcp.tool()
async def TALLY_LIST_SUBMISSIONS(
    formId: str,
    page: int = 1,
    filter: Optional[str] = "all",
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    afterId: Optional[str] = None
) -> Dict:
    """List all submissions for a form"""
    params = {"page": page, "filter": filter}
    if startDate: params["startDate"] = startDate
    if endDate: params["endDate"] = endDate
    if afterId: params["afterId"] = afterId
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}/submissions", params=params)

@mcp.tool()
async def TALLY_GET_SUBMISSION(formId: str, submissionId: str) -> Dict:
    """Get a submission"""
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}/submissions/{submissionId}")

@mcp.tool()
async def TALLY_DELETE_SUBMISSION(formId: str, submissionId: str) -> Dict:  
    """Delete a submission"""
    return await safe_request("DELETE", f"{TALLY_API_BASE}/forms/{formId}/submissions/{submissionId}")

@mcp.tool()
async def TALLY_GET_FORM_SETTINGS(formId: str):
    """Get the settings for a form"""
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}")

# ------------------------------------------------
#            Webhooks
# ------------------------------------------------
@mcp.tool()
async def TALLY_LIST_WEBHOOKS(page: int = 1, limit: int = 25) -> Dict:
    """List all webhooks"""
    return await safe_request("GET", f"{TALLY_API_BASE}/webhooks", params={"page": page, "limit": min(limit, 100)})

@mcp.tool()
async def TALLY_CREATE_WEBHOOK(
    formId: str,
    url: str,
    eventTypes: List[str] = ["FORM_RESPONSE"],
    signingSecret: Optional[str] = None,
    httpHeaders: Optional[List[Dict[str, str]]] = None,
    externalSubscriber: Optional[str] = None
):
    """Create a webhook"""
    payload = {"formId": formId, "url": url, "eventTypes": eventTypes}
    if signingSecret: payload["signingSecret"] = signingSecret
    if httpHeaders: payload["httpHeaders"] = httpHeaders
    if externalSubscriber: payload["externalSubscriber"] = externalSubscriber
    return await safe_request("POST", f"{TALLY_API_BASE}/webhooks", json=payload)

@mcp.tool()
async def TALLY_UPDATE_WEBHOOK(
    webhookId: str,
    formId: str,
    url: str,
    eventTypes: List[str] = ["FORM_RESPONSE"],
    isEnabled: bool = True,
    signingSecret: Optional[str] = None,
    httpHeaders: Optional[List[Dict[str, str]]] = None
):
    """Update a webhook"""
    payload = {"formId": formId, "url": url, "eventTypes": eventTypes, "isEnabled": isEnabled}
    if signingSecret: payload["signingSecret"] = signingSecret
    if httpHeaders: payload["httpHeaders"] = httpHeaders
    return await safe_request("PATCH", f"{TALLY_API_BASE}/webhooks/{webhookId}", json=payload)

@mcp.tool()
async def TALLY_DELETE_WEBHOOK(webhookId: str):
    """Delete a webhook"""
    return await safe_request("DELETE", f"{TALLY_API_BASE}/webhooks/{webhookId}")

@mcp.tool()
async def TALLY_LIST_WEBHOOK_EVENTS(webhookId: str, page: Optional[int] = 1):
    """List all events for a webhook"""
    return await safe_request("GET", f"{TALLY_API_BASE}/webhooks/{webhookId}/events", params={"page": page})

# ------------------- RUN -------------------
if __name__ == "__main__":
    mcp.run()
