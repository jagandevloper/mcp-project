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
- **TALLY_GET_FORM_SETTINGS**:Retrieve the settings of a specific form

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
# Option 1: Environment variable
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





### API Configuration

The server connects to the Tally API at `https://api.tally.so` and uses Bearer token authentication.

## 📋 Tool Parameters Reference

### Required Parameters
Tools marked with `[REQUIRED]` will fail if these parameters are not provided:

- **TALLY_CREATE_FORM**: `status`, `blocks`
- **TALLY_CREATE_WEBHOOK**: `formId`, `url`
- **TALLY_DELETE_FORM**: `formId`
- **TALLY_DELETE_SUBMISSION**: `formId`, `submissionId`
- **TALLY_DELETE_WEBHOOK**: `webhookId`
- **TALLY_GET_FORM**: `formId`
- **TALLY_GET_SUBMISSION**: `formId`, `submissionId`
- **TALLY_GET_WORKSPACE**: `workspaceId`
- **TALLY_LIST_FORM_QUESTIONS**: `formId`
- **TALLY_LIST_SUBMISSIONS**: `formId`
- **TALLY_LIST_WEBHOOK_EVENTS**: `webhookId`
- **TALLY_UPDATE_FORM**: `formId`
- **TALLY_UPDATE_WORKSPACE**: `workspaceId`, `name`
- **TALLY_UPDATE_WEBHOOK**: `webhookId`, `formId`, `url`

### Optional Parameters
All other parameters are optional and can be omitted if not needed.

## 🗃️ Database Setup (for Flask server)

If using the Flask webhook server, set up MySQL:

```sql
CREATE DATABASE mcp_tally;
USE mcp_tally;

CREATE TABLE submissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

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


### Adding New Tools

1. Add the tool function with `@mcp.tool()` decorator
2. Implement proper error handling
3. Add comprehensive docstring
4. Test with various parameter combinations

### Testing

Test individual tools using the MCP client or by running the server and making direct API calls.



## 📞 Support

For issues related to:
- **This MCP server**: Create an issue in this repository
- **Tally API**: Contact [Tally support](https://tally.so/help)
- **MCP protocol**: Refer to [MCP documentation](https://modelcontextprotocol.io/)



---




