# Notion MCP Server

A powerful Model Context Protocol (MCP) server that provides seamless integration with Notion's API. This server enables AI assistants and applications to interact with Notion workspaces, manage databases, create and update pages, and perform various content operations.

## 🚀 Overview

The Notion MCP Server is built using FastMCP and provides a comprehensive set of tools to:

- **User Management**: List users and retrieve detailed user information
- **Database Operations**: Create, read, update, and manage Notion databases
- **Page Management**: Create, update, delete, and retrieve page content
- **Content Operations**: Fetch and manipulate page blocks and content

This project simplifies Notion API integration for AI assistants, automation tools, and custom applications by providing a standardized MCP interface.

## ✨ Features

### User Tools
- 👥 **List Users**: Get all users with names and IDs
- 🔍 **User Properties**: Fetch detailed user information

### Database Tools  
- 📊 **List Databases**: Get all databases with titles and IDs
- 🔧 **Database Properties**: Retrieve complete database metadata
- ➕ **Create Database**: Create new databases under parent pages
- ✏️ **Update Database**: Modify database titles and properties

### Page Tools
- 📄 **List Pages**: Get all pages with names and IDs  
- 📋 **Page Properties**: Retrieve complete page metadata
- 🆕 **Create Page**: Create new pages in databases or under parent pages
- ✏️ **Update Page**: Modify page properties, icons, and covers
- 🗑️ **Delete Page**: Archive/delete pages
- 📖 **Get Content**: Fetch page content and child blocks

## 🛠️ Installation

