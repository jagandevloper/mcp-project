# Tally MCP Server

A comprehensive Model Context Protocol (MCP) server for managing Tally forms, webhooks, workspaces, and submissions. This server provides access to all major Tally API operations through a standardized MCP interface.

## Features

This MCP server provides 16 tools covering all aspects of Tally management:

### Form Management
- **TALLY_CREATE_FORM**: Create new forms with blocks and settings
- **TALLY_UPDATE_FORM**: Update existing form details, blocks, and settings
- **TALLY_DELETE_FORM**: Permanently delete forms
- **TALLY_GET_FORM_DETAILS**: Retrieve comprehensive form metadata
- **TALLY_GET_FORM_FIELDS**: Get form field definitions
- **TALLY_GET_FORM_SETTINGS**: Retrieve form configuration settings
- **TALLY_LIST_FORMS**: List all accessible forms with pagination

### Data Retrieval
- **TALLY_GET_FORM_RESPONSES**: Retrieve form responses with pagination
- **TALLY_LIST_SUBMISSIONS**: List form submissions with pagination

### Webhook Management
- **TALLY_CREATE_WEBHOOK**: Create webhooks for form events
- **TALLY_DELETE_WEBHOOK**: Remove webhooks
- **TALLY_LIST_WEBHOOKS**: List all configured webhooks
- **TALLY_GET_WEBHOOK_EVENTS**: Inspect webhook delivery history

### Workspace & User Management
- **TALLY_LIST_WORKSPACES**: List accessible workspaces
- **TALLY_UPDATE_WORKSPACE**: Update workspace details
- **TALLY_GET_USER_INFO**: Get authenticated user information

## Installation

1. Install dependencies:
```bash
pip install -e .
```

2. Set up your Tally API key:
```bash
export TALLY_API_KEY="your_tally_api_key_here"
```

## Usage

### Running the Server

You have two options for running the server:

#### Option 1: Full MCP Server (main.py)
```bash
python main.py
```

#### Option 2: FastMCP Server (Simplified)
```bash
python fastmcp_server.py
```

The FastMCP version is easier to run and debug, while the full MCP server provides more comprehensive error handling and follows the complete MCP specification.

### Tool Usage Examples

#### Creating a Form
```json
{
  "name": "TALLY_CREATE_FORM",
  "arguments": {
    "blocks": [
      {
        "type": "text",
        "label": "What's your name?",
        "required": true
      },
      {
        "type": "email",
        "label": "Email address",
        "required": true
      }
    ],
    "settings": {
      "language": "en",
      "redirectOnCompletion": "https://example.com/thank-you"
    },
    "status": "PUBLISHED"
  }
}
```

#### Creating a Webhook
```json
{
  "name": "TALLY_CREATE_WEBHOOK",
  "arguments": {
    "formId": "form_abc123",
    "url": "https://your-app.com/webhook/tally",
    "eventTypes": ["FORM_RESPONSE"],
    "signingSecret": "your_secret_key"
  }
}
```

#### Getting Form Details
```json
{
  "name": "TALLY_GET_FORM_DETAILS",
  "arguments": {
    "formId": "form_abc123"
  }
}
```

#### Listing Forms with Pagination
```json
{
  "name": "TALLY_LIST_FORMS",
  "arguments": {
    "page": 1
  }
}
```

#### Getting Form Responses
```json
{
  "name": "TALLY_GET_FORM_RESPONSES",
  "arguments": {
    "formId": "form_abc123",
    "limit": 50,
    "page": 1
  }
}
```

## Configuration

### Environment Variables

- `TALLY_API_KEY`: Your Tally API key (required)

### API Endpoints

The server connects to the Tally API at `https://api.tally.so` and uses Bearer token authentication.

## Tool Parameters

### Required Parameters
Tools with `[REQUIRED]` parameters will fail if these are not provided:
- `TALLY_CREATE_WEBHOOK`: `formId`, `url`
- `TALLY_DELETE_FORM`: `formId`
- `TALLY_DELETE_WEBHOOK`: `webhookId`
- `TALLY_GET_FORM_DETAILS`: `formId`
- `TALLY_GET_FORM_FIELDS`: `formId`
- `TALLY_GET_FORM_RESPONSES`: `formId`
- `TALLY_GET_FORM_SETTINGS`: `formId`
- `TALLY_GET_WEBHOOK_EVENTS`: `webhookId`
- `TALLY_LIST_SUBMISSIONS`: `formId`
- `TALLY_UPDATE_FORM`: `formId`
- `TALLY_UPDATE_WORKSPACE`: `workspaceId`

### Optional Parameters
All other parameters are optional and can be omitted if not needed.

### Settings Object Structure
When using settings in form creation or updates:
```json
{
  "settings": {
    "isClosed": false,
    "language": "en",
    "redirectOnCompletion": "https://example.com/thank-you"
  }
}
```

## Error Handling

The server includes comprehensive error handling:
- API errors are caught and returned with descriptive messages
- Missing required parameters are validated
- HTTP errors are properly formatted and returned
- Network timeouts are handled gracefully

## Development

### Project Structure
```
tally/
├── main.py              # Full MCP server entry point
├── fastmcp_server.py    # Simplified FastMCP server
├── tools.py             # Tool definitions and schemas
├── handlers.py          # Tool implementation handlers
├── pyproject.toml      # Project configuration
├── config.example      # Configuration template
└── README.md           # This file
```

### Adding New Tools

1. Add tool definition to `tools.py`
2. Add handler function to `handlers.py`
3. Add tool routing to `main.py` in the `call_tool` function

## License

This project is open source and available under the MIT License.

## Support

For issues related to:
- This MCP server: Create an issue in this repository
- Tally API: Contact Tally support
- MCP protocol: Refer to MCP documentation

