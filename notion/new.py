import os
from dotenv import load_dotenv
from notion_client import Client, APIResponseError
from mcp.server.fastmcp import FastMCP
import mcp 

# Load environment
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

if not NOTION_API_KEY:
    raise ValueError("Missing NOTION_API_KEY in .env")

notion = Client(auth=NOTION_API_KEY)
mcp = FastMCP("notion-mcp-server")


# ---------- Helper ----------
def safe_execute(func, *args, **kwargs):
    try:
        data = func(*args, **kwargs)
        return {"successful": True, "data": data, "error": ""}
    except APIResponseError as e:
        return {"successful": False, "data": {}, "error": str(e)}
    except Exception as e:
        return {"successful": False, "data": {}, "error": str(e)}


# ---------- USER TOOLS ----------

@mcp.tool()
def list_users():
    """List all users (only names and ids)."""
    res = safe_execute(notion.users.list)
    if res["successful"]:
        simplified = [
            {"id": u["id"], "name": u.get("name", "Unknown")}
            for u in res["data"].get("results", [])
        ]
        res["data"] = simplified
    return res


@mcp.tool()
def user_properties(user_id: str):
    """Fetch all details about a user."""
    return safe_execute(notion.users.retrieve, user_id)


# ---------- DATABASE TOOLS ----------

@mcp.tool()
def list_databases():
    """List all databases (name + id)."""
    # There’s no direct list_databases, we search with filter
    res = safe_execute(notion.search, filter={"property": "object", "value": "database"})
    if res["successful"]:
        simplified = [
            {
                "id": db["id"],
                "title": db["title"][0]["plain_text"] if db.get("title") else "Untitled",
            }
            for db in res["data"].get("results", [])
        ]
        res["data"] = simplified
    return res


@mcp.tool()
def database_properties(database_id: str):
    """Fetch all metadata of a database."""
    return safe_execute(notion.databases.retrieve, database_id)


@mcp.tool()
def create_database(parent_page_id: str, title: str, properties: dict):
    """Create a database under a parent page."""
    if "Name" not in properties:
        properties["Name"] = {"title": {}}
    return safe_execute(
        notion.databases.create,
        parent={"page_id": parent_page_id},
        title=[{"text": {"content": title}}],
        properties=properties,
    )


@mcp.tool()
def update_database(database_id: str, title: str = None, properties: dict = None):
    """Update a database title or properties."""
    args = {}
    if title:
        args["title"] = [{"text": {"content": title}}]
    if properties:
        args["properties"] = properties
    return safe_execute(notion.databases.update, database_id, **args)


# ---------- PAGE TOOLS ----------

@mcp.tool()
def list_pages():
    """List all pages (name + id)."""
    res = safe_execute(notion.search, filter={"property": "object", "value": "page"})
    if res["successful"]:
        simplified = []
        for pg in res["data"].get("results", []):
            name = "Untitled"
            try:
                name = pg["properties"]["Name"]["title"][0]["plain_text"]
            except Exception:
                pass
            simplified.append({"id": pg["id"], "name": name})
        res["data"] = simplified
    return res


@mcp.tool()
def page_properties(page_id: str):
    """Get all properties of a page."""
    return safe_execute(notion.pages.retrieve, page_id)


@mcp.tool()
def delete_page(page_id: str):
    """Delete/archive a page."""
    return safe_execute(notion.pages.update, page_id, archived=True)


@mcp.tool()
def get_page_content(page_id: str):
    """Fetch child blocks (content) of a page."""
    return safe_execute(notion.blocks.children.list, page_id)


@mcp.tool()
def create_page(parent_id: str, title: str, icon: str = None, cover: str = None):
    """
    Create a new page under any parent (database or page).
    - parent_id: ID of parent page or database
    - title: Page title
    - icon: optional emoji or URL
    - cover: optional image URL
    """
    try:
        # Check if parent is a database or page
        parent_obj = notion.databases.retrieve(parent_id)
        is_database = True
    except APIResponseError:
        # If retrieving as database fails, assume it’s a page
        is_database = False

    if is_database:
        # Creating page in a database requires properties
        properties = {
            "Name": {"title": [{"text": {"content": title}}]}
        }
        response = notion.pages.create(
            parent={"database_id": parent_id},
            properties=properties,
            icon={"emoji": icon} if icon else None,
            cover={"external": {"url": cover}} if cover else None,
        )
    else:
        # Creating page under a normal page
        response = notion.pages.create(
            parent={"page_id": parent_id},
            icon={"emoji": icon} if icon else None,
            cover={"external": {"url": cover}} if cover else None,
            properties={},
            children=[
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": [{"text": {"content": title}}]}
                }
            ]
        )

    return {"successful": True, "data": response, "error": ""}



@mcp.tool()
def update_page(page_id: str, properties: dict = None, icon: str = None, cover: str = None):
    """Update a page’s properties, icon, or cover."""
    return safe_execute(
        notion.pages.update,
        page_id,
        properties=properties or {},
        icon={"emoji": icon} if icon else None,
        cover={"external": {"url": cover}} if cover else None,
    )


# ---------- RUN ----------
if __name__ == "__main__":
    mcp.run()