### Prerequisites
- Python 3.11 or higher
- A Notion API key (from [Notion Developers](https://developers.notion.com/))

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/jagandevloper/mcp-project.git
   cd mcp-project/notion
   ```

2. **Install dependencies:**
   ```bash
   pip install -e .
   ```

3. **Set up environment variables:**
   ```bash
   # Copy the example environment file
   cp .env.example .env
   
   # Edit .env and add your Notion API key
   echo "NOTION_API_KEY=your_notion_api_key_here" > .env
   ```

4. **Run the MCP server:**
   ```bash
   python new.py
   ```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the notion directory with the following variables:

```bash
NOTION_API_KEY=your_notion_api_key_here
```

### Getting a Notion API Key

1. Go to [Notion Developers](https://developers.notion.com/)
2. Click "Create new integration"
3. Give your integration a name and select the workspace
4. Copy the generated API key
5. Add the integration to your Notion pages/databases by going to the page settings and adding your integration

## 📚 API Reference

### User Management Tools

#### `list_users()`
Lists all users in the workspace.

**Returns:** List of users with `id` and `name` fields.

**Example:**
```python
{
  "successful": true,
  "data": [
    {"id": "user_123", "name": "John Doe"},
    {"id": "user_456", "name": "Jane Smith"}
  ],
  "error": ""
}
```

#### `user_properties(user_id: str)`
Retrieves detailed information about a specific user.

**Parameters:**
- `user_id` (str): The ID of the user

**Returns:** Complete user object with all properties.

### Database Tools

#### `list_databases()`
Lists all databases accessible to the integration.

**Returns:** List of databases with `id` and `title` fields.

#### `database_properties(database_id: str)`
Retrieves complete metadata for a database.

**Parameters:**
- `database_id` (str): The ID of the database

**Returns:** Complete database object with properties, schema, and metadata.

#### `create_database(parent_page_id: str, title: str, properties: dict)`
Creates a new database under a parent page.

**Parameters:**
- `parent_page_id` (str): The ID of the parent page
- `title` (str): The title of the new database
- `properties` (dict): Database schema properties

**Example:**
```python
create_database(
    parent_page_id="page_123",
    title="My Database",
    properties={
        "Name": {"title": {}},
        "Status": {"select": {"options": [{"name": "To Do"}, {"name": "Done"}]}}
    }
)
```

#### `update_database(database_id: str, title: str = None, properties: dict = None)`
Updates a database's title or properties.

**Parameters:**
- `database_id` (str): The ID of the database
- `title` (str, optional): New title for the database
- `properties` (dict, optional): Updated properties schema

### Page Tools

#### `list_pages()`
Lists all pages accessible to the integration.

**Returns:** List of pages with `id` and `name` fields.

#### `page_properties(page_id: str)`
Retrieves complete metadata for a page.

**Parameters:**
- `page_id` (str): The ID of the page

**Returns:** Complete page object with all properties and metadata.

#### `create_page(parent_id: str, title: str, icon: str = None, cover: str = None)`
Creates a new page under a parent (database or page).

**Parameters:**
- `parent_id` (str): The ID of the parent page or database
- `title` (str): The title of the new page
- `icon` (str, optional): Emoji or icon URL
- `cover` (str, optional): Cover image URL

**Example:**
```python
create_page(
    parent_id="database_123",
    title="My New Page",
    icon="📝",
    cover="https://example.com/cover.jpg"
)
```

#### `update_page(page_id: str, properties: dict = None, icon: str = None, cover: str = None)`
Updates a page's properties, icon, or cover.

**Parameters:**
- `page_id` (str): The ID of the page
- `properties` (dict, optional): Updated page properties
- `icon` (str, optional): New icon (emoji or URL)
- `cover` (str, optional): New cover image URL

#### `delete_page(page_id: str)`
Archives (deletes) a page.

**Parameters:**
- `page_id` (str): The ID of the page to delete

#### `get_page_content(page_id: str)`
Retrieves the content blocks of a page.

**Parameters:**
- `page_id` (str): The ID of the page

**Returns:** List of child blocks containing the page content.

## 🔧 Usage Examples

### Basic Usage with MCP Client

```python
import asyncio
from mcp.client import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server_params = StdioServerParameters(
        command="python",
        args=["new.py"],
        cwd="/path/to/notion"
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()
            
            # List all users
            result = await session.call_tool("list_users", {})
            print("Users:", result)
            
            # Create a new page
            result = await session.call_tool("create_page", {
                "parent_id": "your_parent_id",
                "title": "Hello from MCP!",
                "icon": "🚀"
            })
            print("Created page:", result)

if __name__ == "__main__":
    asyncio.run(main())
```

### Using with Claude Desktop

Add this configuration to your Claude Desktop MCP settings:

```json
{
  "mcpServers": {
    "notion": {
      "command": "python",
      "args": ["/path/to/mcp-project/notion/new.py"],
      "env": {
        "NOTION_API_KEY": "your_notion_api_key_here"
      }
    }
  }
}
```

## 🔍 Error Handling

All tools return a standardized response format:

```python
{
  "successful": bool,      # True if operation succeeded
  "data": object,         # The result data
  "error": str           # Error message if unsuccessful
}
```

Common error scenarios:
- **Invalid API Key**: Ensure your `NOTION_API_KEY` is correct
- **Permission Errors**: Make sure your integration has access to the target pages/databases
- **Invalid IDs**: Verify that page/database IDs are correct and accessible

## 🧪 Testing

To test the MCP server:

1. **Test the installation:**
   ```bash
   cd notion
   python -c "import notion_client, mcp, fastmcp; print('Dependencies OK')"
   ```

2. **Test the server startup:**
   ```bash
   python new.py
   ```

3. **Test with MCP inspector:**
   ```bash
   npx @modelcontextprotocol/inspector python new.py
   ```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes and add tests
4. Commit your changes: `git commit -am 'Add some feature'`
5. Push to the branch: `git push origin feature/your-feature`
6. Submit a pull request

### Development Setup

```bash
# Clone the repo
git clone https://github.com/jagandevloper/mcp-project.git
cd mcp-project/notion

# Install in development mode
pip install -e .

# Set up environment
cp .env.example .env
# Edit .env with your API key
```

## 🐛 Troubleshooting

### Common Issues

**1. Import Errors**
```bash
# Make sure all dependencies are installed
pip install -e .
```

**2. API Key Issues**
```bash
# Verify your API key is set correctly
echo $NOTION_API_KEY
```

**3. Permission Errors**
- Ensure your Notion integration has access to the pages/databases
- Check that the integration is added to your workspace
- Verify the correct permissions are granted in Notion

**4. Connection Issues**
- Check your internet connection
- Verify Notion API is accessible
- Try making a direct API call to test connectivity

### Getting Help

- Check the [Notion API documentation](https://developers.notion.com/)
- Open an issue on [GitHub](https://github.com/jagandevloper/mcp-project/issues)
- Review the MCP specification at [Model Context Protocol](https://modelcontextprotocol.io/)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Notion API](https://developers.notion.com/) for the excellent API
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP specification
- [FastMCP](https://github.com/jlowin/fastmcp) for the FastMCP framework

---

Made with ❤️ by [jagandevloper](https://github.com/jagandevloper)
