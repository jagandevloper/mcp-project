# production_notional_mcp.py
import os
import re
import asyncio
import logging
from typing import Optional, Dict, Any, List
from notion_client import Client
from mcp.server.fastmcp import FastMCP

# ---------------- CONFIG ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("notion_mcp")

mcp = FastMCP("notion-mcp")

# Use environment variable in production. If you keep a literal for testing, replace below.
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise RuntimeError("❌ Please set NOTION_TOKEN in environment variables.")

notion = Client(auth=NOTION_TOKEN)

# ---------------- HELPERS ----------------
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,36}$")


def validate_notion_id(notion_id: str) -> bool:
    if not notion_id or not isinstance(notion_id, str):
        return False
    return bool(_UUID_RE.match(notion_id))


def _func_name(func) -> str:
    # Some Notion client endpoints are bound objects without __name__
    return getattr(func, "__name__", getattr(func, "__qualname__", func.__class__.__name__))


def safe_execute(func, *args, **kwargs):
    """
    Calls Notion client endpoint or a function and returns structured JSON.
    Works when `func` is a bound endpoint object (no __name__).
    """
    try:
        data = func(*args, **kwargs)
        logger.info("✅ Success calling %s", _func_name(func))
        return {"successful": True, "data": data, "error": None}
    except Exception as e:
        logger.exception("❌ Error calling %s", _func_name(func))
        return {"successful": False, "data": {}, "error": str(e)}


def _collect_all_pages_query(database_id: str, page_size: int = 100) -> Dict[str, Any]:
    """
    Helper to collect all pages from databases.query with pagination.
    Returns dict with results list and next_cursor (None if done).
    """
    all_results = []
    start_cursor = None
    while True:
        kwargs = {"database_id": database_id, "page_size": page_size}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        res = safe_execute(lambda **kw: notion.databases.query(**kw), **kwargs)
        if not res["successful"]:
            return res
        page_data = res["data"]
        all_results.extend(page_data.get("results", []))
        start_cursor = page_data.get("next_cursor")
        if not start_cursor:
            break
    return {"successful": True, "data": {"results": all_results}, "error": None}


def _collect_all_blocks(block_id: str, page_size: int = 100) -> Dict[str, Any]:
    """Collect all children blocks for a block/page with pagination."""
    all_results = []
    start_cursor = None
    while True:
        kwargs = {"block_id": block_id, "page_size": page_size}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        res = safe_execute(lambda **kw: notion.blocks.children.list(**kw), **kwargs)
        if not res["successful"]:
            return res
        all_results.extend(res["data"].get("results", []))
        start_cursor = res["data"].get("next_cursor")
        if not start_cursor:
            break
    return {"successful": True, "data": {"results": all_results}, "error": None}


# ---------------- USER TOOLS ----------------
@mcp.tool()
def NOTION_GET_ABOUT_ME():
    """
    Retrieve details about the authenticated Notion user.
    
    Args:
        None
    
    Returns:
        dict: User information including id, name, email, avatar_url, and other metadata
    """
    return safe_execute(lambda **kw: notion.users.me(**kw))


@mcp.tool()
def NOTION_LIST_USERS(page_size: int = 30, start_cursor: Optional[str] = None):
    """
    List all users in the Notion workspace.
    
    Args:
        page_size: Number of users to return per page (default: 30)
        start_cursor: Cursor for pagination (optional)
    
    Returns:
        dict: List of users with id and name fields
    """
    kwargs = {"page_size": page_size}
    if start_cursor:
        kwargs["start_cursor"] = start_cursor
    res = safe_execute(lambda **kw: notion.users.list(**kw), **kwargs)
    if res["successful"]:
        simplified = [{"id": u.get("id"), "name": u.get("name", "Unknown")} for u in res["data"].get("results", [])]
        res["data"] = simplified
    return res


@mcp.tool()
def NOTION_GET_ABOUT_USER(user_id: str):
    """
    Retrieve details about a specific Notion user.
    
    Args:
        user_id: Unique identifier of the user to retrieve
    
    Returns:
        dict: User information including id, name, email, and other metadata
    """
    if not validate_notion_id(user_id):
        return {"successful": False, "data": {}, "error": "Invalid user ID format"}
    return safe_execute(lambda **kw: notion.users.retrieve(**kw), user_id=user_id)


