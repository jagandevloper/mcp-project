import os
from dotenv import load_dotenv
from notion_client import Client, APIResponseError
from mcp.server.fastmcp import FastMCP
from typing import Dict, Any
# ---------- Load environment ----------
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

if not NOTION_API_KEY:
    raise ValueError("Missing NOTION_API_KEY in .env")

notion = Client(auth=NOTION_API_KEY)
mcp = FastMCP("notion-user-mcp-server")


# ---------- Helper ----------
def safe_execute(func, *args, **kwargs):
    try:
        data = func(*args, **kwargs)
        return {"successful": True, "data": data, "error": ""}
    except APIResponseError as e:
        return {"successful": False, "data": {}, "error": str(e)}
    except Exception as e:
        return {"successful": False, "data": {}, "error": str(e)}


# ==================================================
# USER TOOLS
# ==================================================

@mcp.tool()
def get_about_me():
    """ Get details 
    """
    return safe_execute(notion.users.me)


@mcp.tool()
def list_users():
    """
    List all users (id + name) 
    """
    res = safe_execute(notion.users.list)
    if res["successful"]:
        simplified = [{"id": u["id"], "name": u.get("name", "Unknown")}
                      for u in res["data"].get("results", [])]
        res["data"] = simplified
    return res


@mcp.tool()
def retrieve_user(user_id: str):
    """
    Retrieve full information about a specific user.
    """
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
    return safe_execute(notion.databases.retrieve, database_id)

@mcp.tool()
def create_database(parent_page_id: str, title: str, properties: dict):
    """Create a new database under a parent page."""
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
    args = {}
    if title:
        args["title"] = [{"text": {"content": title}}]
    if properties:
        args["properties"] = properties
    return safe_execute(notion.databases.update, database_id, **args)

@mcp.tool()
def query_database(database_id: str, filter: dict = None, sorts: list = None, page_size: int = 100):
    """
    Query row  from a database
    """
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
                        properties={},
                        children=content_res["data"].get("results", []),
                        title=[{"text": {"content": new_title}}])
@mcp.tool()
def list_pages(keyword: str = None):
    res = safe_execute(notion.search, filter={"property": "object", "value": "page"})
    if not res["successful"]:
        return res

    pages = []
    for pg in res["data"].get("results", []):
        title = "Untitled"
        try:
            title = "".join([t["plain_text"] for t in pg["properties"]["Name"]["title"]])
        except:
            pass
        if not keyword or keyword.lower() in title.lower():
            pages.append({"id": pg["id"], "title": title, "url": pg.get("url")})
    return {"successful": True, "data": pages, "error": ""}

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

# ==================================================
# Getting ID's
# ==================================================
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
# RUN SERVER
# ==================================================
if __name__ == "__main__":
    mcp.run()
