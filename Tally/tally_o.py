import os
import httpx
from typing import Optional, List, Dict
from mcp.server.fastmcp import FastMCP

# --- Configuration ---
TALLY_API_KEY ="tly-vqiu7S7QXS7U2YNddkcQDFkiYb9DBqG2"
TALLY_API_BASE = "https://api.tally.so"

if not TALLY_API_KEY:
    raise ValueError("Set TALLY_API_KEY environment variable")

headers = {
    "Authorization": f"Bearer {TALLY_API_KEY}",
    "Content-Type": "application/json"
}

# --- Initialize MCP Server ---
mcp = FastMCP("tally-mcp")

# ------------------------------------------------
#            User Info
# ------------------------------------------------


@mcp.tool()
async def TALLY_GET_USER_INFO():
    """Get info about the authenticated user"""
    url = f"{TALLY_API_BASE}/users/me"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

# ------------------------------------------------
#            Workspaces
# ------------------------------------------------


@mcp.tool()
async def TALLY_GET_WORKSPACE(workspaceId: str):
    """
    Retrieve details of a specific workspace by ID.
    """
    url = f"{TALLY_API_BASE}/workspaces/{workspaceId}"

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)

        if r.status_code == 200:
            return r.json()

        if r.status_code == 401:
            return {"status": 401, "error": "Unauthorized - check your API token"}

        if r.status_code == 404:
            return {"status": 404, "error": f"Workspace {workspaceId} not found"}

        # fallback for unexpected responses
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code, "response": r.text}



@mcp.tool()
async def TALLY_LIST_WORKSPACES(page: int = 1):
    """
    Retrieve a paginated list of workspaces accessible to the authenticated user.
    """
    url = f"{TALLY_API_BASE}/workspaces?page={page}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

@mcp.tool()
async def TALLY_UPDATE_WORKSPACE(workspaceId: str, name: str):
    """
    Update the details of a specific workspace identified by its ID.
    """
    url = f"{TALLY_API_BASE}/workspaces/{workspaceId}"
    payload = {"name": name}

    async with httpx.AsyncClient() as client:
        r = await client.patch(url, headers=headers, json=payload)

        # 204 means success but no response body
        if r.status_code == 204:
            return {"status": 204, "message": "Workspace updated successfully"}

        # If unexpected response, return raw info
        try:
            return r.json()
        except Exception:
            return {"status": r.status_code, "response": r.text}


# ------------------------------------------------
#            Forms
# ------------------------------------------------

@mcp.tool()
async def TALLY_LIST_FORMS(page: int = 1, limit: int = 50, workspaceId: str = None):
    """
    Retrieve a paginated list of forms accessible to the authenticated user.
    
    """
    url = f"{TALLY_API_BASE}/forms"
    params = {
        "page": page,
        "limit": min(limit, 500)  # Max 500 per API restriction
    }
    if workspaceId:
        params["workspaceIds"] = workspaceId  # single workspace

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers, params=params)

        if r.status_code == 200:
            return r.json()  # returns items, page, limit, total, hasMore
        if r.status_code == 401:
            return {"status": 401, "error": "Unauthorized - invalid API key"}
        if r.status_code == 403:
            return {"status": 403, "error": "Forbidden - insufficient permissions"}

        # fallback for unexpected responses
        try:
            return {"status": r.status_code, "response": r.json()}
        except Exception:
            return {"status": r.status_code, "response": r.text}


@mcp.tool()
async def TALLY_DELETE_FORM(formId: str):
    """
    Delete a form by its ID.
    The form is moved to the trash.
    """
    url = f"{TALLY_API_BASE}/forms/{formId}"

    async with httpx.AsyncClient() as client:
        r = await client.delete(url, headers=headers)

        # 204 means success but no response body
        if r.status_code == 204:
            return {
                "status": 204,
                "message": f"Form '{formId}' deleted successfully"
            }

        # Handle common errors
        if r.status_code == 401:
            return {"status": 401, "error": "Unauthorized - invalid API key"}
        if r.status_code == 404:
            return {"status": 404, "error": f"Form '{formId}' not found"}
        if r.status_code == 403:
            return {"status": 403, "error": "Forbidden - insufficient permissions"}

        # Fallback for unexpected responses
        try:
            return {"status": r.status_code, "response": r.json()}
        except Exception:
            return {"status": r.status_code, "response": r.text}

@mcp.tool()
async def TALLY_GET_FORM(formId: str):
    """
    Retrieve a single form by its ID with all blocks and settings.
    """
    url = f"{TALLY_API_BASE}/forms/{formId}"

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)

        if r.status_code == 200:
            return r.json()  # Full form object with blocks, settings, etc.

        if r.status_code == 401:
            return {"status": 401, "error": "Unauthorized - invalid API key"}
        if r.status_code == 404:
            return {"status": 404, "error": f"Form '{formId}' not found"}
        if r.status_code == 403:
            return {"status": 403, "error": "Forbidden - insufficient permissions"}

        # fallback for unexpected responses
        try:
            return {"status": r.status_code, "response": r.json()}
        except Exception:
            return {"status": r.status_code, "response": r.text}


from typing import List, Dict, Optional
import httpx

@mcp.tool()
async def TALLY_CREATE_FORM(
    status: str,
    blocks: List[Dict],  # required
    workspaceId: Optional[str] = None,
    templateId: Optional[str] = None,  # optional, can be omitted
    settings: Optional[Dict] = None
):
    """
    Create a new Tally form.
    """
    payload = {
        "status": status,
        "blocks": blocks
    }
    
    if workspaceId:
        payload["workspaceId"] = workspaceId
    if templateId:
        payload["templateId"] = templateId
    if settings:
        payload["settings"] = settings

    url = f"{TALLY_API_BASE}/forms"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code == 201:
            return r.json()
        try:
            return {"status": r.status_code, "response": r.json()}
        except Exception:
            return {"status": r.status_code, "response": r.text}

@mcp.tool()
async def TALLY_UPDATE_FORM(
    formId: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    blocks: Optional[List[Dict]] = None,
    settings: Optional[Dict] = None
):
    """
    Update a Tally form’s name, status, blocks, or settings.
    """
    url = f"{TALLY_API_BASE}/forms/{formId}"
    payload = {}

    if name:
        payload["name"] = name
    if status:
        payload["status"] = status
    if blocks:
        payload["blocks"] = blocks
    if settings:
        payload["settings"] = settings

    async with httpx.AsyncClient() as client:
        r = await client.patch(url, headers=headers, json=payload)

        if r.status_code == 200:
            return r.json()
        if r.status_code == 400:
            return {"status": 400, "error": "Bad request", "response": r.json()}
        if r.status_code == 401:
            return {"status": 401, "error": "Unauthorized - check API key"}
        if r.status_code == 403:
            return {"status": 403, "error": "Forbidden - insufficient permissions"}
        if r.status_code == 404:
            return {"status": 404, "error": f"Form '{formId}' not found"}

        # fallback for unexpected responses
        try:
            return {"status": r.status_code, "response": r.json()}
        except Exception:
            return {"status": r.status_code, "response": r.text}

# ------------------------------------------------
#            Webhooks
# ------------------------------------------------


# ------------------- RUN -------------------

if __name__ == "__main__":
    mcp.run()