# ---------------- PAGE / DUPLICATE / UPDATE TOOLS ----------------
@mcp.tool()
def NOTION_CREATE_NOTION_PAGE(parent_id: str, title: str, cover: Optional[str] = None, icon: Optional[str] = None):
    """
    Create a new Notion page under a parent page.
    
    Args:
        parent_id: ID of the parent page where the new page will be created
        title: Title of the new page
        cover: Optional cover image URL
        icon: Optional emoji icon
    
    Returns:
        dict: Created page information including id, title, and metadata
    """
    if not validate_notion_id(parent_id):
        return {"successful": False, "data": {}, "error": "Invalid parent ID format"}
    kwargs = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
    }
    if cover:
        kwargs["cover"] = {"external": {"url": cover}}
    if icon:
        kwargs["icon"] = {"emoji": icon}
    return safe_execute(lambda **kw: notion.pages.create(**kw), **kwargs)


@mcp.tool()
def NOTION_DUPLICATE_PAGE(page_id: str, parent_id: str, title: Optional[str] = None, include_blocks: bool = True):
    """
    Duplicate an existing Notion page to a new location.
    
    Args:
        page_id: ID of the page to duplicate
        parent_id: ID of the parent page where the duplicate will be created
        title: Optional new title for the duplicate (defaults to "Copy of [original title]")
        include_blocks: Whether to copy the page content/blocks (default: True)
    
    Returns:
        dict: Information about the duplicated page including new_page_id and title
    """
    if not validate_notion_id(page_id) or not validate_notion_id(parent_id):
        return {"successful": False, "data": {}, "error": "Invalid page_id or parent_id format"}

    # fetch original page metadata
    orig_res = safe_execute(lambda **kw: notion.pages.retrieve(**kw), page_id=page_id)
    if not orig_res["successful"]:
        return orig_res
    original = orig_res["data"]

    # extract a reasonable title
    orig_title = "Untitled"
    try:
        t_prop = original.get("properties", {})
        # find any title property key whose value contains 'title'
        for k, v in t_prop.items():
            if isinstance(v, dict) and "title" in v:
                title_parts = v.get("title", [])
                orig_title = "".join([p.get("plain_text", "") for p in title_parts]) or orig_title
                break
    except Exception:
        pass

    new_title = title or f"Copy of {orig_title}"

    # prepare properties copy - deep copy safe; but remove system-only fields if present
    new_properties = original.get("properties", {}).copy()
    # Ensure title property updated
    # find the title property key to overwrite (first property whose value has 'title')
    title_key = None
    for k, v in new_properties.items():
        if isinstance(v, dict) and "title" in v:
            title_key = k
            break
    if title_key:
        new_properties[title_key] = {"title": [{"text": {"content": new_title}}]}
    else:
        # If no title property exists (edge), add a 'Name' title property
        new_properties["Name"] = {"title": [{"text": {"content": new_title}}]}

    create_payload = {"parent": {"page_id": parent_id}, "properties": new_properties}
    if original.get("cover"):
        create_payload["cover"] = original["cover"]
    if original.get("icon"):
        create_payload["icon"] = original["icon"]

    new_page_res = safe_execute(lambda **kw: notion.pages.create(**kw), **create_payload)
    if not new_page_res["successful"]:
        return new_page_res

    new_page_id = new_page_res["data"]["id"]

    # copy blocks optionally (recursive shallow copy)
    if include_blocks:
        blocks_collected = _collect_all_blocks(page_id := page_id)
        if not blocks_collected["successful"]:
            logger.warning("Failed to collect blocks for duplication, continuing without blocks.")
        else:
            for blk in blocks_collected["data"].get("results", []):
                # Remove read-only fields and keep only the block payload
                blk_payload = {k: v for k, v in blk.items() if k not in ("id", "created_time", "last_edited_time", "created_by", "last_edited_by", "parent", "object")}
                # append
                try:
                    safe_execute(lambda **kw: notion.blocks.children.append(**kw), block_id=new_page_id, children=[blk_payload])
                except Exception as e:
                    logger.warning("Failed to append block during duplication: %s", e)

    return {"successful": True, "data": {"new_page_id": new_page_id, "title": new_title}, "error": None}


