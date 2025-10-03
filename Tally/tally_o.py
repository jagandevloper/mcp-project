import os
import httpx
import logging
import uuid
from typing import Optional, List, Dict
from mcp.server.fastmcp import FastMCP

# ---------------- CONFIG ----------------
# IMPORTANT: Never commit API keys to version control!
# Use environment variables in production:
TALLY_API_KEY = os.getenv("TALLY_API_KEY")
TALLY_API_BASE = "https://api.tally.so"

if not TALLY_API_KEY:
    raise ValueError("Set TALLY_API_KEY environment variable or inline key")

# Headers for all API requests
HEADERS = {"Authorization": f"Bearer {TALLY_API_KEY}", "Content-Type": "application/json"}

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------- MCP SERVER ----------------
mcp = FastMCP("tally-mcp")


# ---------------- HTTP HELPER ----------------
async def safe_request(method: str, url: str, params: dict = None, json: dict = None):
    """
    Wrapper for all HTTP requests with consistent error handling.
    
    IMPORTANT NOTES FOR DEVELOPERS:
    1. Always use this function for API calls - don't make direct HTTP requests
    2. This function handles authentication, timeouts, and error responses
    3. Returns parsed JSON on success, error dict on failure
    4. Timeout is set to 30 seconds - adjust if needed for large requests
    
    Args:
        method: HTTP method (GET, POST, PATCH, DELETE)
        url: Full API endpoint URL
        params: Query parameters (for GET requests)
        json: Request body (for POST/PATCH requests)
    
    Returns:
        dict: API response or error information
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
    """
    Retrieve details about the authenticated Tally user.

    This tool fetches information about the currently authenticated 
    Tally account (the user linked with your API credentials). 
    Useful for verifying account identity, email, and permissions.

    Args:
        None

    Returns:
        dict: User information including:
            - id (str): Unique user ID.
            - name (str): Display name of the user.
            - email (str): Associated email address.
            - avatarUrl (str, optional): Profile picture URL.
            - createdAt (str): Account creation timestamp.
            - other metadata depending on the API.
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/users/me")

# ------------------------------------------------
#            Workspaces
# ------------------------------------------------
@mcp.tool()
async def TALLY_GET_WORKSPACE(workspaceId: str):
    """
    Retrieve details of a specific Tally workspace.

    This tool fetches information about a workspace using its unique ID.
    Useful for inspecting workspace metadata, such as its name, members,
    and configuration before creating or managing forms inside it.

    Args:
        workspaceId (str): The unique identifier of the workspace to fetch. 
                           (Get workspace IDs from TALLY_LIST_WORKSPACES)

    Returns:
        dict: Workspace information including:
            - id (str): Unique workspace ID.
            - name (str): Name of the workspace.
            - createdAt (str): Timestamp when the workspace was created.
            - owner (dict): Details of the workspace owner.
            - members (list): List of users with access to the workspace.
            - other metadata depending on the API.
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/workspaces/{workspaceId}")

@mcp.tool()
async def TALLY_LIST_WORKSPACES(page: int = 1):
    """
    List all available Tally workspaces for the authenticated user.

    This tool retrieves a paginated list of workspaces that the authenticated
    user has access to. Each workspace contains metadata such as its ID,
    name, creation time, owner, and members.

    Args:
        page (int, optional): Page number for paginated results. 
                              Defaults to 1. Each page contains a limited 
                              number of workspaces as defined by the API.

    Returns:
        dict: A dictionary with paginated workspace data including:
            - data (list): List of workspace objects.
                * id (str): Unique workspace ID.
                * name (str): Workspace name.
                * createdAt (str): Timestamp of creation.
                * owner (dict): Owner details.
                * members (list): Users with access to the workspace.
            - pagination (dict): Information about current page, total items, 
                                 and next/previous pages if available.
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/workspaces", params={"page": page})

