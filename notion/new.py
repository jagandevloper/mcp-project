import os
import time
import logging
from dotenv import load_dotenv
from notion_client import Client, APIResponseError
from mcp.server.fastmcp import FastMCP
from functools import wraps
# ---------- Logging Setup ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------- Load environment ----------
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

if not NOTION_API_KEY:
    logger.error("Missing NOTION_API_KEY in .env")
    raise ValueError("Missing NOTION_API_KEY in .env")

try:
    notion = Client(auth=NOTION_API_KEY)
    logger.info("Notion client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Notion client: {e}")
    raise

mcp = FastMCP("notion-user-mcp-server")


# ---------- Rate Limiting ----------
class RateLimiter:
    def __init__(self, max_calls=3, time_window=1):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
    
    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            # Remove old calls outside the time window
            self.calls[:] = [call_time for call_time in self.calls if now - call_time < self.time_window]
            
            # If we've hit the rate limit, wait
            if len(self.calls) >= self.max_calls:
                sleep_time = self.time_window - (now - self.calls[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            # Record this call
            self.calls.append(time.time())
            return func(*args, **kwargs)
        return wrapper

# Global rate limiter instance
rate_limiter = RateLimiter(max_calls=3, time_window=1)

# ---------- Enhanced Error Handling ----------
class NotionError(Exception):
    """Custom exception for Notion-specific errors"""
    def __init__(self, message: str, error_code: str = None, details: dict = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

def validate_notion_id(obj_id: str, obj_type: str = "object") -> bool:
    """Validate Notion object ID format"""
    if not obj_id or not isinstance(obj_id, str):
        return False
    # Notion IDs are 32 characters with hyphens
    return len(obj_id) == 36 and obj_id.count('-') == 4

def validate_required_params(params: dict, required: list) -> None:
    """Validate required parameters"""
    missing = [param for param in required if not params.get(param)]
    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(missing)}")

# ---------- Helper ----------
@rate_limiter
def safe_execute(func, *args, **kwargs):
    """Enhanced safe execution with detailed error handling and logging"""
    func_name = func.__name__ if hasattr(func, '__name__') else str(func)
    
    try:
        logger.debug(f"Executing {func_name} with args: {args}, kwargs: {kwargs}")
        data = func(*args, **kwargs)
        logger.debug(f"Successfully executed {func_name}")
        return {"successful": True, "data": data, "error": ""}
    
    except APIResponseError as e:
        error_msg = f"Notion API error in {func_name}: {str(e)}"
        logger.error(error_msg)
        
        # Parse error details
        error_details = {
            "type": "API_ERROR",
            "function": func_name,
            "status_code": getattr(e, 'status', None),
            "error_code": getattr(e, 'code', None),
            "message": str(e)
        }
        
        return {
            "successful": False, 
            "data": {}, 
            "error": error_msg,
            "error_details": error_details
        }
    
    except ValueError as e:
        error_msg = f"Validation error in {func_name}: {str(e)}"
        logger.warning(error_msg)
        return {
            "successful": False, 
            "data": {}, 
            "error": error_msg,
            "error_type": "VALIDATION_ERROR"
        }
    
    except Exception as e:
        error_msg = f"Unexpected error in {func_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "successful": False, 
            "data": {}, 
            "error": error_msg,
            "error_type": "UNEXPECTED_ERROR"
        }


# ==================================================
# USER TOOLS
# ==================================================

@mcp.tool()
def get_about_me():
    """ Get details of the user """
    return safe_execute(notion.users.me)


@mcp.tool()
def list_users():
    """List all users (id + name) """
    res = safe_execute(notion.users.list)
    if res["successful"]:
        simplified = [{"id": u["id"], "name": u.get("name", "Unknown")}
                      for u in res["data"].get("results", [])]
        res["data"] = simplified
    return res


@mcp.tool()
def retrieve_user(user_id: str):
    """ Retrieve full information about a specific user. """
    if not validate_notion_id(user_id):
        return {"successful": False, "data": {}, "error": "Invalid user ID format"}
    
    return safe_execute(notion.users.retrieve, user_id)

# ==================================================
# DATABASE TOOLS
# ==================================================
@mcp.tool()
def list_databases():
    """List all databases with id and title."""
    res = safe_execute(notion.search, filter={"property": "object", "value": "database"})
    if res["successful"]:
        simplified = [
            {"id": db["id"], "title": "".join([t.get("plain_text", "") for t in db.get("title", [])]) if db.get("title") else "Untitled"}
            for db in res["data"].get("results", [])
        ]
        res["data"] = simplified
    return res

@mcp.tool()
def retrieve_database(database_id: str):
    """Get full details of a database (properties, title, parent)."""
    if not validate_notion_id(database_id):
        return {"successful": False, "data": {}, "error": "Invalid database ID format"}
    
    return safe_execute(notion.databases.retrieve, database_id)

@mcp.tool()
def create_database(parent_page_id: str, title: str, properties: dict):
    """Create a new database under a parent page."""
    # Input validation
    if not validate_notion_id(parent_page_id):
        return {"successful": False, "data": {}, "error": "Invalid parent page ID format"}
    
    if not title or not isinstance(title, str):
        return {"successful": False, "data": {}, "error": "Title must be a non-empty string"}
    
    if not isinstance(properties, dict):
        return {"successful": False, "data": {}, "error": "Properties must be a dictionary"}
    
    # Ensure Name property exists
    if "Name" not in properties:
        properties["Name"] = {"title": {}}
    
    return safe_execute(
        notion.databases.create,
        parent={"page_id": parent_page_id},
        title=[{"text": {"content": title}}],
        properties=properties
    )

@mcp.tool()
def update_database(database_id: str, title: str = None, properties: dict = None):
    """Update a database with a new title or properties"""
    args = {}
    if title:
        args["title"] = [{"text": {"content": title}}]
    if properties:
        args["properties"] = properties
    return safe_execute(notion.databases.update, database_id, **args)

@mcp.tool()
def query_database(database_id: str, filter: dict = None, sorts: list = None, page_size: int = 100):
    """Query row  from a database """
    args = {"database_id": database_id, "page_size": page_size}
    
    # Only add filter/sorts if they are provided
    if filter and isinstance(filter, dict) and filter != {}:
        args["filter"] = filter
    if sorts and isinstance(sorts, list) and len(sorts) > 0:
        args["sorts"] = sorts

    return safe_execute(notion.databases.query, **args)
# ==================================================
# PAGE TOOLS
# ==================================================
@mcp.tool()
def create_page(parent_id: str, title: str, icon: str = None, cover: str = None):
    """Create a page under parent page or database."""
    try:
        notion.databases.retrieve(parent_id)
        is_database = True
    except APIResponseError:
        is_database = False

    if is_database:
        properties = {"Name": {"title": [{"text": {"content": title}}]}}
        return safe_execute(notion.pages.create,
                            parent={"database_id": parent_id},
                            properties=properties,
                            icon={"emoji": icon} if icon else None,
                            cover={"external": {"url": cover}} if cover else None)
    else:
        return safe_execute(notion.pages.create,
                            parent={"page_id": parent_id},
                            properties={},
                            icon={"emoji": icon} if icon else None,
                            cover={"external": {"url": cover}} if cover else None,
                            children=[{"object": "block",
                                       "type": "heading_1",
                                       "heading_1": {"rich_text": [{"text": {"content": title}}]}}])

@mcp.tool()
def retrieve_page(page_id: str):
    """Get all properties of a page."""
    return safe_execute(notion.pages.retrieve, page_id)

@mcp.tool()
def update_page(page_id: str, properties: dict = None, icon: str = None, cover: str = None):
    return safe_execute(notion.pages.update,
                        page_id,
                        properties=properties or {},
                        icon={"emoji": icon} if icon else None,
                        cover={"external": {"url": cover}} if cover else None)


@mcp.tool()
def archive_page(page_id: str, archive: bool = True):
    return safe_execute(notion.pages.update, page_id, archived=archive)

@mcp.tool()
def duplicate_page(page_id: str, parent_id: str, new_title: str):
    content_res = safe_execute(notion.blocks.children.list, page_id)
    if not content_res["successful"]:
        return content_res

    return safe_execute(notion.pages.create,
                        parent={"page_id": parent_id},
                        properties={"Name": {"title": [{"text": {"content": new_title}}]}},
                        children=content_res["data"].get("results", []))
@mcp.tool()
def list_pages(keyword: str = None):
    res = safe_execute(notion.search, filter={"property": "object", "value": "page"})
    if not res["successful"]:
        return res

    pages = []
    for pg in res["data"].get("results", []):
        title = "Untitled"
        try:
            # Fix: Safe property access with proper error handling
            if "properties" in pg and "Name" in pg["properties"]:
                name_prop = pg["properties"]["Name"]
                if "title" in name_prop and name_prop["title"]:
                    title = "".join([t["plain_text"] for t in name_prop["title"]])
        except (KeyError, TypeError, AttributeError):
            pass
        
        if not keyword or keyword.lower() in title.lower():
            pages.append({"id": pg["id"], "title": title, "url": pg.get("url")})
    return {"successful": True, "data": pages, "error": ""}

# ==================================================
# COMMENTS TOOLS
# ==================================================

@mcp.tool()
def create_comment(page_id: str, text: str, block_id: str = None):
    """
    Create a comment on a page or specific block.
    - page_id: ID of the page to comment on
    - text: Comment text content
    - block_id: Optional specific block ID to comment on
    """
    parent = {"page_id": page_id}
    if block_id:
        parent = {"block_id": block_id}
    
    return safe_execute(
        notion.comments.create,
        parent=parent,
        rich_text=[{"text": {"content": text}}]
    )

@mcp.tool()
def list_comments(block_id: str, page_size: int = 50):
    """
    List all comments on a page or block.
    - block_id: ID of the page or block to get comments for
    - page_size: Number of comments to retrieve (max 100)
    """
    return safe_execute(notion.comments.list, block_id=block_id, page_size=page_size)

@mcp.tool()
def retrieve_comment(comment_id: str):
    """
    Retrieve a specific comment by ID.
    - comment_id: ID of the comment to retrieve
    """
    return safe_execute(notion.comments.retrieve, comment_id)

# ==================================================
# BLOCK TOOLS
# ==================================================
@mcp.tool()
def retrieve_block(block_id: str):
    """
    Retrieve a block by ID.
    """
    return safe_execute(notion.blocks.retrieve, block_id)

@mcp.tool()
def list_block_children(block_id: str, page_size: int = 50):
    """
    List children (nested blocks) of a block or page.
    """
    return safe_execute(notion.blocks.children.list, block_id, page_size=page_size)

@mcp.tool()
def append_block(parent_id: str, children: list):
    """
    Append one or more blocks to a page or block.
    
    """
    if not children or not isinstance(children, list):
        return {"successful": False, "error": "children must be a non-empty list of block objects"}
    
    return safe_execute(
        notion.blocks.children.append,
        parent_id,
        children=children
    )


@mcp.tool()
def update_block(block_id: str, fields: dict):
    """
    Update a block (e.g., change paragraph text).

    """
    return safe_execute(notion.blocks.update, block_id, **fields)

@mcp.tool()
def delete_block(block_id: str):
    """
    Delete (archive) a block, page, or database by ID.
    """
    return safe_execute(notion.blocks.delete, block_id)
@mcp.tool()
def get_all_ids_from_name(name: str, max_depth: int = 3):
    """
    Given a Notion page or database name, fetch all related IDs:
    """

    # Step 1: Search for matching page or database
    search_res = safe_execute(notion.search, query=name)
    if not search_res["successful"]:
        return search_res

    results = search_res["data"].get("results", [])
    if not results:
        return {"successful": False, "data": {}, "error": f"No match found for '{name}'"}

    # Take first match
    target = results[0]
    obj_type = target["object"]
    obj_id = target["id"]

    result = {
        "object_type": obj_type,
        "id": obj_id,
        "parent": target.get("parent", {}),
        "blocks": [],
        "rows": [],
        "comments": []
    }

    # Extract title if possible
    if obj_type == "page":
        try:
            result["title"] = target["properties"]["Name"]["title"][0]["plain_text"]
        except Exception:
            result["title"] = "Untitled"
    elif obj_type == "database":
        title = target.get("title", [])
        result["title"] = title[0]["plain_text"] if title else "Untitled"

    # Step 2: If page → fetch blocks + comments
    if obj_type == "page":

        def fetch_blocks_recursive(block_id, depth):
            blocks_res = safe_execute(notion.blocks.children.list, block_id, page_size=50)
            if not blocks_res["successful"]:
                return []

            collected = []
            for blk in blocks_res["data"].get("results", []):
                blk_entry = {
                    "id": blk["id"],
                    "type": blk["type"],
                    "has_children": blk.get("has_children", False),
                    "children": []
                }
                if blk.get("has_children") and depth < max_depth:
                    blk_entry["children"] = fetch_blocks_recursive(blk["id"], depth + 1)
                collected.append(blk_entry)
            return collected

        result["blocks"] = fetch_blocks_recursive(obj_id, 1)

        # Comments
        comments_res = safe_execute(notion.comments.list, block_id=obj_id)
        if comments_res["successful"]:
            for c in comments_res["data"].get("results", []):
                result["comments"].append({
                    "id": c["id"],
                    "discussion_id": c.get("discussion_id"),
                    "text": "".join([t["plain_text"] for t in c["rich_text"]])
                })

    # Step 3: If database → fetch schema + rows (pages inside database)
    elif obj_type == "database":
        rows_res = safe_execute(notion.databases.query, obj_id)
        if rows_res["successful"]:
            for row in rows_res["data"].get("results", []):
                row_entry = {
                    "id": row["id"],
                    "parent": row.get("parent", {}),
                }
                result["rows"].append(row_entry)

    return {"successful": True, "data": result, "error": ""}

# ==================================================
# ADVANCED SEARCH TOOLS
# ==================================================

@mcp.tool()
def advanced_search(query: str = None, object_type: str = None, 
                   created_by: str = None, last_edited_time: dict = None,
                   page_size: int = 100):
    """
    Advanced search with multiple filters.
    - query: Text to search for
    - object_type: Filter by object type ('page', 'database', 'user')
    - created_by: Filter by creator user ID
    - last_edited_time: Filter by last edited time (dict with 'after' or 'before' keys)
    - page_size: Number of results to return (max 100)
    """
    args = {"page_size": page_size}
    
    # Add query if provided
    if query:
        args["query"] = query
    
    # Build filter object
    filter_dict = {}
    
    if object_type:
        filter_dict["property"] = "object"
        filter_dict["value"] = object_type
    
    if created_by:
        if not filter_dict:
            filter_dict = {"property": "created_by", "value": created_by}
        else:
            # Combine filters with AND logic
            filter_dict = {
                "and": [
                    filter_dict,
                    {"property": "created_by", "value": created_by}
                ]
            }
    
    if last_edited_time:
        if not filter_dict:
            filter_dict = {"property": "last_edited_time", **last_edited_time}
        else:
            filter_dict = {
                "and": [
                    filter_dict,
                    {"property": "last_edited_time", **last_edited_time}
                ]
            }
    
    if filter_dict:
        args["filter"] = filter_dict
    
    return safe_execute(notion.search, **args)

@mcp.tool()
def search_by_property(query: str, property_name: str, property_type: str = "title"):
    """
    Search for content within specific properties.
    - query: Text to search for
    - property_name: Name of the property to search in
    - property_type: Type of property ('title', 'rich_text', 'select', etc.)
    """
    filter_dict = {
        "property": property_name,
        property_type: {"contains": query}
    }
    
    return safe_execute(notion.search, filter=filter_dict)

@mcp.tool()
def search_recently_modified(days: int = 7, object_type: str = None):
    """
    Search for recently modified content.
    - days: Number of days to look back (default 7)
    - object_type: Filter by object type ('page', 'database')
    """
    from datetime import datetime, timedelta
    
    cutoff_date = datetime.now() - timedelta(days=days)
    cutoff_iso = cutoff_date.isoformat()
    
    filter_dict = {
        "property": "last_edited_time",
        "last_edited_time": {"after": cutoff_iso}
    }
    
    if object_type:
        filter_dict = {
            "and": [
                filter_dict,
                {"property": "object", "value": object_type}
            ]
        }
    
    return safe_execute(notion.search, filter=filter_dict)

# ==================================================
# HEALTH CHECK TOOLS
# ==================================================

@mcp.tool()
def health_check():
    """Check server and Notion API health status"""
    try:
        # Test Notion API connection
        user_info = notion.users.me()
        
        return {
            "successful": True,
            "data": {
                "status": "healthy",
                "notion_api": "connected",
                "user_id": user_info.get("id"),
                "workspace": user_info.get("bot", {}).get("workspace_name"),
                "rate_limiter": "active",
                "error_handling": "enhanced"
            },
            "error": ""
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "successful": False,
            "data": {
                "status": "unhealthy",
                "notion_api": "disconnected",
                "error": str(e)
            },
            "error": f"Health check failed: {e}"
        }

@mcp.tool()
def get_server_info():
    """Get server configuration and status information"""
    return {
        "successful": True,
        "data": {
            "server_name": "notion-user-mcp-server",
            "version": "2.0.0",
            "features": {
                "rate_limiting": True,
                "comments_system": True,
                "advanced_search": True,
                "enhanced_error_handling": True,
                "input_validation": True,
                "logging": True
            },
            "total_tools": 28,
            "notion_api_version": "2022-06-28",
            "rate_limit": "3 requests/second"
        },
        "error": ""
    }

# ==================================================
# RUN SERVER
# ==================================================
if __name__ == "__main__":
    logger.info("Starting Notion MCP Server ")
    logger.info("Features: Rate Limiting, Comments, Advanced Search, Enhanced Error Handling")
    mcp.run()