@mcp.tool()
def NOTION_UPDATE_PAGE(page_id: str, title: Optional[str] = None, archived: Optional[bool] = None,
                       cover_url: Optional[str] = None, icon_emoji: Optional[str] = None, properties: Optional[Dict[str, Any]] = None):
    """
    Update properties of an existing Notion page.
    
    Args:
        page_id: ID of the page to update
        title: Optional new title for the page
        archived: Optional archive status (True to archive, False to unarchive)
        cover_url: Optional new cover image URL
        icon_emoji: Optional new emoji icon
        properties: Optional additional properties to update
    
    Returns:
        dict: Updated page information
    """
    if not validate_notion_id(page_id):
        return {"successful": False, "data": {}, "error": "Invalid page_id format"}
    kwargs = {}
    if archived is not None:
        kwargs["archived"] = archived
    if cover_url:
        kwargs["cover"] = {"external": {"url": cover_url}}
    if icon_emoji:
        kwargs["icon"] = {"emoji": icon_emoji}
    if title:
        kwargs.setdefault("properties", {})
        # find title property name first by retrieving the page schema
        page_meta = safe_execute(lambda **kw: notion.pages.retrieve(**kw), page_id=page_id)
        if page_meta["successful"]:
            page_props = page_meta["data"].get("properties", {})
            title_key = None
            for k, v in page_props.items():
                if isinstance(v, dict) and "title" in v:
                    title_key = k
                    break
            if title_key:
                kwargs["properties"][title_key] = {"title": [{"text": {"content": title}}]}
            else:
                # fallback: set property "Name"
                kwargs["properties"]["Name"] = {"title": [{"text": {"content": title}}]}
        else:
            # can't inspect page; still set a 'title' property named 'Name'
            kwargs.setdefault("properties", {})
            kwargs["properties"]["Name"] = {"title": [{"text": {"content": title}}]}
    if properties:
        kwargs.setdefault("properties", {})
        kwargs["properties"].update(properties)
    return safe_execute(lambda **kw: notion.pages.update(**kw), page_id=page_id, **kwargs)


@mcp.tool()
def NOTION_GET_PAGE_PROPERTY_ACTION(page_id: str, property_id: str, page_size: Optional[int] = None, start_cursor: Optional[str] = None):
    """
    Retrieve a specific property value from a Notion page.
    
    Args:
        page_id: ID of the page to retrieve property from
        property_id: ID of the property to retrieve
        page_size: Optional number of results per page
        start_cursor: Optional cursor for pagination
    
    Returns:
        dict: Property value and metadata
    """
    if not validate_notion_id(page_id):
        
        return {"successful": False, "data": {}, "error": "Invalid page_id format"}
    kwargs = {"page_id": page_id, "property_id": property_id}
    if page_size:
        kwargs["page_size"] = page_size
    if start_cursor:
        kwargs["start_cursor"] = start_cursor
    return safe_execute(lambda **kw: notion.pages.properties.retrieve(**kw), **kwargs)


@mcp.tool()
def NOTION_ARCHIVE_NOTION_PAGE(page_id: str, archive: bool = True):
    """
    Archive or unarchive a Notion page.
    
    Args:
        page_id: ID of the page to archive/unarchive
        archive: Whether to archive (True) or unarchive (False) the page
    
    Returns:
        dict: Updated page information
    """
    if not validate_notion_id(page_id):
        return {"successful": False, "data": {}, "error": "Invalid page_id format"}
    return safe_execute(lambda **kw: notion.pages.update(**kw), page_id=page_id, archived=archive)


@mcp.tool()
def list_pages(keyword: Optional[str] = None):
    """
    Search for Notion pages by keyword.
    
    Args:
        keyword: Optional keyword to search for in page titles
    
    Returns:
        dict: List of pages with id, title, and url
    """
    search_kwargs = {"filter": {"property": "object", "value": "page"}}
    if keyword:
        search_kwargs["query"] = keyword
    res = safe_execute(lambda **kw: notion.search(**kw), **search_kwargs)
    if not res["successful"]:
        return res
    pages = []
    for pg in res["data"].get("results", []):
        title = "Untitled"
        try:
            props = pg.get("properties", {})
            # find first title prop
            for k, v in props.items():
                if isinstance(v, dict) and "title" in v:
                    title = "".join([t.get("plain_text", "") for t in v.get("title", [])]) or title
                    break
        except Exception:
            pass
        pages.append({"id": pg.get("id"), "title": title, "url": pg.get("url")})
    return {"successful": True, "data": pages, "error": ""}