@mcp.tool()
async def TALLY_UPDATE_WORKSPACE(workspaceId: str, name: str):
    """
    Update the name of an existing Tally workspace.

    This tool allows renaming a workspace identified by its unique ID.
    Only the workspace owner or a user with the necessary permissions
    can perform this operation.

    Args:
        workspaceId (str): Unique ID of the workspace to be updated.
        name (str): The new name for the workspace.

    Returns:
        dict: A dictionary containing updated workspace information, including:
            - id (str): Workspace ID.
            - name (str): Updated name of the workspace.
            - createdAt (str): Timestamp of creation.
            - updatedAt (str): Timestamp of the update.
            - owner (dict): Details of the owner.
            - members (list): Users with access to the workspace.

    Raises:
        400 Bad Request: If the name is invalid or request is malformed.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission to update the workspace.
        404 Not Found: If the workspace does not exist.
    """
    return await safe_request("PATCH", f"{TALLY_API_BASE}/workspaces/{workspaceId}", json={"name": name})

# ------------------------------------------------
#            Forms
# ------------------------------------------------
@mcp.tool()
async def TALLY_LIST_FORMS(page: int = 1, limit: int = 50, workspaceId: str = None):
    """
    List forms available in Tally.

    This tool retrieves a paginated list of forms from the authenticated
    Tally account. Forms can optionally be filtered by workspace.

    Args:
        page (int, optional): The page number of results to retrieve. Defaults to 1.
        limit (int, optional): Number of forms per page (max 500). Defaults to 50.
        workspaceId (str, optional): If provided, only forms belonging to
            the specified workspace will be returned.

    Returns:
        dict: A dictionary containing:
            - data (list): A list of form objects. Each form includes:
                - id (str): Form ID.
                - name (str): Form title.
                - status (str): "DRAFT" or "PUBLISHED".
                - createdAt (str): Creation timestamp.
                - updatedAt (str): Last updated timestamp.
                - workspaceId (str): Workspace the form belongs to.
            - pagination (dict): Includes current page, total pages, and limit.

    Raises:
        400 Bad Request: If invalid parameters are provided.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have access to the workspace.
        404 Not Found: If no forms are found for the given parameters.
    """
    params = {"page": page, "limit": min(limit, 500)}
    if workspaceId:
        params["workspaceIds"] = workspaceId
    return await safe_request("GET", f"{TALLY_API_BASE}/forms", params=params)

@mcp.tool()
async def TALLY_DELETE_FORM(formId: str):
    """
    Delete a form from Tally.

    This tool permanently deletes a form from the authenticated user's
    Tally workspace. Once deleted, the form and its submissions cannot
    be recovered.

    Args:
        formId (str): The unique ID of the form to delete.

    Returns:
        dict: A dictionary containing:
            - status (int): HTTP status code (204 for success).
            - message (str): Confirmation message (e.g., "Success").
            - error (str, optional): Error message if deletion failed.

    Raises:
        400 Bad Request: If the form ID is invalid.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission to delete the form.
        404 Not Found: If the form with the given ID does not exist.
    """
    return await safe_request("DELETE", f"{TALLY_API_BASE}/forms/{formId}")

