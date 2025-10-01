# Tally MCP Server

A comprehensive Model Context Protocol (MCP) server for managing Tally forms, webhooks, workspaces, and submissions. This server provides access to all major Tally API operations through a standardized MCP interface using FastMCP.

## 🚀 Features

This MCP server provides **19 tools** covering all aspects of Tally management:

### 👤 User Management
- **TALLY_GET_USER_INFO**: Get authenticated user information

### 🏢 Workspace Management
- **TALLY_LIST_WORKSPACES**: List all accessible workspaces with pagination
- **TALLY_GET_WORKSPACE**: Retrieve details of a specific workspace
- **TALLY_UPDATE_WORKSPACE**: Update workspace name and settings

### 📝 Form Management
- **TALLY_CREATE_FORM**: Create new forms with blocks, settings, and templates
- **TALLY_UPDATE_FORM**: Update existing form details, blocks, and settings
- **TALLY_DELETE_FORM**: Permanently delete forms (moves to trash)
- **TALLY_GET_FORM**: Retrieve comprehensive form metadata with all blocks
- **TALLY_LIST_FORMS**: List all accessible forms with pagination and filtering
- **TALLY_LIST_FORM_QUESTIONS**: Get all questions for a specific form
- **TALLY_GET_FORM_SETTINGS**: Get form settings and configuration

### 📊 Submission Management
- **TALLY_LIST_SUBMISSIONS**: List form submissions with pagination and filtering
- **TALLY_GET_SUBMISSION**: Retrieve specific submission with all responses
- **TALLY_DELETE_SUBMISSION**: Delete specific submissions

### 🔗 Webhook Management
- **TALLY_CREATE_WEBHOOK**: Create webhooks for form events
- **TALLY_UPDATE_WEBHOOK**: Update existing webhook configuration
- **TALLY_DELETE_WEBHOOK**: Remove webhooks
- **TALLY_LIST_WEBHOOKS**: List all configured webhooks
- **TALLY_LIST_WEBHOOK_EVENTS**: Inspect webhook delivery history

## 📦 Installation

### Prerequisites
- Python 3.11+
- Tally API key

### Setup

1. **Clone and navigate to the project:**
```bash
cd tally
```

2. **Install dependencies using uv:**
```bash
uv sync
```

3. **Set up your Tally API key:**
```bash
# Option 1: Environment variable (Recommended)
export TALLY_API_KEY="your_tally_api_key_here"

# Option 2: Direct in code (for development only)
# Edit tally_o.py and update TALLY_API_KEY variable
```

## 🚀 Usage

### Running the Server

#### Main MCP Server (tally_o.py)
```bash
python tally_o.py
```

The server will start and be ready to accept MCP client connections.

### MCP Client Configuration

#### For Claude Desktop

Add this configuration to your Claude Desktop config file:

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux**: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tally-mcp": {
      "command": "python",
      "args": ["tally_o.py"],
      "cwd": "/path/to/your/tally/directory",
      "env": {
        "TALLY_API_KEY": "your_tally_api_key_here"
      }
    }
  }
}
```

#### For Other MCP Clients

```json
{
  "servers": {
    "tally": {
      "command": "python",
      "args": ["tally_o.py"],
      "cwd": "/path/to/your/tally/directory",
      "env": {
        "TALLY_API_KEY": "your_tally_api_key_here",
        "TALLY_API_BASE_URL": "https://api.tally.so",
        "TALLY_TIMEOUT": "30.0"
      }
    }
  }
}
```

### Tool Usage Examples

#### Creating a Form
```python
# Example form creation with blocks
blocks = [
    {
        "type": "text",
        "label": "What's your name?",
        "required": True
    },
    {
        "type": "email", 
        "label": "Email address",
        "required": True
    },
    {
        "type": "textarea",
        "label": "Tell us about yourself",
        "required": False
    }
]

settings = {
    "language": "en",
    "redirectOnCompletion": "https://example.com/thank-you"
}

# Call TALLY_CREATE_FORM tool
result = await TALLY_CREATE_FORM(
    status="PUBLISHED",
    blocks=blocks,
    settings=settings,
    workspaceId="your_workspace_id"  # optional
)
```

#### Creating a Webhook
```python
# Create webhook for form submissions
result = await TALLY_CREATE_WEBHOOK(
    formId="form_abc123",
    url="https://your-app.com/webhook/tally",
    eventTypes=["FORM_RESPONSE"],
    signingSecret="your_secret_key"  # optional
)
```

#### Getting Form Details
```python
# Retrieve complete form information
form_data = await TALLY_GET_FORM(formId="form_abc123")
```

#### Listing Forms with Pagination
```python
# Get first page of forms
forms = await TALLY_LIST_FORMS(page=1, limit=50)

# Filter by workspace
workspace_forms = await TALLY_LIST_FORMS(
    page=1, 
    limit=50, 
    workspaceId="workspace_xyz"
)
```

#### Getting Form Submissions
```python
# Get all submissions
submissions = await TALLY_LIST_SUBMISSIONS(
    formId="form_abc123",
    page=1,
    filter="all"  # or "completed", "partial"
)