# ---------------- DATABASE TOOLS ----------------
@mcp.tool()
def NOTION_CREATE_DATABASE(parent_id: str, title: str, properties: Dict[str, Any]):
    """
    Create a new Notion database under a parent page.
    
    Args:
        parent_id: ID of the parent page where the database will be created
        title: Title of the new database
        properties: Dictionary defining the database schema (columns)
    
    Returns:
        dict: Created database information including id, title, and properties
    """
    if not validate_notion_id(parent_id):
        return {"successful": False, "data": {}, "error": "Invalid parent_id format"}
    # require at least one title prop in properties values
    if not any(isinstance(v, dict) and "title" in v for v in properties.values()):
        return {"successful": False, "data": {}, "error": "Database must have at least one title property"}
    payload = {"parent": {"type": "page_id", "page_id": parent_id}, "title": [{"type": "text", "text": {"content": title}}], "properties": properties}
    return safe_execute(lambda **kw: notion.databases.create(**kw), **payload)


@mcp.tool()
def NOTION_INSERT_ROW_DATABASE(database_id: str, properties: Dict[str, Any], icon: Optional[str] = None, cover: Optional[str] = None, children: Optional[List[Dict[str, Any]]] = None):
    """
    Insert a new row (page) into a Notion database.
    
    Args:
        database_id: ID of the database to insert the row into
        properties: Dictionary of property values for the new row
        icon: Optional emoji icon for the row
        cover: Optional cover image URL for the row
        children: Optional list of blocks to add as content to the row
    
    Returns:
        dict: Created row information including id and properties
    """
    if not validate_notion_id(database_id):
        return {"successful": False, "data": {}, "error": "Invalid database_id format"}
    payload = {"parent": {"database_id": database_id}, "properties": properties}
    if icon:
        payload["icon"] = {"emoji": icon}
    if cover:
        payload["cover"] = {"external": {"url": cover}}
    if children:
        payload["children"] = children
    return safe_execute(lambda **kw: notion.pages.create(**kw), **payload)


@mcp.tool()
def NOTION_QUERY_DATABASE(database_id: str, page_size: int = 10, sorts: Optional[List[Dict[str, Any]]] = None, start_cursor: Optional[str] = None):
    """
    Query a Notion database to retrieve rows with optional sorting and pagination.
    
    Args:
        database_id: ID of the database to query
        page_size: Number of rows to return per page (default: 10)
        sorts: Optional list of sort criteria (property and direction)
        start_cursor: Optional cursor for pagination
    
    Returns:
        dict: Query results including rows and pagination information
    """
    if not validate_notion_id(database_id):
        return {"successful": False, "data": {}, "error": "Invalid database_id format"}
    payload = {"page_size": page_size}
    if sorts:
        payload["sorts"] = [{"property": s["property"], "direction": s.get("direction", "ascending")} for s in sorts]
    if start_cursor:
        payload["start_cursor"] = start_cursor
    return safe_execute(lambda **kw: notion.databases.query(**kw), database_id=database_id, **payload)


@mcp.tool()
def NOTION_FETCH_DATABASE(database_id: str):
    """
    Retrieve metadata and schema information for a Notion database.
    
    Args:
        database_id: ID of the database to fetch
    
    Returns:
        dict: Database information including title, properties schema, and metadata
    """
    if not validate_notion_id(database_id):
        return {"successful": False, "data": {}, "error": "Invalid database_id format"}
    return safe_execute(lambda **kw: notion.databases.retrieve(**kw), database_id=database_id)


@mcp.tool()
def NOTION_FETCH_ROW(page_id: str):
    """
    Retrieve a specific row (page) from a Notion database.
    
    Args:
        page_id: ID of the row/page to fetch
    
    Returns:
        dict: Row information including properties and metadata
    """
    if not validate_notion_id(page_id):
        return {"successful": False, "data": {}, "error": "Invalid page_id format"}
    return safe_execute(lambda **kw: notion.pages.retrieve(**kw), page_id=page_id)


