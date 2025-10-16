# Discord Bot MCP Server v2.0.0

A comprehensive Discord Bot MCP (Model Context Protocol) server implementation with **190 Discord API tools** based on the [Composio Discord Toolkit](https://docs.composio.dev/toolkits/discordbot#tool-list).

## 🚀 Features

This MCP server provides comprehensive Discord bot functionality with **190 tools** covering:

### 📨 Message Management (16 tools)
- Create, read, update, and delete messages
- Pin/unpin messages and list pinned messages
- Manage message reactions (add, remove, list)
- Bulk message operations
- Crosspost messages for announcements

### 🏰 Guild Management (5 tools)
- Create, update, and delete guilds
- Get guild information
- Leave guilds

### 👑 Role Management (4 tools)
- Create, update, and delete guild roles
- List guild roles
- Role permissions and settings

### 👥 Member Management (8 tools)
- Add, update, and remove guild members
- Manage member roles
- Search and list guild members
- Member information retrieval

### 🚫 Ban Management (5 tools)
- Ban and unban users from guilds
- Bulk ban operations
- List guild bans
- Get ban information

### 📺 Channel Management (5 tools)
- Create, update, and delete channels
- Get channel information
- List guild channels
- Channel settings and permissions

### 🧵 Thread Management (12 tools)
- Create threads and threads from messages
- Join/leave threads
- Add/remove thread members
- List thread members
- Manage archived threads (public, private, user-specific)
- Get active guild threads

### 🔧 Utility Tools (10 tools)
- User information and management
- Gateway information
- Typing indicators
- DM channel management
- Group DM operations
- Public keys for verification

### 📅 Scheduled Events (6 tools)
- Create, update, and delete guild scheduled events
- List scheduled events and event users
- Event management and user subscriptions

### 📋 Guild Templates (7 tools)
- Create and manage guild templates
- Sync templates and create guilds from templates
- Template operations and management

### 🎫 Invite Management (7 tools)
- Create and manage channel invites
- List guild and channel invites
- Invite resolution and revocation

### 🛡️ Auto Moderation (5 tools)
- Create and manage auto moderation rules
- Rule configuration and management
- Automated content moderation

### 🎭 Stage Instances (4 tools)
- Create and manage stage instances
- Stage instance operations
- Voice channel stage management

### 🎤 Voice State (2 tools)
- Update voice states for users
- Voice channel state management

### ⚡ Interaction Responses (4 tools)
- Create and manage interaction responses
- Original response management
- Interaction handling

### 🔧 Additional Tools (30+ tools)
- Channel permission overwrites
- Guild widgets and vanity URLs
- Welcome screens and onboarding
- Audit logs and integrations
- Voice regions and guild pruning
- Channel following and more

## 📦 Installation

1. Install dependencies:
```bash
pip install httpx fastmcp mcp[cli]
```

2. Set up your Discord bot token:
```bash
export DISCORD_BOT_TOKEN="your_bot_token_here"
```

3. Run the server:
```bash
python discordbot.py
```

## 🛠️ Usage

The server exposes tools that can be called via MCP protocol. Each tool is designed to handle specific Discord API operations with proper error handling and validation.

### Example Tools

#### Message Operations
- `DISCORDBOT_CREATE_MESSAGE`: Send messages with embeds, stickers, components
- `DISCORDBOT_GET_MESSAGE`: Retrieve specific messages
- `DISCORDBOT_UPDATE_MESSAGE`: Edit existing messages
- `DISCORDBOT_DELETE_MESSAGE`: Delete messages
- `DISCORDBOT_LIST_MESSAGES`: Get message history with pagination

#### Reaction Management
- `DISCORDBOT_ADD_MY_MESSAGE_REACTION`: Add reactions
- `DISCORDBOT_DELETE_MY_MESSAGE_REACTION`: Remove own reactions
- `DISCORDBOT_DELETE_USER_MESSAGE_REACTION`: Remove user reactions
- `DISCORDBOT_DELETE_ALL_MESSAGE_REACTIONS`: Clear all reactions
- `DISCORDBOT_LIST_MESSAGE_REACTIONS_BY_EMOJI`: List reaction users

#### Guild Management
- `DISCORDBOT_CREATE_GUILD`: Create new guilds
- `DISCORDBOT_GET_GUILD`: Get guild information
- `DISCORDBOT_UPDATE_GUILD`: Modify guild settings
- `DISCORDBOT_DELETE_GUILD`: Delete guilds

#### Member Operations
- `DISCORDBOT_ADD_GUILD_MEMBER`: Add members to guilds
- `DISCORDBOT_GET_GUILD_MEMBER`: Get member information
- `DISCORDBOT_UPDATE_GUILD_MEMBER`: Modify member attributes
- `DISCORDBOT_LIST_GUILD_MEMBERS`: List guild members

#### Thread Operations
- `DISCORDBOT_CREATE_THREAD`: Create new threads
- `DISCORDBOT_CREATE_THREAD_FROM_MESSAGE`: Create threads from messages
- `DISCORDBOT_JOIN_THREAD`: Join threads
- `DISCORDBOT_LEAVE_THREAD`: Leave threads
- `DISCORDBOT_LIST_THREAD_MEMBERS`: List thread members

## ⚙️ Configuration

The server uses the following configuration:

- `DISCORD_API_BASE`: Discord API base URL (default: https://discord.com/api/v10)
- `DISCORD_BOT_TOKEN`: Your Discord bot token (required)

## 🛡️ Error Handling

The server includes comprehensive error handling for:
- **Parameter Validation**: ID format validation, content length limits
- **Discord API Errors**: 401, 403, 404, 429 status codes
- **Network Issues**: Timeouts and connection errors
- **Rate Limiting**: Automatic retry suggestions
- **Permission Issues**: Clear error messages

## 🔍 Validation Features

- **ID Validation**: Channel, message, user, guild, and role IDs
- **Content Limits**: Message content (2000 chars), embeds (10 max), stickers (3 max)
- **Pagination**: Proper limit validation (1-1000 for most endpoints)
- **Emoji Encoding**: Automatic URL encoding for emoji reactions
- **Audit Logging**: Support for reason headers in destructive operations

## 📋 Requirements

- Python 3.11+
- httpx>=0.25.0
- fastmcp>=2.12.4
- mcp[cli]>=1.16.0

## 🎯 Reference

This implementation is based on the [Composio Discord Toolkit](https://docs.composio.dev/toolkits/discordbot#tool-list) and provides comprehensive coverage of Discord's REST API endpoints.

## 📄 License

This project is licensed under the MIT License.

## 🔄 Version History

- **v2.0.0**: Complete rewrite with 190 tools based on Composio toolkit
- **v1.0.0**: Initial implementation with 19 basic tools

## 🚀 Quick Start

1. **Create Discord Bot**:
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create new application and bot
   - Copy the bot token

2. **Set Environment Variable**:
   ```bash
   export DISCORD_BOT_TOKEN="your_bot_token_here"
   ```

3. **Install and Run**:
   ```bash
   pip install httpx fastmcp mcp[cli]
   python discordbot.py
   ```

4. **Invite Bot to Server**:
   - Use OAuth2 URL Generator in Discord Developer Portal
   - Select "bot" scope and required permissions
   - Use generated URL to invite bot to your server

## 🔧 Advanced Features

- **Comprehensive Validation**: All parameters are validated before API calls
- **Error Recovery**: Detailed error messages with suggested fixes
- **Rate Limit Handling**: Built-in rate limit detection and guidance
- **Audit Logging**: Support for audit log reasons in destructive operations
- **Type Safety**: Full type hints for better IDE support and error detection