# Get specific submission
submission = await TALLY_GET_SUBMISSION(
    formId="form_abc123",
    submissionId="submission_xyz"
)
```

## ⚙️ Configuration

### Environment Variables

- `TALLY_API_KEY`: Your Tally API key (required)
- `TALLY_API_BASE_URL`: API base URL (default: https://api.tally.so)
- `TALLY_TIMEOUT`: Request timeout in seconds (default: 30.0)
- `TALLY_LOG_LEVEL`: Logging level (default: INFO)

### API Configuration

The server connects to the Tally API at `https://api.tally.so` and uses Bearer token authentication.

## 📋 Complete Tools Reference

| Tool Name | Category | Description | Required Parameters | Optional Parameters |
|-----------|----------|-------------|-------------------|-------------------|
| **TALLY_GET_USER_INFO** | User | Get authenticated user information | None | None |
| **TALLY_GET_WORKSPACE** | Workspace | Get workspace details | `workspaceId: str` | None |
| **TALLY_LIST_WORKSPACES** | Workspace | List all workspaces | None | `page: int = 1` |
| **TALLY_UPDATE_WORKSPACE** | Workspace | Update workspace name | `workspaceId: str`, `name: str` | None |
| **TALLY_CREATE_FORM** | Form | Create a new form | `status: str`, `blocks: List[Dict]` | `workspaceId: str`, `templateId: str`, `settings: Dict` |
| **TALLY_UPDATE_FORM** | Form | Update existing form | `formId: str` | `name: str`, `status: str`, `blocks: List[Dict]`, `settings: Dict` |
| **TALLY_DELETE_FORM** | Form | Delete a form | `formId: str` | None |
| **TALLY_GET_FORM** | Form | Get form details | `formId: str` | None |
| **TALLY_LIST_FORMS** | Form | List all forms | None | `page: int = 1`, `limit: int = 50`, `workspaceId: str` |
| **TALLY_LIST_FORM_QUESTIONS** | Form | Get form questions | `formId: str` | None |
| **TALLY_GET_FORM_SETTINGS** | Form | Get form settings | `formId: str` | None |
| **TALLY_LIST_SUBMISSIONS** | Submission | List form submissions | `formId: str` | `page: int = 1`, `filter: str = "all"`, `startDate: str`, `endDate: str`, `afterId: str` |
| **TALLY_GET_SUBMISSION** | Submission | Get specific submission | `formId: str`, `submissionId: str` | None |
| **TALLY_DELETE_SUBMISSION** | Submission | Delete a submission | `formId: str`, `submissionId: str` | None |
| **TALLY_CREATE_WEBHOOK** | Webhook | Create webhook | `formId: str`, `url: str` | `eventTypes: List[str] = ["FORM_RESPONSE"]`, `signingSecret: str`, `httpHeaders: List[Dict]`, `externalSubscriber: str` |
| **TALLY_UPDATE_WEBHOOK** | Webhook | Update webhook | `webhookId: str`, `formId: str`, `url: str` | `eventTypes: List[str] = ["FORM_RESPONSE"]`, `isEnabled: bool = True`, `signingSecret: str`, `httpHeaders: List[Dict]` |
| **TALLY_DELETE_WEBHOOK** | Webhook | Delete webhook | `webhookId: str` | None |
| **TALLY_LIST_WEBHOOKS** | Webhook | List all webhooks | None | `page: int = 1`, `limit: int = 25` |
| **TALLY_LIST_WEBHOOK_EVENTS** | Webhook | List webhook events | `webhookId: str` | `page: int = 1` |

## 🔧 Error Handling

The server includes comprehensive error handling:

- **401 Unauthorized**: Invalid or missing API key
- **403 Forbidden**: Insufficient permissions
- **404 Not Found**: Resource doesn't exist
- **400 Bad Request**: Invalid parameters or data
- **Network Errors**: Graceful handling of connection issues
- **Validation Errors**: Missing required parameters

All errors are returned with descriptive messages and appropriate HTTP status codes.

## 📁 Project Structure

```
tally/
├── tally_o.py           # Main MCP server with all tools
├── pyproject.toml       # Project dependencies and configuration
├── uv.lock             # Dependency lock file
├── README.md           # This documentation
└── __pycache__/        # Python cache files
```

## 🛠️ Development

### Dependencies

The project uses the following key dependencies:
- `mcp[cli]>=1.0.0`: Model Context Protocol framework
- `httpx>=0.25.0`: Async HTTP client
- `fastmcp>=0.1.0`: FastMCP server implementation
- `fastapi>=0.117.1`: Web framework for additional endpoints

### Adding New Tools

1. Add the tool function with `@mcp.tool()` decorator
2. Implement proper error handling
3. Add comprehensive docstring
4. Test with various parameter combinations

### Testing

Test individual tools using the MCP client or by running the server and making direct API calls.

## 🔒 Security Notes

- **API Key**: Never commit your Tally API key to version control
- **Webhook Security**: Use signing secrets for webhook verification
- **Environment**: Use environment variables for sensitive configuration
- **Network**: Use HTTPS for all API communications