@mcp.tool()
def NOTION_UPDATE_ROW_DATABASE(page_id: str, properties: Optional[Dict[str, Any]] = None, icon: Optional[str] = None, cover: Optional[str] = None, archived: Optional[bool] = False):
    """
    Update properties and metadata of a Notion database row.
    
    Args:
        page_id: ID of the row/page to update
        properties: Optional dictionary of property values to update
        icon: Optional emoji icon for the row
        cover: Optional cover image URL for the row
        archived: Optional archive status (True to archive, False to unarchive)
    
    Returns:
        dict: Updated row information
    """
    if not validate_notion_id(page_id):
        return {"successful": False, "data": {}, "error": "Invalid page_id format"}
    payload = {}
    if properties:
        payload["properties"] = properties
    if icon:
        payload["icon"] = {"emoji": icon}
    if cover:
        payload["cover"] = {"external": {"url": cover}}
    if archived is not None:
        payload["archived"] = archived
    return safe_execute(lambda **kw: notion.pages.update(**kw), page_id=page_id, **payload)


@mcp.tool()
def NOTION_UPDATE_SCHEMA_DATABASE(database_id: str, title: Optional[str] = None, description: Optional[str] = None, properties: Optional[Dict[str, Any]] = None):
    """
    Update the schema and metadata of a Notion database.
    
    Args:
        database_id: ID of the database to update
        title: Optional new title for the database
        description: Optional new description for the database
        properties: Optional new properties schema (columns) for the database
    
    Returns:
        dict: Updated database information
    """
    if not validate_notion_id(database_id):
        return {"successful": False, "data": {}, "error": "Invalid database_id format"}
    payload = {}
    if title:
        payload["title"] = [{"type": "text", "text": {"content": title}}]
    if description:
        payload["description"] = [{"type": "text", "text": {"content": description}}]
    if properties:
        payload["properties"] = properties
    return safe_execute(lambda **kw: notion.databases.update(**kw), database_id=database_id, **payload)


# ---------------- BLOCK TOOLS ----------------
def markdown_to_rich_text(content: str) -> List[Dict[str, Any]]:
    # Minimal conversion: returns single text rich_text item. Extend as needed.
    return [{"type": "text", "text": {"content": content}}]


@mcp.tool()
def NOTION_ADD_MULTIPLE_PAGE_CONTENT(parent_block_id: str, content_blocks: List[Dict[str, Any]], after: Optional[str] = None):
    """
    Add multiple content blocks to a Notion page or block.
    
    Args:
        parent_block_id: ID of the parent block/page to add content to
        content_blocks: List of block objects or content dictionaries to add
        after: Optional block ID to insert content after
    
    Returns:
        dict: Information about the added blocks
    """
    if not validate_notion_id(parent_block_id):
        return {"successful": False, "data": {}, "error": "Invalid parent_block_id"}
    if not isinstance(content_blocks, list) or len(content_blocks) == 0:
        return {"successful": False, "data": {}, "error": "content_blocks must be a non-empty list"}
    if len(content_blocks) > 100:
        return {"successful": False, "data": {}, "error": "Maximum 100 blocks per request"}

    parsed_blocks = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("object") == "block":
            parsed_blocks.append(block)
        elif isinstance(block, dict) and "content" in block:
            parsed_blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": markdown_to_rich_text(block["content"])}})
        else:
            return {"successful": False, "data": {}, "error": f"Invalid block format: {block}"}

    payload = {"children": parsed_blocks}
    if after is not None:
        payload["after"] = after
    return safe_execute(lambda **kw: notion.blocks.children.append(**kw), block_id=parent_block_id, **payload)


@mcp.tool()
def NOTION_ADD_PAGE_CONTENT(parent_block_id: str, content_block: Dict[str, Any], after: Optional[str] = None):
    """
    Add a single content block to a Notion page or block.
    
    Args:
        parent_block_id: ID of the parent block/page to add content to
        content_block: Block object to add
        after: Optional block ID to insert content after
    
    Returns:
        dict: Information about the added block
    """
    if not validate_notion_id(parent_block_id):
        return {"successful": False, "data": {}, "error": "Invalid parent_block_id"}
    if not isinstance(content_block, dict):
        return {"successful": False, "data": {}, "error": "content_block must be an object"}
    payload = {"children": [content_block]}
    if after is not None:
        payload["after"] = after
    return safe_execute(lambda **kw: notion.blocks.children.append(**kw), block_id=parent_block_id, **payload)