@mcp.tool()
async def TALLY_GET_FORM(formId: str):
    """
    Retrieve details of a specific form from Tally.

    This tool fetches the full configuration of a form, including its
    title, blocks, settings, and status.

    Args:
        formId (str): The unique ID of the form to retrieve.

    Returns:
        dict: A dictionary containing the form details:
            - id (str): Unique ID of the form.
            - name (str): Name of the form.
            - status (str): Form status ("DRAFT" or "PUBLISHED").
            - blocks (list): List of blocks (questions, inputs, etc.).
            - settings (dict): Form settings (language, redirect URL, etc.).

    Raises:
        400 Bad Request: If the form ID is invalid.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission to view the form.
        404 Not Found: If the form with the given ID does not exist.
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}")

@mcp.tool()
async def TALLY_CREATE_FORM(
    status: str,
    blocks: List[Dict],
    workspaceId: Optional[str] = None,
    templateId: Optional[str] = None,
    settings: Optional[Dict] = None
):
    """
    Create a new form in Tally.

    This tool creates a form with the specified status, blocks, and optional 
    workspace, template, or settings. Each block must include a valid structure 
    with a UUID, type, groupUuid, groupType, and payload.

    Args:
        status (str): The initial status of the form. Must be one of:
            - "DRAFT"
            - "PUBLISHED"
        blocks (List[Dict]): Ordered list of block definitions that make up the form.
            Example block:
            {
                "uuid": "deeea064-1088-464d-b1a1-3d2964217edc",
                "type": "FORM_TITLE",
                "groupUuid": "903682df-ab0a-4606-867a-c38038e2568d",
                "groupType": "TEXT",
                "payload": {
                    "title": "Customer Feedback",
                    "safeHTMLSchema": [["Customer Feedback"]]
                }
            }
        workspaceId (Optional[str]): ID of the workspace where the form will be created.
        templateId (Optional[str]): ID of the template to base the form on.
        settings (Optional[Dict]): Additional form settings such as language, 
            redirectOnCompletion, isClosed, etc.

    Returns:
        dict: Information about the newly created form:
            - id (str): Unique ID of the created form.
            - name (str): Form name.
            - status (str): Current form status.
            - blocks (list): Block definitions included in the form.
            - settings (dict): Applied settings.

    Raises:
        400 Bad Request: If block structure is invalid or required fields are missing.
        401 Unauthorized: If the API key is invalid or missing.
        403 Forbidden: If the user does not have permission.
        404 Not Found: If the specified workspace or template does not exist.

    # ---------------- BLOCK STRUCTURE ----------------
    CORRECT BLOCK STRUCTURE:
    {
        "uuid": "unique-uuid-here",
        "type": "FORM_TITLE",  # or INPUT_TEXT, TITLE, etc.
        "groupUuid": "different-uuid-here",
        "groupType": "TEXT",  # Must match block type
        "payload": {
            "title": "Form Title",
            "safeHTMLSchema": [["Form Title"]]
        }
    }
    
    ❌ COMMON MISTAKES:
    - Don't use the same UUID for uuid and groupUuid
    - Don't forget the safeHTMLSchema for text blocks
    - Don't use wrong groupType values
    - Don't create forms with empty blocks array
    """
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
    """
    Update an existing Tally form.

    This tool updates an existing form identified by `formId`. You can update 
    its name, status, block definitions, and/or settings. Only the provided 
    fields will be modified; omitted arguments remain unchanged.

    Args:
        formId (str): Unique ID of the form to update (from TALLY_LIST_FORMS or TALLY_GET_FORM).
        name (Optional[str]): New name of the form.
        status (Optional[str]): Updated status of the form. Must be one of:
            - "DRAFT"
            - "PUBLISHED"
            - "DELETED"
        blocks (Optional[List[Dict]]): New block definitions for the form. If provided, 
            each block must have:
            {
                "uuid": "existing-or-new-uuid",
                "type": "FORM_TITLE | INPUT_TEXT | TITLE | ...",
                "groupUuid": "different-uuid",
                "groupType": "TEXT | INPUT_TEXT | QUESTION | ...",
                "payload": {...}  # block-specific payload
            }
        settings (Optional[Dict]): Updated form settings such as `isClosed`, 
            `redirectOnCompletion`, `language`, etc.

    Returns:
        dict: Updated form details:
            - id (str): Form ID.
            - name (str): Updated form name.
            - status (str): Updated form status.
            - blocks (list): Updated block definitions.
            - settings (dict): Updated form settings.

    Raises:
        400 Bad Request: If block structure is invalid or required fields are missing.
        401 Unauthorized: If the API key is invalid or missing.
        403 Forbidden: If the user does not have permission.
        404 Not Found: If the formId does not exist.
    """
    payload = {}
    if name: payload["name"] = name
    if status: payload["status"] = status
    if blocks: payload["blocks"] = blocks
    if settings: payload["settings"] = settings
    return await safe_request("PATCH", f"{TALLY_API_BASE}/forms/{formId}", json=payload)

@mcp.tool()
async def TALLY_LIST_FORM_QUESTIONS(formId: str) -> Dict:
    """
    List all questions of a Tally form.

    This tool retrieves all the questions (blocks of type QUESTION, INPUT_TEXT, 
    MULTIPLE_CHOICE_OPTION, etc.) for the given form. Useful for inspecting 
    form structure or preparing updates.

    Args:
        formId (str): Unique ID of the form (from TALLY_LIST_FORMS or TALLY_GET_FORM).

    Returns:
        dict: Contains information about the questions, including:
            - id (str): Question ID
            - type (str): Block type (QUESTION, INPUT_TEXT, etc.)
            - uuid (str): Unique identifier for the block
            - groupUuid (str): Group identifier
            - groupType (str): Group type
            - payload (dict): Block-specific data such as text, options, etc.

    Raises:
        400 Bad Request: If the formId is invalid.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission.
        404 Not Found: If the formId does not exist.
    """
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
    """
    List all submissions for a given Tally form.

    Retrieves the submissions (responses) for a specific form. Supports pagination,
    filtering by status, date ranges, and fetching submissions after a specific ID.

    Args:
        formId (str): Unique ID of the form (from TALLY_LIST_FORMS or TALLY_GET_FORM).
        page (int, optional): Page number for paginated results. Default is 1.
        filter (str, optional): Filter submissions by status. 
            Options: "all", "completed", "draft". Default is "all".
        startDate (str, optional): ISO 8601 date (YYYY-MM-DD) to start filtering submissions.
        endDate (str, optional): ISO 8601 date (YYYY-MM-DD) to end filtering submissions.
        afterId (str, optional): Return submissions after the specified submission ID.

    Returns:
        dict: Contains submission details, including:
            - id (str): Submission ID
            - submittedAt (str): Timestamp of submission
            - data (dict): Submitted answers, keyed by question/block UUID
            - status (str): Submission status ("completed", "draft")
            - metadata (dict): Additional submission metadata

    Raises:
        400 Bad Request: If the formId is invalid or parameters are malformed.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission.
        404 Not Found: If the formId does not exist.
    """
    params = {"page": page, "filter": filter}
    if startDate: params["startDate"] = startDate
    if endDate: params["endDate"] = endDate
    if afterId: params["afterId"] = afterId
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}/submissions", params=params)

@mcp.tool()
async def TALLY_GET_SUBMISSION(formId: str, submissionId: str) -> Dict:
    """
    Retrieve a single submission for a given Tally form.

    Fetches the details of a specific submission (response) using the form ID
    and submission ID. Useful for viewing or processing a particular respondent's answers.

    Args:
        formId (str): Unique ID of the form (from TALLY_LIST_FORMS or TALLY_GET_FORM).
        submissionId (str): Unique ID of the submission (from TALLY_LIST_SUBMISSIONS).

    Returns:
        dict: Contains detailed submission information, including:
            - id (str): Submission ID
            - submittedAt (str): Timestamp of submission
            - status (str): Submission status ("completed", "draft")
            - data (dict): Submitted answers keyed by block/question UUID
            - metadata (dict): Additional submission metadata, e.g., IP, user agent

    Raises:
        400 Bad Request: If the formId or submissionId is invalid.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission to access the submission.
        404 Not Found: If the form or submission does not exist.
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}/submissions/{submissionId}")