@mcp.tool()
def NOTION_APPEND_BLOCK_CHILDREN(block_id: str, children: List[Dict[str, Any]], after: Optional[str] = None):
    """
    Append child blocks to a Notion block or page.
    
    Args:
        block_id: ID of the parent block to append children to
        children: List of block objects to append
        after: Optional block ID to insert children after
    
    Returns:
        dict: Information about the appended blocks
    """
    if not validate_notion_id(block_id):
        return {"successful": False, "data": {}, "error": "Invalid block_id"}
    if not isinstance(children, list) or len(children) == 0:
        return {"successful": False, "data": {}, "error": "children must be a non-empty list"}
    if len(children) > 100:
        return {"successful": False, "data": {}, "error": "Maximum 100 blocks per request"}
    payload = {"children": children}
    if after is not None:
        payload["after"] = after
    return safe_execute(lambda **kw: notion.blocks.children.append(**kw), block_id=block_id, **payload)


@mcp.tool()
def NOTION_UPDATE_BLOCK(block_id: str, block_type: str, content: str, additional_properties: Optional[Dict[str, Any]] = None):
    """
    Update the content of an existing Notion block.
    
    Args:
        block_id: ID of the block to update
        block_type: Type of block (paragraph, heading_1, heading_2, heading_3, etc.)
        content: Text content for the block
        additional_properties: Optional additional properties for the block
    
    Returns:
        dict: Updated block information
    """
    if not validate_notion_id(block_id):
        return {"successful": False, "data": {}, "error": "Invalid block_id"}
    # For text-like blocks we populate the type's rich_text or text key depending on type.
    # Caller should pass appropriate block_type and additional_properties when needed.
    block_payload = {}
    # Common mapping for text-based blocks
    if block_type in ("paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "quote"):
        # Notion expects e.g. {"paragraph": {"rich_text": [...], **additional_properties}}
        block_payload[block_type] = {"rich_text": markdown_to_rich_text(content)}
        if additional_properties:
            block_payload[block_type].update(additional_properties)
    elif block_type == "to_do":
        block_payload["to_do"] = {"rich_text": markdown_to_rich_text(content)}
        if additional_properties:
            block_payload["to_do"].update(additional_properties)
    else:
        # For other block types, allow caller to provide the payload via additional_properties
        if not additional_properties:
            return {"successful": False, "data": {}, "error": f"Unsupported block_type '{block_type}' without additional_properties"}
        block_payload[block_type] = additional_properties

    return safe_execute(lambda **kw: notion.blocks.update(**kw), block_id=block_id, **block_payload)


@mcp.tool()
def NOTION_DELETE_BLOCK(block_id: str):
    """
    Delete (archive) a Notion block.
    
    Args:
        block_id: ID of the block to delete
    
    Returns:
        dict: Confirmation of deletion
    """
    if not validate_notion_id(block_id):
        return {"successful": False, "data": {}, "error": "Invalid block_id"}
    return safe_execute(lambda **kw: notion.blocks.update(**kw), block_id=block_id, archived=True)


@mcp.tool()
def NOTION_FETCH_BLOCK_CONTENTS(block_id: str, page_size: Optional[int] = None, start_cursor: Optional[str] = None):
    """
    Retrieve the child blocks of a Notion block or page.
    
    Args:
        block_id: ID of the block to fetch children from
        page_size: Optional number of blocks to return per page
        start_cursor: Optional cursor for pagination
    
    Returns:
        dict: List of child blocks with pagination information
    """
    if not validate_notion_id(block_id):
        return {"successful": False, "data": {}, "error": "Invalid block_id"}
    kwargs = {"block_id": block_id}
    if page_size:
        kwargs["page_size"] = page_size
    if start_cursor:
        kwargs["start_cursor"] = start_cursor
    return safe_execute(lambda **kw: notion.blocks.children.list(**kw), **kwargs)


@mcp.tool()
def NOTION_FETCH_BLOCK_METADATA(block_id: str):
    """
    Retrieve metadata information for a Notion block.
    
    Args:
        block_id: ID of the block to fetch metadata for
    
    Returns:
        dict: Block metadata including type, properties, and other information
    """
    if not validate_notion_id(block_id):
        return {"successful": False, "data": {}, "error": "Invalid block_id"}
    return safe_execute(lambda **kw: notion.blocks.retrieve(**kw), block_id=block_id)


@mcp.tool()
def mcp_notion_get_all_ids_from_name(name: str, max_depth: int = 3):
    """
    Search for Notion items by name and retrieve their IDs and related information.
    
    Args:
        name: Name to search for in Notion
        max_depth: Maximum depth to search (default: 3)
    
    Returns:
        dict: Search results including object type, id, parent info, blocks, and rows
    """
    if not name or not isinstance(name, str):
        return {"successful": False, "data": {}, "error": "name is required"}
    res = safe_execute(lambda **kw: notion.search(**kw), query=name)
    if not res["successful"]:
        return res
    results = res["data"].get("results", [])
    if not results:
        return {"successful": False, "data": {}, "error": f"No match found for '{name}'"}
    target = results[0]
    obj_type = target.get("object")
    obj_id = target.get("id")
    result: Dict[str, Any] = {"object_type": obj_type, "id": obj_id, "parent": target.get("parent", {}), "blocks": [], "rows": [], "comments": []}
    # extract title
    if obj_type == "page":
        try:
            for k, v in target.get("properties", {}).items():
                if isinstance(v, dict) and "title" in v:
                    result["title"] = "".join([t.get("plain_text", "") for t in v.get("title", [])]) or "Untitled"
                    break
        except Exception:
            result["title"] = "Untitled"
    elif obj_type == "database":
        title = target.get("title", [])
        result["title"] = title[0].get("plain_text", "Untitled") if title else "Untitled"
    # blocks & comments
    if obj_type == "page":
        blocks_col = _collect_all_blocks(obj_id)
        if blocks_col["successful"]:
            result["blocks"] = [{"id": b.get("id"), "type": b.get("type"), "has_children": b.get("has_children", False)} for b in blocks_col["data"].get("results", [])]
        comments_res = safe_execute(lambda **kw: notion.comments.list(**kw), block_id=obj_id)
        if comments_res["successful"]:
            for c in comments_res["data"].get("results", []):
                result["comments"].append({"id": c.get("id"), "discussion_id": c.get("discussion_id"), "text": "".join([t.get("plain_text", "") for t in c.get("rich_text", [])])})
    elif obj_type == "database":
        rows_res = _collect_all_pages_query(obj_id)
        if rows_res["successful"]:
            result["rows"] = [{"id": r.get("id"), "parent": r.get("parent", {})} for r in rows_res["data"].get("results", [])]
    return {"successful": True, "data": result, "error": ""}


# ---------------- COMMENT TOOLS ----------------
@mcp.tool()
def NOTION_CREATE_COMMENT(comment: Dict[str, Any], discussion_id: Optional[str] = None, parent_page_id: Optional[str] = None):
    """
    Create a comment on a Notion page or discussion.
    
    Args:
        comment: Dictionary containing comment content
        discussion_id: Optional ID of the discussion to comment on
        parent_page_id: Optional ID of the page to comment on
    
    Returns:
        dict: Created comment information
    """
    if not discussion_id and not parent_page_id:
        return {"successful": False, "data": {}, "error": "Either discussion_id or parent_page_id must be provided."}
    # Build rich_text payload for comment.create
    payload = {"rich_text": [{"type": "text", "text": {"content": comment.get("content", "")}}]}
    if discussion_id:
        payload["discussion_id"] = discussion_id
    else:
        # parent page
        payload["parent"] = {"type": "page_id", "page_id": parent_page_id}
    return safe_execute(lambda **kw: notion.comments.create(**kw), **payload)


@mcp.tool()
def NOTION_GET_COMMENT_BY_ID(parent_block_id: str, comment_id: str):
    """
    Retrieve a specific comment by its ID from a Notion block.
    
    Args:
        parent_block_id: ID of the parent block where the comment is located
        comment_id: ID of the comment to retrieve
    
    Returns:
        dict: Comment information including content and metadata
    """
    if not parent_block_id or not comment_id:
        return {"successful": False, "data": {}, "error": "parent_block_id and comment_id are required."}
    # fetch (paginated if needed)
    kwargs = {"block_id": parent_block_id, "page_size": 100}
    res = safe_execute(lambda **kw: notion.comments.list(**kw), **kwargs)
    if not res["successful"]:
        return res
    for c in res["data"].get("results", []):
        if c.get("id") == comment_id:
            return {"successful": True, "data": c, "error": None}
    return {"successful": False, "data": {}, "error": f"Comment with ID {comment_id} not found."}


@mcp.tool()
def NOTION_FETCH_COMMENTS(block_id: str, page_size: Optional[int] = 100, start_cursor: Optional[str] = None):
    """
    Retrieve all comments for a Notion block.
    
    Args:
        block_id: ID of the block to fetch comments from
        page_size: Optional number of comments to return per page (default: 100)
        start_cursor: Optional cursor for pagination
    
    Returns:
        dict: List of comments with pagination information
    """
    if not block_id:
        return {"successful": False, "data": {}, "error": "block_id is required."}
    kwargs = {"block_id": block_id, "page_size": page_size}
    if start_cursor is not None:
        kwargs["start_cursor"] = start_cursor
    return safe_execute(lambda **kw: notion.comments.list(**kw), **kwargs)
#--------------------------------------
           #SEARCH TOOLS
#--------------------------------------

@mcp.tool()
def NOTION_SEARCH_NOTION_PAGE(
    direction: Optional[str] = None,
    filter_property: Optional[str] = "object",
    filter_value: Optional[str] = "page",
    page_size: int = 2,
    query: Optional[str] = "",
    start_cursor: Optional[str] = None,
    timestamp: Optional[str] = None,
):
    """
    Search for Notion pages and databases by title.
    
    Args:
        direction: Optional sort direction (ascending/descending)
        filter_property: Property to filter by (default: "object")
        filter_value: Value to filter by (default: "page")
        page_size: Number of results per page (default: 2)
        query: Search query string (empty returns all accessible items)
        start_cursor: Optional cursor for pagination
        timestamp: Optional timestamp for sorting
    
    Returns:
        dict: Search results with pagination information
    """
    kwargs = {
        "page_size": page_size,
        "filter": {"property": filter_property, "value": filter_value},
    }

    if query:
        kwargs["query"] = query
    if timestamp:
        kwargs["sort"] = {"direction": direction or "ascending", "timestamp": timestamp}
    if start_cursor:
        kwargs["start_cursor"] = start_cursor

    return safe_execute(lambda **kw: notion.search(**kw), **kwargs)

@mcp.tool()
def NOTION_FETCH_DATA(
    get_all: bool = False,
    get_databases: bool = False,
    get_pages: bool = False,
    page_size: int = 100,
    query: Optional[str] = None,
):
    """
    Fetch Notion items (pages and/or databases) with optional filtering.
    
    Args:
        get_all: Whether to fetch all accessible items (default: False)
        get_databases: Whether to fetch only databases (default: False)
        get_pages: Whether to fetch only pages (default: False)
        page_size: Number of items per page (default: 100)
        query: Optional search query string
    
    Returns:
        dict: List of Notion items with minimal metadata
    """
    kwargs = {"page_size": page_size}
    if query:
        kwargs["query"] = query

    if get_all:
        return safe_execute(lambda **kw: notion.search(**kw), **kwargs)

    if get_databases:
        kwargs["filter"] = {"property": "object", "value": "database"}
        return safe_execute(lambda **kw: notion.search(**kw), **kwargs)

    if get_pages:
        kwargs["filter"] = {"property": "object", "value": "page"}
        return safe_execute(lambda **kw: notion.search(**kw), **kwargs)

    # Default: pages
    kwargs["filter"] = {"property": "object", "value": "page"}
    return safe_execute(lambda **kw: notion.search(**kw), **kwargs)

# ---------------- ENTRYPOINT ----------------
if __name__ == "__main__":
    logger.info("Starting Notion MCP server...")
    asyncio.run(mcp.run())