@mcp.tool()
async def TALLY_DELETE_SUBMISSION(formId: str, submissionId: str) -> Dict:  
    """
    Delete a specific submission for a given Tally form.

    This tool removes a submission (response) permanently from the form.
    Use this with caution as deletion cannot be undone.

    Args:
        formId (str): Unique ID of the form (from TALLY_LIST_FORMS or TALLY_GET_FORM).
        submissionId (str): Unique ID of the submission to delete (from TALLY_LIST_SUBMISSIONS).

    Returns:
        dict: Confirmation of deletion, usually containing:
            - status (int): HTTP status code (204 for success)
            - message (str, optional): Success message if available

    Raises:
        400 Bad Request: If the formId or submissionId is invalid.
        401 Unauthorized: If the API key is missing or invalid.
        403 Forbidden: If the user does not have permission to delete the submission.
        404 Not Found: If the form or submission does not exist.
    """
    return await safe_request("DELETE", f"{TALLY_API_BASE}/forms/{formId}/submissions/{submissionId}")

@mcp.tool()
async def TALLY_GET_FORM_SETTINGS(formId: str):
    """
    Retrieve all configurable settings of a specific Tally form.

    This tool fetches detailed settings for a form, including:
    - Form language
    - Submission limits
    - Redirect URL on completion
    - Email notifications (for owner and respondent)
    - Appearance options (progress bar, styles)
    - Password protection
    - Data retention policies
    - Other behavior and settings for the form

    Args:
        formId (str): Unique identifier of the form. Can be obtained from TALLY_LIST_FORMS or TALLY_GET_FORM.

    Returns:
        dict: Dictionary containing the form's settings. Typical keys include:
            - language: str
            - isClosed: bool
            - redirectOnCompletion: str
            - hasSelfEmailNotifications: bool
            - selfEmailTo: str
            - hasRespondentEmailNotifications: bool
            - respondentEmailTo: str
            - hasProgressBar: bool
            - password: str
            - submissionsDataRetentionDuration: int
            - submissionsDataRetentionUnit: str
            - ...additional settings depending on form configuration

    Raises:
        400 Bad Request: Invalid formId
        401 Unauthorized: API key missing or invalid
        403 Forbidden: No access to the form
        404 Not Found: Form does not exist
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/forms/{formId}")

# ------------------------------------------------
#            Webhooks
# ------------------------------------------------
@mcp.tool()
async def TALLY_LIST_WEBHOOKS(page: int = 1, limit: int = 25) -> Dict:
    """
    Retrieve a paginated list of all webhooks associated with the authenticated Tally account.

    This tool fetches all webhook configurations, including:
    - Webhook ID
    - Associated form ID
    - URL of the webhook
    - Event types it listens to
    - Status (enabled/disabled)
    - Optional headers or signing secret info

    Args:
        page (int, optional): Page number for paginated results. Default is 1.
        limit (int, optional): Maximum number of webhooks per page. Maximum allowed is 100. Default is 25.

    Returns:
        dict: Dictionary containing a paginated list of webhooks. Typical keys include:
            - data: List of webhook objects
                - id: str
                - formId: str
                - url: str
                - eventTypes: List[str]
                - isEnabled: bool
                - httpHeaders: Optional[List[Dict[str, str]]]
                - signingSecret: Optional[str]
            - page: int
            - limit: int
            - total: int

    Raises:
        401 Unauthorized: API key missing or invalid
        403 Forbidden: Insufficient permissions
    """
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
    """
    Create a webhook for a specific Tally form.

    This tool allows you to register a webhook URL that will receive events for a given form.
    Common use cases:
      - Capture form responses in real-time
      - Trigger external workflows when a form is submitted

    Args:
        formId (str): ID of the Tally form to attach the webhook to.
        url (str): Target URL where webhook events will be sent.
        eventTypes (List[str], optional): Types of events to listen to. Default is ["FORM_RESPONSE"].
        signingSecret (str, optional): Secret key used to sign webhook payloads for verification.
        httpHeaders (List[Dict[str, str]], optional): Optional HTTP headers to include in webhook requests.
            Each header should be a dictionary with keys "key" and "value".
        externalSubscriber (str, optional): Identifier for external subscribers (if applicable).

    Returns:
        dict: Created webhook information, typically including:
            - id: str, webhook ID
            - formId: str
            - url: str
            - eventTypes: List[str]
            - isEnabled: bool
            - httpHeaders: List[Dict[str, str]] (if provided)
            - signingSecret: str (if provided)

    Raises:
        401 Unauthorized: Invalid API key
        403 Forbidden: Insufficient permissions
        400 Bad Request: Invalid input data
    """
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
    """
    Update an existing webhook for a Tally form.

    This tool allows you to modify the URL, events, and other configurations of an existing webhook.
    Typical use cases:
      - Change the target URL for webhook events
      - Enable or disable a webhook
      - Update the event types the webhook listens for
      - Update headers or signing secret for security

    Args:
        webhookId (str): The unique ID of the webhook to update.
        formId (str): ID of the Tally form associated with the webhook.
        url (str): The new URL where webhook events will be sent.
        eventTypes (List[str], optional): Types of events to listen to. Default is ["FORM_RESPONSE"].
        isEnabled (bool, optional): Whether the webhook should be active. Default is True.
        signingSecret (str, optional): Secret key used to sign webhook payloads for verification.
        httpHeaders (List[Dict[str, str]], optional): Optional HTTP headers to include in webhook requests.
            Each header should be a dictionary with keys "key" and "value".

    Returns:
        dict: Updated webhook information, typically including:
            - id: str, webhook ID
            - formId: str
            - url: str
            - eventTypes: List[str]
            - isEnabled: bool
            - httpHeaders: List[Dict[str, str]] (if provided)
            - signingSecret: str (if provided)

    Raises:
        401 Unauthorized: Invalid API key
        403 Forbidden: Insufficient permissions
        400 Bad Request: Invalid input data
    """
    payload = {"formId": formId, "url": url, "eventTypes": eventTypes, "isEnabled": isEnabled}
    if signingSecret: payload["signingSecret"] = signingSecret
    if httpHeaders: payload["httpHeaders"] = httpHeaders
    return await safe_request("PATCH", f"{TALLY_API_BASE}/webhooks/{webhookId}", json=payload)

@mcp.tool()
async def TALLY_DELETE_WEBHOOK(webhookId: str):
    """
    Delete an existing webhook from a Tally form.

    This tool removes a webhook permanently. Once deleted, it will no longer send
    any events to the configured URL. Use with caution.

    Args:
        webhookId (str): The unique ID of the webhook to delete.

    Returns:
        dict: Result of the deletion. Typically includes:
            - status: int (204 if successful)
            - message: str (confirmation message)

    Raises:
        401 Unauthorized: Invalid API key
        403 Forbidden: Insufficient permissions
        404 Not Found: Webhook ID does not exist
    """
    return await safe_request("DELETE", f"{TALLY_API_BASE}/webhooks/{webhookId}")

@mcp.tool()
async def TALLY_LIST_WEBHOOK_EVENTS(webhookId: str, page: Optional[int] = 1):
    """
    List all events received by a specific webhook.

    This tool fetches a paginated list of events for a given webhook ID. Each event
    typically contains information about the form response or other triggers that
    activated the webhook.

    Args:
        webhookId (str): The unique ID of the webhook to fetch events for.
        page (int, optional): Page number for pagination. Defaults to 1.

    Returns:
        dict: Paginated list of webhook events, each including:
            - eventId: str, unique ID of the event
            - eventType: str, type of the event (e.g., FORM_RESPONSE)
            - payload: dict, data sent by Tally for the event
            - createdAt: str, timestamp of the event

    Raises:
        401 Unauthorized: Invalid API key
        403 Forbidden: Insufficient permissions
        404 Not Found: Webhook ID does not exist
    """
    return await safe_request("GET", f"{TALLY_API_BASE}/webhooks/{webhookId}/events", params={"page": page})

# ------------------- RUN -------------------
if __name__ == "__main__":
    mcp.run()
