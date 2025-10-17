import os
import json
import asyncio
import time
from typing import Optional, List, Dict, Any, Union, IO, BinaryIO
from urllib.parse import quote_plus, urlencode
from dataclasses import dataclass
from datetime import datetime, timedelta
import httpx

# FastMCP import compatibility
try:
    from mcp.server.fastmcp import FastMCP  
except Exception:
    try:
        from mcp.server.fastmcp import FastMCP  
    except Exception:
        raise ImportError("FastMCP import failed. Ensure 'mcp' package is installed.")

# ---------------- PRODUCTION CONFIGURATION ----------------
@dataclass
class ProductionConfig:
    """Production configuration settings."""
    # API Configuration
    DISCORD_API_BASE: str = "https://discord.com/api/v10"
    REQUEST_TIMEOUT: float = 30.0
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.0
    CONNECTION_POOL_SIZE: int = 100
    MAX_KEEPALIVE_CONNECTIONS: int = 20
    
    # Rate Limiting
    RATE_LIMIT_WINDOW: int = 60  # seconds
    MAX_REQUESTS_PER_WINDOW: int = 50
    
    # Health Check
    HEALTH_CHECK_INTERVAL: int = 30  # seconds
    
    # File Upload
    MAX_FILE_SIZE: int = 25 * 1024 * 1024  # 25MB (Discord limit)
    ALLOWED_FILE_TYPES: List[str] = None
    
    def __post_init__(self):
        if self.ALLOWED_FILE_TYPES is None:
            self.ALLOWED_FILE_TYPES = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mov']

# Load configuration
config = ProductionConfig()

# Environment variable overrides
config.DISCORD_API_BASE = os.getenv("DISCORD_API_BASE", config.DISCORD_API_BASE)
config.REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", config.REQUEST_TIMEOUT))

# Bot token validation
DISCORD_BOT_TOKEN = "MTQyNTEzMTI2MjkxNzQ4MDU5Nw.GZy3qk.iyJC4kdkA2ywNARsB8SY8sIB2IPFZ6Q2a6U0WI"
if not DISCORD_BOT_TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN environment variable must be set. Include leading 'Bot ' if required.")

if not DISCORD_BOT_TOKEN.startswith("Bot "):
    DISCORD_BOT_TOKEN = f"Bot {DISCORD_BOT_TOKEN}"

DEFAULT_HEADERS = {"Authorization": DISCORD_BOT_TOKEN, "Content-Type": "application/json"}

# ---------------- PRODUCTION HTTP CLIENT ----------------
class ProductionHTTPClient:
    """Production-ready HTTP client with connection pooling and retry logic."""
    
    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
    
    async def __aenter__(self):
        await self._ensure_client()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def _ensure_client(self):
        """Ensure HTTP client is initialized."""
        if self.client is None:
            async with self._lock:
                if self.client is None:
                    limits = httpx.Limits(
                        max_keepalive_connections=config.MAX_KEEPALIVE_CONNECTIONS,
                        max_connections=config.CONNECTION_POOL_SIZE
                    )
                    
                    timeout = httpx.Timeout(
                        connect=10.0,
                        read=config.REQUEST_TIMEOUT,
                        write=10.0,
                        pool=5.0
                    )
                    
                    self.client = httpx.AsyncClient(
                        limits=limits,
                        timeout=timeout,
                        headers=DEFAULT_HEADERS,
                        follow_redirects=True
                    )
    
    async def request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with retry logic."""
        await self._ensure_client()
        
        last_exception = None
        for attempt in range(config.MAX_RETRIES + 1):
            try:
                response = await self.client.request(method, url, **kwargs)
                return response
                
            except Exception as e:
                last_exception = e
                
                if attempt < config.MAX_RETRIES:
                    delay = config.RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    await asyncio.sleep(delay)
        
        raise last_exception
    
    async def close(self):
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

# Global HTTP client instance
http_client = ProductionHTTPClient()

# ---------------- PRODUCTION MCP ----------------
mcp = FastMCP("discordbot-mcp-production")

# ---------------- HELPERS ----------------
def _safe_str(s: Optional[str]) -> Optional[str]:
    """Safely convert to string and strip whitespace."""
    if s is None:
        return None
    return str(s).strip()

def _safe_list(v: Optional[Union[List[Any], Any]]) -> List[Any]:
    """Safely convert to list."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]

def _safe_dict(v: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Safely convert to dict."""
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    return {"value": v}

def _filter_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Remove None values from dict, but keep False values."""
    return {k: v for k, v in d.items() if v is not None}

def _encode_emoji(emoji: Optional[str]) -> Optional[str]:
    """Encode emoji for URL use."""
    if not emoji:
        return None
    if ":" in emoji and emoji.count(":") == 1 and emoji.split(":")[1].isdigit():
        return emoji
    return quote_plus(emoji)

def _validate_snowflake(snowflake: str, name: str = "ID") -> str:
    """Validate Discord snowflake ID."""
    if not snowflake or not snowflake.strip():
        raise ValueError(f"{name} cannot be empty")
    if not snowflake.strip().isdigit():
        raise ValueError(f"{name} must be a valid Discord snowflake ID")
    return snowflake.strip()

def _validate_channel_id(channel_id: str) -> str:
    """Validate channel ID."""
    return _validate_snowflake(channel_id, "Channel ID")

def _validate_guild_id(guild_id: str) -> str:
    """Validate guild ID."""
    return _validate_snowflake(guild_id, "Guild ID")

def _validate_user_id(user_id: str) -> str:
    """Validate user ID."""
    return _validate_snowflake(user_id, "User ID")

def _validate_message_id(message_id: str) -> str:
    """Validate message ID."""
    return _validate_snowflake(message_id, "Message ID")

def _handle_discord_error(error: Exception, context: str = "", **kwargs) -> Dict[str, Any]:
    """Standardized error handling for Discord API errors."""
    error_str = str(error)
    
    # Common Discord error patterns
    if "404" in error_str:
        return {
            "error": "Resource not found",
            "message": f"The requested {context} was not found",
            "suggestion": f"Verify that the {context} exists and is accessible",
            "status": 404,
            **kwargs
        }
    elif "403" in error_str:
        return {
            "error": "Access forbidden",
            "message": f"Insufficient permissions to access {context}",
            "suggestion": f"Check bot permissions for {context}",
            "status": 403,
            **kwargs
        }
    elif "400" in error_str:
        return {
            "error": "Bad request",
            "message": f"Invalid request parameters for {context}",
            "suggestion": f"Verify request parameters for {context}",
            "status": 400,
            **kwargs
        }
    elif "429" in error_str:
        return {
            "error": "Rate limited",
            "message": f"Too many requests for {context}",
            "suggestion": f"Wait before retrying {context}",
            "status": 429,
            **kwargs
        }
    else:
        return {
            "error": "Discord API error",
            "message": f"Unexpected error occurred: {error_str}",
            "suggestion": f"Check Discord API status and retry {context}",
            "status": "unknown",
            **kwargs
        }

async def discord_request(method: str, endpoint: str, params: Optional[Dict[str, Any]] = None,
                          json: Optional[Any] = None, data: Optional[Any] = None,
                          files: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
                          timeout: Optional[float] = None) -> Any:
    """Make a Discord API request with production-ready error handling."""
    request_id = f"req_{int(time.time() * 1000)}"
    
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    url = f"{config.DISCORD_API_BASE}{endpoint}"
    
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    if files:
        req_headers.pop("Content-Type", None)


    try:
        # Use production HTTP client with retry logic
        async with http_client:
            # For DELETE requests without JSON, don't pass json parameter at all
            request_kwargs = {
                "method": method,
                "url": url,
                "headers": req_headers,
                "params": params,
                "data": data,
                "files": files,
                "timeout": timeout or config.REQUEST_TIMEOUT
            }
            
            # Only add json parameter if it's not None
            if json is not None:
                request_kwargs["json"] = json
            
            resp = await http_client.request_with_retry(**request_kwargs)
        
        status = resp.status_code
        

        # Handle successful responses
        if status in (200, 201):
            try:
                result = resp.json()
                return result
            except Exception as e:
                return {"status": status, "text": resp.text, "request_id": request_id}
        
        if status == 204:
            return {"status": 204, "detail": "No content", "request_id": request_id}

        # Handle error responses
        try:
            error_data = resp.json()
            
            # Handle rate limiting
            if status == 429:
                retry_after = error_data.get("retry_after", 1)
                raise RuntimeError(f"Rate limited: retry after {retry_after}s")
            
            raise RuntimeError(f"Discord API Error {status}: {error_data}")
            
        except ValueError:
            raise RuntimeError(f"Discord API Error {status}: {resp.text}")

    except Exception as e:
        raise

async def _handle_file_upload(files: Optional[List[Union[str, BinaryIO]]],
                              payload: Dict[str, Any]) -> Dict[str, Any]:
    """Handle multipart file uploads safely with production validation."""
    if not files:
        return payload

    multipart = {}
    opened_files = []
    total_size = 0

    try:
        for i, file_obj in enumerate(files):
            key = f"file[{i}]"
            
            if isinstance(file_obj, str):
                # File path validation
                if not os.path.exists(file_obj):
                    raise FileNotFoundError(f"File not found: {file_obj}")
                
                # Check file size
                file_size = os.path.getsize(file_obj)
                if file_size > config.MAX_FILE_SIZE:
                    raise ValueError(f"File {file_obj} exceeds maximum size limit of {config.MAX_FILE_SIZE} bytes")
                
                # Check file extension
                file_ext = os.path.splitext(file_obj)[1].lower()
                if file_ext not in config.ALLOWED_FILE_TYPES:
                    pass  # Skip unsupported file types
                total_size += file_size
                if total_size > config.MAX_FILE_SIZE:
                    raise ValueError(f"Total file size exceeds limit of {config.MAX_FILE_SIZE} bytes")
                
                fh = open(file_obj, "rb")
                opened_files.append(fh)
                multipart[key] = (os.path.basename(file_obj), fh)
                
            else:
                # File-like object
                name = getattr(file_obj, "name", f"upload_{i}")
                
                # Try to get size if possible
                if hasattr(file_obj, 'seek') and hasattr(file_obj, 'tell'):
                    try:
                        current_pos = file_obj.tell()
                        file_obj.seek(0, 2)  # Seek to end
                        file_size = file_obj.tell()
                        file_obj.seek(current_pos)  # Restore position
                        
                        if file_size > config.MAX_FILE_SIZE:
                            raise ValueError(f"File {name} exceeds maximum size limit of {config.MAX_FILE_SIZE} bytes")
                        
                        total_size += file_size
                        if total_size > config.MAX_FILE_SIZE:
                            raise ValueError(f"Total file size exceeds limit of {config.MAX_FILE_SIZE} bytes")
                    except (OSError, IOError):
                        pass  # Could not determine file size
                multipart[key] = (name, file_obj)

        # Convert payload to JSON string for multipart
        if payload:
            multipart["payload_json"] = (None, json.dumps(payload))

        return multipart
        
    except Exception as e:
        # Clean up opened files
        for fh in opened_files:
            try:
                fh.close()
            except:
                pass
        raise e

# ---------------- APPLICATION & COMMAND MANAGEMENT (20 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_APPLICATION_COMMAND(application_id: str, name: str, description: str,
                                                type: int = 1, options: str = "",
                                                default_member_permissions: str = "", dm_permission: bool = True,
                                                nsfw: bool = False) -> Any:
    """Create a new global application command for Discord slash commands.
    
    This tool creates a global slash command that will be available across all servers where your bot is present.
    Global commands can take up to 1 hour to propagate across Discord.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - name (str): The command name (required) - must be lowercase, 1-32 characters, letters/numbers/underscores only
    - description (str): The command description shown to users (required) - max 100 characters
    - type (int): The command type (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT (slash command)
        * 2 = USER (user context menu)
        * 3 = MESSAGE (message context menu)
    - options (str): JSON string of command options/parameters (optional)
    - default_member_permissions (str): JSON string of default member permissions required (optional)
    - dm_permission (bool): Whether the command can be used in DMs (default: true)
    - nsfw (bool): Whether the command is NSFW and only works in NSFW channels (default: false)
    
    Returns:
    - dict: Application command object on success containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type
        * options: Command options array
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
    - dict: Error information if failed
    
    Example:
    ```python
    # Create a simple ping command
    result = await DISCORDBOT_CREATE_APPLICATION_COMMAND(
        application_id="123456789012345678",
        name="ping",
        description="Pong! Check bot latency"
    )
    
    # Create a command with options
    options = '[{"name": "user", "description": "User to greet", "type": 6, "required": true}]'
    result = await DISCORDBOT_CREATE_APPLICATION_COMMAND(
        application_id="123456789012345678",
        name="greet",
        description="Greet a user",
        options=options
    )
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    
    # Validate command name
    if not name or not isinstance(name, str):
        raise ValueError("Command name is required and must be a non-empty string")
    
    # Discord command name validation: lowercase, 1-32 chars, letters/numbers/underscores only
    import re
    if not re.match(r'^[a-z0-9_]{1,32}$', name.lower()):
        raise ValueError("Command name must be 1-32 characters, lowercase letters, numbers, and underscores only")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": name.lower(),  # Ensure lowercase
        "description": _safe_str(description),
        "type": type,
        "options": parse_json_param(options, "options"),
        "default_member_permissions": default_member_permissions if default_member_permissions else None,
        "dm_permission": dm_permission,
        "nsfw": nsfw
    })
    return await discord_request("POST", f"/applications/{application_id}/commands", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_APPLICATION_COMMAND(application_id: str, command_id: str) -> Any:
    """Delete a global application command permanently.
    
    This tool removes a global slash command from your Discord application. Once deleted, the command
    will no longer be available to users and cannot be recovered.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - command_id (str): The unique identifier of the command to delete (required)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Delete a command by its ID
    result = await DISCORDBOT_DELETE_APPLICATION_COMMAND(
        application_id="123456789012345678",
        command_id="987654321098765432"
    )
    
    # Check if deletion was successful
    if result.get("status") == 204:
        print("Command deleted successfully")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("DELETE", f"/applications/{application_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_APPLICATION_COMMAND(application_id: str, command_id: str, name: str = "",
                                                description: str = "", type: int = 1,
                                                options: str = "",
                                                default_member_permissions: str = "",
                                                dm_permission: bool = True, nsfw: bool = False) -> Any:
    """Update an existing global application command.
    
    This tool modifies an existing global slash command. You can update any aspect of the command
    including its name, description, options, and permissions. Only provide fields you want to change.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - command_id (str): The unique identifier of the command to update (required)
    - name (str): New name for the command (optional) - must be lowercase, 1-32 characters
    - description (str): New description for the command (optional) - max 100 characters
    - type (int): New type of command (optional, default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT (slash command)
        * 2 = USER (user context menu)
        * 3 = MESSAGE (message context menu)
    - options (str): JSON string of new command options/parameters (optional)
    - default_member_permissions (str): JSON string of new permission requirements (optional)
    - dm_permission (bool): Whether the command can be used in DMs (optional)
    - nsfw (bool): Whether the command is NSFW and only works in NSFW channels (optional)
    
    Returns:
    - dict: Updated application command object on success containing:
        * id: Command ID
        * name: Updated command name
        * description: Updated command description
        * type: Updated command type
        * options: Updated command options array
        * default_member_permissions: Updated permission requirements
        * dm_permission: Updated DM usage permission
        * nsfw: Updated NSFW flag
        * version: Updated command version
    - dict: Error information if failed
    
    Example:
    ```python
    # Update only the description
    result = await DISCORDBOT_UPDATE_APPLICATION_COMMAND(
        application_id="123456789012345678",
        command_id="987654321098765432",
        description="Updated description for the command"
    )
    
    # Update multiple fields
    options = '[{"name": "amount", "description": "Number of items", "type": 4, "required": true}]'
    result = await DISCORDBOT_UPDATE_APPLICATION_COMMAND(
        application_id="123456789012345678",
        command_id="987654321098765432",
        name="give_items",
        description="Give items to a user",
        options=options,
        dm_permission=False
    )
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    command_id = _validate_snowflake(command_id, "Command ID")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "description": _safe_str(description) if description else None,
        "type": type,
        "options": parse_json_param(options, "options"),
        "default_member_permissions": default_member_permissions if default_member_permissions else None,
        "dm_permission": dm_permission,
        "nsfw": nsfw
    })
    return await discord_request("PATCH", f"/applications/{application_id}/commands/{command_id}", json=payload)

@mcp.tool()
async def DISCORDBOT_LIST_APPLICATION_COMMANDS(application_id: str, with_localizations: Optional[bool] = None) -> Any:
    """Fetch all global commands for an application.
    
    This tool retrieves a list of all global slash commands registered for your Discord application.
    Useful for managing commands, checking what's already registered, or syncing command states.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - with_localizations (bool): Whether to include localization data in the response (optional)
        * True: Include localized names and descriptions
        * False/None: Return only default language data
    
    Returns:
    - list: Array of application command objects, each containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type (1=CHAT_INPUT, 2=USER, 3=MESSAGE)
        * options: Command options array
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
        * name_localizations: Localized names (if with_localizations=True)
        * description_localizations: Localized descriptions (if with_localizations=True)
    - dict: Error information if failed
    
    Example:
    ```python
    # Get all commands without localizations
    commands = await DISCORDBOT_LIST_APPLICATION_COMMANDS(
        application_id="123456789012345678"
    )
    print(f"Found {len(commands)} commands")
    
    # Get commands with localization data
    commands_with_locales = await DISCORDBOT_LIST_APPLICATION_COMMANDS(
        application_id="123456789012345678",
        with_localizations=True
    )
    
    # List command names
    for cmd in commands:
        print(f"- {cmd['name']}: {cmd['description']}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    params = _filter_none({
        "with_localizations": with_localizations
    })
    return await discord_request("GET", f"/applications/{application_id}/commands", params=params)

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION_COMMAND(application_id: str, command_id: str) -> Any:
    """Fetch a specific global application command by its ID.
    
    This tool retrieves detailed information about a single global slash command.
    Useful for checking command details, validating command existence, or getting command metadata.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - command_id (str): The unique identifier of the command to fetch (required)
    
    Returns:
    - dict: Application command object on success containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type (1=CHAT_INPUT, 2=USER, 3=MESSAGE)
        * options: Command options array with detailed option information
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
        * application_id: Application ID that owns this command
    - dict: Error information if failed (404 if command not found)
    
    Example:
    ```python
    # Get a specific command
    command = await DISCORDBOT_GET_APPLICATION_COMMAND(
        application_id="123456789012345678",
        command_id="987654321098765432"
    )
    
    if "error" not in command:
        print(f"Command: {command['name']}")
        print(f"Description: {command['description']}")
        print(f"Options: {len(command.get('options', []))}")
    else:
        print(f"Error: {command['error']}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("GET", f"/applications/{application_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_APPLICATION_COMMAND(application_id: str, guild_id: str, name: str, description: str,
                                                      type: int = 1, options: str = "",
                                                      default_member_permissions: str = "", dm_permission: bool = True,
                                                      nsfw: bool = False) -> Any:
    """Create a new guild-specific application command.
    
    This tool creates a slash command that is only available in a specific Discord server (guild).
    Guild commands are instantly available and don't have the 1-hour propagation delay of global commands.
    Perfect for server-specific features, testing, or commands that shouldn't be global.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server where the command will be created (required)
    - name (str): The command name (required) - must be lowercase, 1-32 characters, letters/numbers/underscores only
    - description (str): The command description shown to users (required) - max 100 characters
    - type (int): The command type (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT (slash command)
        * 2 = USER (user context menu)
        * 3 = MESSAGE (message context menu)
    - options (str): JSON string of command options/parameters (optional)
    - default_member_permissions (str): JSON string of default member permissions required (optional)
    - dm_permission (bool): Whether the command can be used in DMs (default: true)
    - nsfw (bool): Whether the command is NSFW and only works in NSFW channels (default: false)
    
    Returns:
    - dict: Guild application command object on success containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type
        * options: Command options array
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
        * guild_id: Guild ID where this command is available
    - dict: Error information if failed
    
    Example:
    ```python
    # Create a server-specific moderation command
    result = await DISCORDBOT_CREATE_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        name="ban_user",
        description="Ban a user from this server"
    )
    
    # Create a command with options for a specific guild
    options = '[{"name": "reason", "description": "Reason for ban", "type": 3, "required": false}]'
    result = await DISCORDBOT_CREATE_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        name="warn",
        description="Warn a user",
        options=options,
        dm_permission=False
    )
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    
    # Validate command name
    if not name or not isinstance(name, str):
        raise ValueError("Command name is required and must be a non-empty string")
    
    # Discord command name validation: lowercase, 1-32 chars, letters/numbers/underscores only
    import re
    if not re.match(r'^[a-z0-9_]{1,32}$', name.lower()):
        raise ValueError("Command name must be 1-32 characters, lowercase letters, numbers, and underscores only")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": name.lower(),  # Ensure lowercase
        "description": _safe_str(description),
        "type": type,
        "options": parse_json_param(options, "options"),
        "default_member_permissions": default_member_permissions if default_member_permissions else None,
        "dm_permission": dm_permission,
        "nsfw": nsfw
    })
    return await discord_request("POST", f"/applications/{application_id}/guilds/{guild_id}/commands", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_APPLICATION_COMMAND(application_id: str, guild_id: str, command_id: str) -> Any:
    """Delete a guild-specific application command permanently.
    
    This tool removes a guild-specific slash command from your Discord application.
    Once deleted, the command will no longer be available in that specific server.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server where the command exists (required)
    - command_id (str): The unique identifier of the command to delete (required)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Delete a guild-specific command
    result = await DISCORDBOT_DELETE_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        command_id="987654321098765432"
    )
    
    # Check if deletion was successful
    if result.get("status") == 204:
        print("Guild command deleted successfully")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("DELETE", f"/applications/{application_id}/guilds/{guild_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_APPLICATION_COMMAND(application_id: str, guild_id: str, command_id: str,
                                                      name: str = "", description: str = "",
                                                      type: int = 1, options: str = "",
                                                      default_member_permissions: str = "",
                                                      dm_permission: bool = True, nsfw: bool = False) -> Any:
    """Update an existing guild-specific application command.
    
    This tool modifies an existing guild-specific slash command. You can update any aspect of the command
    including its name, description, options, and permissions. Only provide fields you want to change.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server where the command is located (required)
    - command_id (str): The unique identifier of the command to update (required)
    - name (str): New name for the command (optional) - must be lowercase, 1-32 characters
    - description (str): New description for the command (optional) - max 100 characters
    - type (int): New type of command (optional, default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT (slash command)
        * 2 = USER (user context menu)
        * 3 = MESSAGE (message context menu)
    - options (str): JSON string of new command options/parameters (optional)
    - default_member_permissions (str): JSON string of new permission requirements (optional)
    - dm_permission (bool): Whether the command can be used in DMs (optional)
    - nsfw (bool): Whether the command is NSFW and only works in NSFW channels (optional)
    
    Returns:
    - dict: Updated guild application command object on success containing:
        * id: Command ID
        * name: Updated command name
        * description: Updated command description
        * type: Updated command type
        * options: Updated command options array
        * default_member_permissions: Updated permission requirements
        * dm_permission: Updated DM usage permission
        * nsfw: Updated NSFW flag
        * version: Updated command version
        * guild_id: Guild ID where this command is available
    - dict: Error information if failed
    
    Example:
    ```python
    # Update only the description of a guild command
    result = await DISCORDBOT_UPDATE_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        command_id="987654321098765432",
        description="Updated description for guild-specific command"
    )
    
    # Update multiple fields for a guild command
    options = '[{"name": "duration", "description": "Timeout duration", "type": 4, "required": true}]'
    result = await DISCORDBOT_UPDATE_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        command_id="987654321098765432",
        name="timeout_user",
        description="Timeout a user for specified duration",
        options=options,
        dm_permission=False
    )
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    command_id = _validate_snowflake(command_id, "Command ID")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "description": _safe_str(description) if description else None,
        "type": type,
        "options": parse_json_param(options, "options"),
        "default_member_permissions": default_member_permissions if default_member_permissions else None,
        "dm_permission": dm_permission,
        "nsfw": nsfw
    })
    return await discord_request("PATCH", f"/applications/{application_id}/guilds/{guild_id}/commands/{command_id}", json=payload)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_APPLICATION_COMMAND(application_id: str, guild_id: str, command_id: str) -> Any:
    """Fetch a specific guild application command by its ID.
    
    This tool retrieves detailed information about a single guild-specific slash command.
    Useful for checking command details, validating command existence in a specific server, or getting command metadata.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server where the command exists (required)
    - command_id (str): The unique identifier of the command to fetch (required)
    
    Returns:
    - dict: Guild application command object on success containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type (1=CHAT_INPUT, 2=USER, 3=MESSAGE)
        * options: Command options array with detailed option information
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
        * application_id: Application ID that owns this command
        * guild_id: Guild ID where this command is available
    - dict: Error information if failed (404 if command not found in guild)
    
    Example:
    ```python
    # Get a specific guild command
    command = await DISCORDBOT_GET_GUILD_APPLICATION_COMMAND(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        command_id="987654321098765432"
    )
    
    if "error" not in command:
        print(f"Guild Command: {command['name']}")
        print(f"Description: {command['description']}")
        print(f"Guild ID: {command['guild_id']}")
        print(f"Options: {len(command.get('options', []))}")
    else:
        print(f"Error: {command['error']}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_APPLICATION_COMMANDS(application_id: str, guild_id: str, with_localizations: bool = False) -> Any:
    """Fetch all guild-specific commands for an application.
    
    This tool retrieves a list of all guild-specific slash commands registered for your Discord application
    in a specific server. Useful for managing server-specific commands, checking what's registered, or syncing command states.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server to fetch commands from (required)
    - with_localizations (bool): Whether to include localization data in the response (default: false)
        * True: Include localized names and descriptions
        * False: Return only default language data
    
    Returns:
    - list: Array of guild application command objects, each containing:
        * id: Command ID
        * name: Command name
        * description: Command description
        * type: Command type (1=CHAT_INPUT, 2=USER, 3=MESSAGE)
        * options: Command options array
        * default_member_permissions: Permission requirements
        * dm_permission: DM usage permission
        * nsfw: NSFW flag
        * version: Command version
        * guild_id: Guild ID where these commands are available
        * name_localizations: Localized names (if with_localizations=True)
        * description_localizations: Localized descriptions (if with_localizations=True)
    - dict: Error information if failed
    
    Example:
    ```python
    # Get all guild commands without localizations
    commands = await DISCORDBOT_LIST_GUILD_APPLICATION_COMMANDS(
        application_id="123456789012345678",
        guild_id="876543210987654321"
    )
    print(f"Found {len(commands)} guild commands")
    
    # Get guild commands with localization data
    commands_with_locales = await DISCORDBOT_LIST_GUILD_APPLICATION_COMMANDS(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        with_localizations=True
    )
    
    # List guild command names
    for cmd in commands:
        print(f"- {cmd['name']}: {cmd['description']} (Guild: {cmd['guild_id']})")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "with_localizations": with_localizations if with_localizations else None
    })
    return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands", params=params)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_APPLICATION_COMMAND_PERMISSIONS(application_id: str, guild_id: str, command_id: str) -> Any:
    """Get permissions for a specific command in a guild.
    
    This tool retrieves the permission settings for a guild-specific slash command.
    Useful for checking which roles/users can use a command, or managing command access control.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server where the command exists (required)
    - command_id (str): The unique identifier of the command to get permissions for (required)
    
    Returns:
    - dict: Command permissions object on success containing:
        * id: Command ID
        * application_id: Application ID
        * guild_id: Guild ID
        * permissions: Array of permission objects with:
            * id: Role or user ID
            * type: Permission type (1=role, 2=user)
            * permission: Boolean indicating if permission is granted
    - dict: Error information if failed (404 if command doesn't exist in guild or has no permissions set)
    
    Example:
    ```python
    # Get command permissions
    permissions = await DISCORDBOT_GET_GUILD_APPLICATION_COMMAND_PERMISSIONS(
        application_id="123456789012345678",
        guild_id="876543210987654321",
        command_id="987654321098765432"
    )
    
    if "error" not in permissions:
        print(f"Command {permissions['id']} permissions:")
        for perm in permissions.get('permissions', []):
            perm_type = "Role" if perm['type'] == 1 else "User"
            status = "Allowed" if perm['permission'] else "Denied"
            print(f"  {perm_type} {perm['id']}: {status}")
    else:
        print(f"Error: {permissions['error']}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    command_id = _validate_snowflake(command_id, "Command ID")
    
    try:
        return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands/{command_id}/permissions")
    except Exception as e:
        return _handle_discord_error(e, "command permissions", command_id=command_id, guild_id=guild_id)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_APPLICATION_COMMAND_PERMISSIONS(application_id: str, guild_id: str) -> Any:
    """Get all permissions for all commands in a guild.
    
    This tool retrieves the permission settings for all guild-specific slash commands in a server.
    Useful for managing command access control across multiple commands or auditing permissions.
    
    Parameters:
    - application_id (str): The unique identifier of your Discord application/bot (required)
    - guild_id (str): The unique identifier of the Discord server to get permissions from (required)
    
    Returns:
    - list: Array of command permissions objects, each containing:
        * id: Command ID
        * application_id: Application ID
        * guild_id: Guild ID
        * permissions: Array of permission objects with:
            * id: Role or user ID
            * type: Permission type (1=role, 2=user)
            * permission: Boolean indicating if permission is granted
    - dict: Error information if failed
    
    Example:
    ```python
    # Get all command permissions in a guild
    all_permissions = await DISCORDBOT_LIST_GUILD_APPLICATION_COMMAND_PERMISSIONS(
        application_id="123456789012345678",
        guild_id="876543210987654321"
    )
    
    print(f"Found permissions for {len(all_permissions)} commands")
    
    for cmd_perms in all_permissions:
        print(f"Command {cmd_perms['id']}:")
        for perm in cmd_perms.get('permissions', []):
            perm_type = "Role" if perm['type'] == 1 else "User"
            status = "Allowed" if perm['permission'] else "Denied"
            print(f"  {perm_type} {perm['id']}: {status}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    try:
     return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands/permissions")
    except Exception as e:
        return _handle_discord_error(e, "guild command permissions", guild_id=guild_id)

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION(application_id: str) -> Any:
    """Get information about a Discord application.
    
    This tool retrieves detailed information about a Discord application, including its name,
    description, icon, and other metadata. Useful for getting application details or validating application existence.
    
    Parameters:
    - application_id (str): The unique identifier of the Discord application to fetch (required)
    
    Returns:
    - dict: Application object on success containing:
        * id: Application ID
        * name: Application name
        * icon: Application icon hash
        * description: Application description
        * rpc_origins: Array of RPC origin URLs
        * bot_public: Whether the bot is public
        * bot_require_code_grant: Whether the bot requires OAuth2 code grant
        * terms_of_service_url: Terms of service URL
        * privacy_policy_url: Privacy policy URL
        * owner: Owner information
        * summary: Application summary
        * verify_key: Verification key
        * team: Team information (if applicable)
        * guild_id: Guild ID (if applicable)
        * primary_sku_id: Primary SKU ID
        * slug: Application slug
        * cover_image: Cover image hash
        * flags: Application flags
    - dict: Error information if failed
    
    Example:
    ```python
    # Get application information
    app_info = await DISCORDBOT_GET_APPLICATION(
        application_id="123456789012345678"
    )
    
    if "error" not in app_info:
        print(f"Application: {app_info['name']}")
        print(f"Description: {app_info.get('description', 'No description')}")
        print(f"Public Bot: {app_info.get('bot_public', False)}")
        print(f"Owner: {app_info.get('owner', {}).get('username', 'Unknown')}")
    else:
        print(f"Error: {app_info['error']}")
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    try:
        return await discord_request("GET", f"/applications/{application_id}")
    except Exception as e:
        return _handle_discord_error(e, "application", application_id=application_id)

@mcp.tool()
async def DISCORDBOT_UPDATE_APPLICATION(application_id: str, name: str = "", description: str = "",
                                       icon: str = "", cover_image: str = "",
                                       flags: int = 0, tags: str = "",
                                       install_params: str = "", custom_install_url: str = "",
                                       role_connections_verification_url: str = "") -> Any:
    """Update a Discord application's settings and metadata.
    
    This tool allows you to modify various aspects of your Discord application including name,
    description, icons, and other settings. Only provide fields you want to change.
    
    Parameters:
    - application_id (str): The unique identifier of the Discord application to update (required)
    - name (str): New name for the application (optional)
    - description (str): New description for the application (optional)
    - icon (str): New icon for the application - base64 encoded image data (optional)
    - cover_image (str): New cover image for the application - base64 encoded image data (optional)
    - flags (int): New flags for the application (optional)
    - tags (str): JSON string of tags for the application (optional)
    - install_params (str): JSON string of installation parameters (optional)
    - custom_install_url (str): Custom installation URL (optional)
    - role_connections_verification_url (str): Role connections verification URL (optional)
    
    Returns:
    - dict: Updated application object on success containing:
        * id: Application ID
        * name: Updated application name
        * description: Updated application description
        * icon: Updated application icon hash
        * cover_image: Updated cover image hash
        * flags: Updated application flags
        * tags: Updated application tags
        * install_params: Updated installation parameters
        * custom_install_url: Updated custom install URL
        * role_connections_verification_url: Updated verification URL
        * All other application fields
    - dict: Error information if failed
    
    Example:
    ```python
    # Update application name and description
    result = await DISCORDBOT_UPDATE_APPLICATION(
        application_id="123456789012345678",
        name="My Updated Bot",
        description="A helpful Discord bot for server management"
    )
    
    # Update with tags and custom install URL
    tags = '["moderation", "utility", "fun"]'
    result = await DISCORDBOT_UPDATE_APPLICATION(
        application_id="123456789012345678",
        tags=tags,
        custom_install_url="https://mybot.com/install"
    )
    ```
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "description": _safe_str(description) if description else None,
        "icon": icon if icon else None,
        "cover_image": cover_image if cover_image else None,
        "flags": flags if flags > 0 else None,
        "tags": parse_json_param(tags, "tags"),
        "install_params": parse_json_param(install_params, "install_params"),
        "custom_install_url": _safe_str(custom_install_url) if custom_install_url else None,
        "role_connections_verification_url": _safe_str(role_connections_verification_url) if role_connections_verification_url else None
    })
    try:
        return await discord_request("PUT", f"/applications/{application_id}", json=payload)
    except Exception as e:
        return _handle_discord_error(e, "application update", application_id=application_id)

@mcp.tool()
async def DISCORDBOT_GET_MY_APPLICATION() -> Any:
    """Get information about the current authenticated application.
    
    This tool retrieves detailed information about your own Discord application (the one associated
    with the bot token being used). Useful for getting your application's details, validating settings,
    or checking application metadata.
    
    Returns:
    - dict: Application object on success containing:
        * id: Application ID
        * name: Application name
        * icon: Application icon hash
        * description: Application description
        * rpc_origins: Array of RPC origin URLs
        * bot_public: Whether the bot is public
        * bot_require_code_grant: Whether the bot requires OAuth2 code grant
        * terms_of_service_url: Terms of service URL
        * privacy_policy_url: Privacy policy URL
        * owner: Owner information
        * summary: Application summary
        * verify_key: Verification key
        * team: Team information (if applicable)
        * guild_id: Guild ID (if applicable)
        * primary_sku_id: Primary SKU ID
        * slug: Application slug
        * cover_image: Cover image hash
        * flags: Application flags
    - dict: Error information if failed
    
    Example:
    ```python
    # Get current application information
    my_app = await DISCORDBOT_GET_MY_APPLICATION()
    
    if "error" not in my_app:
        print(f"My Application: {my_app['name']}")
        print(f"Application ID: {my_app['id']}")
        print(f"Description: {my_app.get('description', 'No description')}")
        print(f"Public Bot: {my_app.get('bot_public', False)}")
        print(f"Owner: {my_app.get('owner', {}).get('username', 'Unknown')}")
    else:
        print(f"Error: {my_app['error']}")
    ```
    """
    try:
        return await discord_request("GET", "/applications/@me")
    except Exception as e:
        return _handle_discord_error(e, "my application")

@mcp.tool()
async def DISCORDBOT_UPDATE_MY_APPLICATION(name: str = "", description: str = "",
                                           icon: str = "", cover_image: str = "",
                                           flags: int = 0, tags: str = "",
                                           install_params: str = "", custom_install_url: str = "",
                                           role_connections_verification_url: str = "") -> Any:
    """Update the current application.
    
    Parameters:
    - name: New name for the application
    - description: New description for the application
    - icon: New icon for the application (base64 encoded image data)
    - cover_image: New cover image for the application (base64 encoded image data)
    - flags: New flags for the application
    - tags: JSON string of tags for the application
    - install_params: JSON string of installation parameters
    - custom_install_url: Custom installation URL
    - role_connections_verification_url: Role connections verification URL
    """
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "description": _safe_str(description) if description else None,
        "icon": icon if icon else None,
        "cover_image": cover_image if cover_image else None,
        "flags": flags if flags > 0 else None,
        "tags": parse_json_param(tags, "tags"),
        "install_params": parse_json_param(install_params, "install_params"),
        "custom_install_url": _safe_str(custom_install_url) if custom_install_url else None,
        "role_connections_verification_url": _safe_str(role_connections_verification_url) if role_connections_verification_url else None
    })
    try:
        return await discord_request("PATCH", "/applications/@me", json=payload)
    except Exception as e:
        return _handle_discord_error(e, "my application update")

@mcp.tool()
async def DISCORDBOT_GET_MY_OAUTH2_APPLICATION() -> Any:
    """Get information about the current OAuth2 application."""
    try:
     return await discord_request("GET", "/oauth2/applications/@me")
    except Exception as e:
        return _handle_discord_error(e, "OAuth2 application")

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION_ROLE_CONNECTIONS_METADATA(application_id: str) -> Any:
    """Get role connection metadata records for an application."""
    application_id = _validate_snowflake(application_id, "Application ID")
    try:
     return await discord_request("GET", f"/applications/{application_id}/role-connections/metadata")
    except Exception as e:
        return _handle_discord_error(e, "role connections metadata", application_id=application_id)

@mcp.tool()
async def DISCORDBOT_UPDATE_APPLICATION_USER_ROLE_CONNECTION(application_id: str, platform_name: str = "",
                                                             platform_username: str = "",
                                                             metadata: str = "") -> Any:
    """Update the current user's role connection metadata.
    
    Note: This endpoint requires OAuth2 application authentication, not bot token.
    For bot applications, this endpoint is not accessible with bot tokens.
    
    Parameters:
    - application_id: ID of the application (required)
    - platform_name: Name of the platform
    - platform_username: Username on the platform
    - metadata: JSON string of metadata to store
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "platform_name": _safe_str(platform_name) if platform_name else None,
        "platform_username": _safe_str(platform_username) if platform_username else None,
        "metadata": parse_json_param(metadata, "metadata")
    })
    
    try:
        return await discord_request("PUT", f"/users/@me/applications/{application_id}/role-connection", json=payload)
    except Exception as e:
        return _handle_discord_error(e, "user role connection", application_id=application_id)

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION_USER_ROLE_CONNECTION(application_id: str) -> Any:
    """Get the current user's role connection metadata.
    
    Note: This endpoint requires OAuth2 application authentication, not bot token.
    For bot applications, this endpoint is not accessible with bot tokens.
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    try:
        return await discord_request("GET", f"/users/@me/applications/{application_id}/role-connection")
    except Exception as e:
        if "403" in str(e) or "Bots cannot use this endpoint" in str(e):
            return {
                "error": "This endpoint requires OAuth2 application authentication",
                "message": "The /users/@me/applications/{application_id}/role-connection endpoint is not accessible with bot tokens",
                "suggestion": "Use OAuth2 application credentials instead of bot token for this endpoint",
                "status": 403
            }
        raise

# ---------------- CHANNEL & THREAD MANAGEMENT (26 tools) ----------------
@mcp.tool()
async def DISCORDBOT_GET_CHANNEL(channel_id: str) -> Any:
    """Get detailed information about a Discord channel.
    
    This tool retrieves comprehensive information about a Discord channel including its type,
    name, permissions, and other metadata. Works with all channel types (text, voice, category, etc.).
    
    Parameters:
    - channel_id (str): The unique identifier of the channel to retrieve (required)
    
    Returns:
    - dict: Channel object on success containing:
        * id: Channel ID
        * type: Channel type (0=text, 2=voice, 4=category, 5=announcement, 13=stage, 15=forum)
        * guild_id: Guild ID (if applicable)
        * position: Channel position
        * permission_overwrites: Array of permission overwrites
        * name: Channel name
        * topic: Channel topic (if applicable)
        * nsfw: Whether channel is NSFW
        * last_message_id: ID of last message
        * bitrate: Bitrate for voice channels
        * user_limit: User limit for voice channels
        * rate_limit_per_user: Slowmode delay in seconds
        * recipients: Array of recipients for DM channels
        * icon: Channel icon hash
        * owner_id: Owner ID for DM channels
        * application_id: Application ID for group DM channels
        * parent_id: Parent category ID
        * last_pin_timestamp: Timestamp of last pinned message
        * rtc_region: Voice region
        * video_quality_mode: Video quality mode
        * message_count: Message count (for threads)
        * member_count: Member count (for threads)
        * thread_metadata: Thread metadata (for threads)
        * member: Thread member object (for threads)
        * default_auto_archive_duration: Auto-archive duration
        * permissions: Computed permissions for the bot
        * flags: Channel flags
        * total_message_sent: Total messages sent
        * available_tags: Available tags (for forum channels)
        * applied_tags: Applied tags (for forum channels)
        * default_reaction_emoji: Default reaction emoji
        * default_thread_rate_limit_per_user: Default thread slowmode
        * default_sort_order: Default sort order
        * default_forum_layout: Default forum layout
    - dict: Error information if failed
    
    Example:
    ```python
    # Get channel information
    channel = await DISCORDBOT_GET_CHANNEL(
        channel_id="123456789012345678"
    )
    
    if "error" not in channel:
        print(f"Channel: {channel['name']}")
        print(f"Type: {channel['type']}")
        print(f"Guild ID: {channel.get('guild_id', 'DM Channel')}")
        print(f"NSFW: {channel.get('nsfw', False)}")
        
        if channel['type'] == 0:  # Text channel
            print(f"Topic: {channel.get('topic', 'No topic')}")
            print(f"Slowmode: {channel.get('rate_limit_per_user', 0)} seconds")
        elif channel['type'] == 2:  # Voice channel
            print(f"Bitrate: {channel.get('bitrate', 'Unknown')}")
            print(f"User Limit: {channel.get('user_limit', 'No limit')}")
    else:
        print(f"Error: {channel['error']}")
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_CHANNEL(guild_id: str, name: str, type: int = 0,
                                          topic: str = "", bitrate: int = 0,
                                          user_limit: int = 0, rate_limit_per_user: int = 0,
                                          position: int = 0, permission_overwrites: str = "",
                                          parent_id: str = "", nsfw: bool = False,
                                          rtc_region: str = "", video_quality_mode: int = 0,
                                          default_auto_archive_duration: int = 0,
                                          available_tags: str = "",
                                          default_reaction_emoji: str = "",
                                          default_thread_rate_limit_per_user: int = 0,
                                          default_sort_order: int = 0, reason: str = "") -> Any:
    """Create a new channel in a Discord server.
    
    This tool creates a new channel in a Discord server with customizable settings.
    Supports all channel types including text, voice, category, announcement, stage, and forum channels.
    
    Parameters:
    - guild_id (str): The unique identifier of the Discord server where the channel will be created (required)
    - name (str): Name of the channel (required)
    - type (int): Type of channel (default: 0 = TEXT)
        * 0 = TEXT
        * 2 = VOICE
        * 4 = CATEGORY
        * 5 = ANNOUNCEMENT
        * 13 = STAGE
        * 15 = FORUM
    - topic (str): Topic of the channel (optional)
    - bitrate (int): Bitrate for voice channels (8000-128000, optional)
    - user_limit (int): User limit for voice channels (0 = no limit, optional)
    - rate_limit_per_user (int): Slowmode delay in seconds (optional)
    - position (int): Position of the channel (optional)
    - permission_overwrites (str): JSON string of permission overwrites (optional)
    - parent_id (str): ID of the parent category (optional)
    - nsfw (bool): Whether the channel is NSFW (default: false)
    - rtc_region (str): Voice region for the channel (optional)
    - video_quality_mode (int): Video quality mode for voice channels (optional)
    - default_auto_archive_duration (int): Default auto-archive duration for threads (optional)
    - available_tags (str): JSON string of available tags for forum channels (optional)
    - default_reaction_emoji (str): JSON string of default reaction emoji (optional)
    - default_thread_rate_limit_per_user (int): Default thread slowmode (optional)
    - default_sort_order (int): Default sort order for forum channels (optional)
    - reason (str): Reason for creating the channel (for audit logs, optional)
    
    Returns:
    - dict: Created channel object on success containing all channel properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Create a simple text channel
    channel = await DISCORDBOT_CREATE_GUILD_CHANNEL(
        guild_id="876543210987654321",
        name="general-chat",
        topic="General discussion channel"
    )
    
    # Create a voice channel with specific settings
    voice_channel = await DISCORDBOT_CREATE_GUILD_CHANNEL(
        guild_id="876543210987654321",
        name="Gaming Voice",
        type=2,  # Voice channel
        bitrate=64000,
        user_limit=10,
        reason="Created for gaming sessions"
    )
    
    # Create a category with permission overwrites
    overwrites = '[{"id": "123456789", "type": 1, "allow": "1024", "deny": "0"}]'
    category = await DISCORDBOT_CREATE_GUILD_CHANNEL(
        guild_id="876543210987654321",
        name="Staff Channels",
        type=4,  # Category
        permission_overwrites=overwrites
    )
    ```
    """
    guild_id = _validate_guild_id(guild_id)
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name),
        "type": type if type > 0 else None,
        "topic": _safe_str(topic) if topic else None,
        "bitrate": bitrate if bitrate > 0 else None,
        "user_limit": user_limit if user_limit > 0 else None,
        "rate_limit_per_user": rate_limit_per_user if rate_limit_per_user > 0 else None,
        "position": position if position > 0 else None,
        "permission_overwrites": parse_json_param(permission_overwrites, "permission_overwrites"),
        "parent_id": parent_id if parent_id else None,
        "nsfw": nsfw,
        "rtc_region": _safe_str(rtc_region) if rtc_region else None,
        "video_quality_mode": video_quality_mode if video_quality_mode > 0 else None,
        "default_auto_archive_duration": default_auto_archive_duration if default_auto_archive_duration > 0 else None,
        "available_tags": parse_json_param(available_tags, "available_tags"),
        "default_reaction_emoji": parse_json_param(default_reaction_emoji, "default_reaction_emoji"),
        "default_thread_rate_limit_per_user": default_thread_rate_limit_per_user if default_thread_rate_limit_per_user > 0 else None,
        "default_sort_order": default_sort_order if default_sort_order > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/channels", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_UPDATE_CHANNEL(channel_id: str, name: str = "", type: int = 0,
                                    position: int = 0, topic: str = "",
                                    nsfw: bool = False, rate_limit_per_user: int = 0,
                                    bitrate: int = 0, user_limit: int = 0,
                                    permission_overwrites: str = "",
                                    parent_id: str = "", rtc_region: str = "",
                                    video_quality_mode: int = 0, default_auto_archive_duration: int = 0,
                                    flags: int = 0, available_tags: str = "",
                                    default_reaction_emoji: str = "",
                                    default_thread_rate_limit_per_user: int = 0,
                                    default_sort_order: int = 0, reason: str = "") -> Any:
    """Update a channel's settings and properties.
    
    This tool allows you to modify various aspects of an existing Discord channel including
    its name, topic, permissions, and other settings. Only provide fields you want to change.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel to update (required)
    - name (str): New name for the channel (optional)
    - type (int): New type of channel (optional, default: 0 = TEXT)
        * 0 = TEXT
        * 2 = VOICE
        * 4 = CATEGORY
        * 5 = ANNOUNCEMENT
        * 13 = STAGE
        * 15 = FORUM
    - position (int): New position of the channel (optional)
    - topic (str): New topic of the channel (optional)
    - nsfw (bool): Whether the channel is NSFW (optional)
    - rate_limit_per_user (int): Slowmode delay in seconds (optional)
    - bitrate (int): Bitrate for voice channels (8000-128000, optional)
    - user_limit (int): User limit for voice channels (0 = no limit, optional)
    - permission_overwrites (str): JSON string of permission overwrites (optional)
    - parent_id (str): ID of the parent category (optional)
    - rtc_region (str): Voice region for the channel (optional)
    - video_quality_mode (int): Video quality mode for voice channels (optional)
    - default_auto_archive_duration (int): Default auto-archive duration for threads (optional)
    - flags (int): Channel flags (optional)
    - available_tags (str): JSON string of available tags for forum channels (optional)
    - default_reaction_emoji (str): JSON string of default reaction emoji (optional)
    - default_thread_rate_limit_per_user (int): Default thread slowmode (optional)
    - default_sort_order (int): Default sort order for forum channels (optional)
    - reason (str): Reason for updating the channel (for audit logs, optional)
    
    Returns:
    - dict: Updated channel object on success containing all channel properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Update channel name and topic
    updated = await DISCORDBOT_UPDATE_CHANNEL(
        channel_id="123456789012345678",
        name="updated-general",
        topic="Updated general discussion channel"
    )
    
    # Update voice channel settings
    voice_updated = await DISCORDBOT_UPDATE_CHANNEL(
        channel_id="123456789012345678",
        bitrate=128000,
        user_limit=20,
        reason="Increased capacity for events"
    )
    
    # Move channel to different category
    moved = await DISCORDBOT_UPDATE_CHANNEL(
        channel_id="123456789012345678",
        parent_id="987654321098765432",
        position=5
    )
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "type": type if type > 0 else None,
        "position": position if position > 0 else None,
        "topic": _safe_str(topic) if topic else None,
        "nsfw": nsfw,
        "rate_limit_per_user": rate_limit_per_user if rate_limit_per_user > 0 else None,
        "bitrate": bitrate if bitrate > 0 else None,
        "user_limit": user_limit if user_limit > 0 else None,
        "permission_overwrites": parse_json_param(permission_overwrites, "permission_overwrites"),
        "parent_id": parent_id if parent_id else None,
        "rtc_region": _safe_str(rtc_region) if rtc_region else None,
        "video_quality_mode": video_quality_mode if video_quality_mode > 0 else None,
        "default_auto_archive_duration": default_auto_archive_duration if default_auto_archive_duration > 0 else None,
        "flags": flags if flags > 0 else None,
        "available_tags": parse_json_param(available_tags, "available_tags"),
        "default_reaction_emoji": parse_json_param(default_reaction_emoji, "default_reaction_emoji"),
        "default_thread_rate_limit_per_user": default_thread_rate_limit_per_user if default_thread_rate_limit_per_user > 0 else None,
        "default_sort_order": default_sort_order if default_sort_order > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/channels/{channel_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_CHANNEL(channel_id: str) -> Any:
    """Delete a Discord channel permanently.
    
    This tool permanently deletes a Discord channel. This action cannot be undone.
    The channel and all its messages will be permanently removed.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel to delete (required)
    
    Returns:
    - dict: Deleted channel object on success containing:
        * id: Channel ID
        * name: Channel name
        * type: Channel type
        * All other channel properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Delete a channel
    deleted = await DISCORDBOT_DELETE_CHANNEL(
        channel_id="123456789012345678"
    )
    
    if "error" not in deleted:
        print(f"Successfully deleted channel: {deleted['name']}")
        print(f"Channel ID: {deleted['id']}")
    else:
        print(f"Failed to delete channel: {deleted['error']}")
    ```
    
    Warning: This action is irreversible. Make sure you really want to delete the channel.
    """
    channel_id = _validate_channel_id(channel_id)
    headers = DEFAULT_HEADERS.copy()
    try:
        return await discord_request("DELETE", f"/channels/{channel_id}", headers=headers)
    except Exception as e:
        if "404" in str(e) or "Unknown channel" in str(e):
            return {
                "error": "Channel not found",
                "message": "The channel either doesn't exist or has already been deleted",
                "suggestion": "Check if the channel exists and is not already deleted",
                "status": 404,
                "channel_id": channel_id
            }
        raise

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_CHANNELS(guild_id: str) -> Any:
    """Get a list of all channels in a Discord server.
    
    This tool retrieves all channels in a Discord server including text channels, voice channels,
    categories, announcement channels, stage channels, and forum channels.
    
    Parameters:
    - guild_id (str): The unique identifier of the Discord server to list channels from (required)
    
    Returns:
    - list: Array of channel objects, each containing:
        * id: Channel ID
        * type: Channel type (0=text, 2=voice, 4=category, 5=announcement, 13=stage, 15=forum)
        * guild_id: Guild ID
        * position: Channel position
        * permission_overwrites: Array of permission overwrites
        * name: Channel name
        * topic: Channel topic (if applicable)
        * nsfw: Whether channel is NSFW
        * last_message_id: ID of last message
        * bitrate: Bitrate for voice channels
        * user_limit: User limit for voice channels
        * rate_limit_per_user: Slowmode delay in seconds
        * parent_id: Parent category ID
        * All other channel properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Get all channels in a guild
    channels = await DISCORDBOT_LIST_GUILD_CHANNELS(
        guild_id="876543210987654321"
    )
    
    print(f"Found {len(channels)} channels")
    
    # Categorize channels by type
    text_channels = []
    voice_channels = []
    categories = []
    
    for channel in channels:
        if channel['type'] == 0:  # Text
            text_channels.append(channel)
        elif channel['type'] == 2:  # Voice
            voice_channels.append(channel)
        elif channel['type'] == 4:  # Category
            categories.append(channel)
    
    print(f"Text channels: {len(text_channels)}")
    print(f"Voice channels: {len(voice_channels)}")
    print(f"Categories: {len(categories)}")
    ```
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/channels")

@mcp.tool()
async def DISCORDBOT_CREATE_CHANNEL_INVITE(channel_id: str, max_age: int = 0, max_uses: int = 0,
                                           temporary: bool = False, unique: bool = False,
                                           target_type: int = 0, target_user_id: str = "",
                                           target_application_id: str = "", reason: str = "") -> Any:
    """
    Creates a new invite link for a Discord channel.

    NOTE: Requires the 'Create Instant Invite' permission.

    Args:
        channel_id (str): The ID of the channel to create invite for.
        max_age (int): Duration of invite in seconds (0 = never expires).
        max_uses (int): Number of times invite can be used (0 = unlimited).
        temporary (bool): Whether invite grants temporary membership.
        unique (bool): Whether invite should be unique.
        target_type (int): Type of target for invite (0=none, 1=stream, 2=embedded application).
        target_user_id (str): ID of user whose stream to display.
        target_application_id (str): ID of embedded application to open.
        reason (str): Reason for creating the invite (for audit logs).

    Returns:
        dict: Invite object containing invite details and code.
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "max_age": max_age if max_age > 0 else None,
        "max_uses": max_uses if max_uses > 0 else None,
        "target_type": target_type if target_type > 0 else None,
        "target_user_id": target_user_id if target_user_id else None,
        "target_application_id": target_application_id if target_application_id else None
    })
    
    # Handle boolean parameters separately to avoid filtering out False values
    payload["temporary"] = temporary
    payload["unique"] = unique
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/channels/{channel_id}/invites", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_CHANNEL_INVITES(channel_id: str) -> Any:
    """
    Retrieves a list of all invite links for a Discord channel.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        channel_id (str): The ID of the channel to list invites for.

    Returns:
        dict: List of invite objects containing invite details.
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}/invites")

@mcp.tool()
async def DISCORDBOT_SET_CHANNEL_PERMISSION_OVERWRITE(channel_id: str, overwrite_id: str, allow: str = "",
                                                     deny: str = "", type: int = 0,
                                                     reason: str = "") -> Any:
    """Edit the channel permission overwrites for a user or role in a channel.
    
    Parameters:
    - channel_id: ID of the channel (required)
    - overwrite_id: ID of the user or role to set permissions for (required)
    - allow: Permission bitwise value for allowed permissions (use "0" for none)
    - deny: Permission bitwise value for denied permissions (use "0" for none)
    - type: Type of overwrite (0 = role, 1 = member)
    - reason: Reason for setting permissions (for audit logs)
    
    Note: Use Discord permission constants for allow/deny values.
    Common permissions: 1024 (VIEW_CHANNEL), 2048 (SEND_MESSAGES), 8192 (READ_MESSAGE_HISTORY)
    """
    channel_id = _validate_channel_id(channel_id)
    overwrite_id = _validate_snowflake(overwrite_id, "Overwrite ID")
    
    # Parse permission strings to integers
    allow_value = None
    deny_value = None
    
    if allow and allow != "0":
        try:
            allow_value = int(allow)
        except ValueError:
            raise ValueError(f"Invalid allow permission value: {allow}. Must be a valid permission integer.")
    
    if deny and deny != "0":
        try:
            deny_value = int(deny)
        except ValueError:
            raise ValueError(f"Invalid deny permission value: {deny}. Must be a valid permission integer.")
    
    payload = _filter_none({
        "allow": allow_value,
        "deny": deny_value,
        "type": type if type > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PUT", f"/channels/{channel_id}/permissions/{overwrite_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_CHANNEL_PERMISSION_OVERWRITE(channel_id: str, overwrite_id: str) -> Any:
    """Delete a channel permission overwrite for a user or role in a channel."""
    channel_id = _validate_channel_id(channel_id)
    overwrite_id = _validate_snowflake(overwrite_id, "Overwrite ID")
    headers = DEFAULT_HEADERS.copy()
    try:
        return await discord_request("DELETE", f"/channels/{channel_id}/permissions/{overwrite_id}", headers=headers)
    except Exception as e:
        if "404" in str(e) or "Unknown channel permission overwrite" in str(e):
            return {
                "error": "Channel permission overwrite not found",
                "message": "The overwrite either doesn't exist or has already been deleted",
                "suggestion": "Check if the overwrite exists and is not already deleted",
                "status": 404,
                "overwrite_id": overwrite_id,
                "channel_id": channel_id
            }

@mcp.tool()
async def DISCORDBOT_FOLLOW_CHANNEL(channel_id: str, webhook_channel_id: str) -> Any:
    """
    Follows an Announcement Channel and posts its messages to another channel via a webhook.

    Args:
        channel_id: ID of the Announcement Channel to follow (source channel).
        webhook_channel_id: ID of the channel where messages will be posted (destination channel).
    
    Returns:
        dict containing:
            - data: dict with 'channel_id' (source) and 'webhook_id' (created webhook)
            - successful: bool
            - error: error message if any
    """
    channel_id = _validate_channel_id(channel_id)
    webhook_channel_id = _validate_channel_id(webhook_channel_id)
    payload = {
        "webhook_channel_id": webhook_channel_id
    }
    return await discord_request("POST", f"/channels/{channel_id}/followers", json=payload)

@mcp.tool()
async def DISCORDBOT_TRIGGER_TYPING_INDICATOR(channel_id: str) -> Any:
    """
    Triggers the typing indicator in a specified Discord channel.
    
    Args:
        channel_id: ID of the Discord channel where the typing indicator should appear.
    
    Returns:
        dict containing:
            - data: empty dict (operation returns 204 on success)
            - successful: bool
            - error: error message if any
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("POST", f"/channels/{channel_id}/typing")

@mcp.tool()
async def DISCORDBOT_CREATE_THREAD(channel_id: str, name: str, type: int = 11,
                                   auto_archive_duration: int = 0, invitable: bool = True,
                                   rate_limit_per_user: int = 0, reason: str = "") -> Any:
    """Creates a new thread from an existing message.
    
    Parameters:
    - channel_id: ID of the channel to create thread in (required)
    - name: Name of the thread (required)
    - type: Type of thread (default: 11 = PUBLIC_THREAD)
        * 10 = NEWS_THREAD
        * 11 = PUBLIC_THREAD
        * 12 = PRIVATE_THREAD
    - auto_archive_duration: Duration in minutes to automatically archive the thread (0 = disabled)
    - invitable: Whether non-moderators can add other non-moderators to the thread
    - rate_limit_per_user: Amount of seconds a user has to wait before sending another message
    - reason: Reason for creating the thread (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "type": type,
        "auto_archive_duration": auto_archive_duration if auto_archive_duration > 0 else None,
        "invitable": invitable,
        "rate_limit_per_user": rate_limit_per_user if rate_limit_per_user > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/channels/{channel_id}/threads", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_CREATE_THREAD_FROM_MESSAGE(channel_id: str, message_id: str, name: str,
                                                auto_archive_duration: int = 0,
                                                rate_limit_per_user: int = 0, reason: str = "") -> Any:
    """Creates a new thread from an existing message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to create thread from (required)
    - name: Name of the thread (required)
    - auto_archive_duration: Duration in minutes to automatically archive the thread (0 = disabled)
    - rate_limit_per_user: Amount of seconds a user has to wait before sending another message
    - reason: Reason for creating the thread (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "auto_archive_duration": auto_archive_duration if auto_archive_duration > 0 else None,
        "rate_limit_per_user": rate_limit_per_user if rate_limit_per_user > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/channels/{channel_id}/messages/{message_id}/threads", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_JOIN_THREAD(channel_id: str) -> Any:
    """Adds the current user to a thread.
    
    Parameters:
    - channel_id: ID of the thread to join (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("PUT", f"/channels/{channel_id}/thread-members/@me")

@mcp.tool()
async def DISCORDBOT_LEAVE_THREAD(channel_id: str) -> Any:
    """Removes the current user from a thread.
    
    Parameters:
    - channel_id: ID of the thread to leave (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("DELETE", f"/channels/{channel_id}/thread-members/@me")

@mcp.tool()
async def DISCORDBOT_GET_THREAD_MEMBER(channel_id: str, user_id: str) -> Any:
    """Returns a thread member object for the specified user."""
    channel_id = _validate_channel_id(channel_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("GET", f"/channels/{channel_id}/thread-members/{user_id}")

@mcp.tool()
async def DISCORDBOT_DELETE_THREAD_MEMBER(channel_id: str, user_id: str) -> Any:
    """Removes another member from a thread."""
    channel_id = _validate_channel_id(channel_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("DELETE", f"/channels/{channel_id}/thread-members/{user_id}")

@mcp.tool()
async def DISCORDBOT_LIST_THREAD_MEMBERS(channel_id: str, with_member: bool = False,
                                         after: str = "", limit: int = 0) -> Any:
    """Returns array of thread members objects that are members of the thread.
    
    Parameters:
    - channel_id: ID of the thread (required)
    - with_member: Whether to include the guild member object for each thread member
    - after: Get thread members after this user ID
    - limit: Maximum number of thread members to return (0 = default)
    """
    channel_id = _validate_channel_id(channel_id)
    params = _filter_none({
        "with_member": with_member if with_member else None,
        "after": after if after else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/thread-members", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_PUBLIC_ARCHIVED_THREADS(channel_id: str, before: str = "",
                                                  limit: int = 0) -> Any:
    """Returns archived threads in the channel that are public.
    
    Parameters:
    - channel_id: ID of the channel (required)
    - before: Get threads before this thread ID
    - limit: Maximum number of threads to return (0 = default)
    """
    channel_id = _validate_channel_id(channel_id)
    params = _filter_none({
        "before": before if before else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/threads/archived/public", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_PRIVATE_ARCHIVED_THREADS(channel_id: str, before: str = "",
                                                   limit: int = 0) -> Any:
    """Returns archived threads in the channel that are of type GUILD_PRIVATE_THREAD.
    
    Parameters:
    - channel_id: ID of the channel (required)
    - before: Get threads before this thread ID
    - limit: Maximum number of threads to return (0 = default)
    """
    channel_id = _validate_channel_id(channel_id)
    params = _filter_none({
        "before": before if before else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/threads/archived/private", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_MY_PRIVATE_ARCHIVED_THREADS(channel_id: str, before: str = "",
                                                      limit: int = 0) -> Any:
    """Returns archived threads in the channel that are of type GUILD_PRIVATE_THREAD.
    
    Parameters:
    - channel_id: ID of the channel (required)
    - before: Get threads before this thread ID
    - limit: Maximum number of threads to return (0 = default)
    """
    channel_id = _validate_channel_id(channel_id)
    params = _filter_none({
        "before": before if before else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/users/@me/threads/archived/private", params=params)

@mcp.tool()
async def DISCORDBOT_GET_ACTIVE_GUILD_THREADS(guild_id: str) -> Any:
    """Returns all active threads in the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/threads/active")

@mcp.tool()
async def DISCORDBOT_CREATE_STAGE_INSTANCE(channel_id: str, topic: str, privacy_level: int = 1,
                                           send_start_notification: bool = False) -> Any:
    """Create a new stage instance associated with a stage channel.
    
    Parameters:
    - channel_id: ID of the stage channel (required)
    - topic: Topic of the stage instance (required)
    - privacy_level: Privacy level of the stage instance (default: 1 = GUILD_ONLY)
        * 1 = GUILD_ONLY
        * 2 = PUBLIC
    - send_start_notification: Whether to notify @everyone about the stage instance
    - reason: Reason for creating the stage instance (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "channel_id": channel_id,
        "topic": _safe_str(topic),
        "privacy_level": privacy_level,
        "send_start_notification": send_start_notification
    })
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("POST", f"/stage-instances", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_STAGE_INSTANCE(channel_id: str) -> Any:
    """Gets the stage instance associated with a stage channel."""
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/stage-instances/{channel_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_STAGE_INSTANCE(channel_id: str, topic: str = "",
                                           privacy_level: int = 0) -> Any:
    """Updates fields of an existing stage instance.
    
    Parameters:
    - channel_id: ID of the stage channel (required)
    - topic: New topic of the stage instance
    - privacy_level: New privacy level of the stage instance (0 = no change)
        * 1 = GUILD_ONLY
        * 2 = PUBLIC
    - reason: Reason for updating the stage instance (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "topic": _safe_str(topic) if topic else None,
        "privacy_level": privacy_level if privacy_level > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("PATCH", f"/stage-instances/{channel_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_STAGE_INSTANCE(channel_id: str, reason: str = "") -> Any:
    """Delete the stage instance.
    
    Parameters:
    - channel_id: ID of the stage channel (required)
    - reason: Reason for deleting the stage instance (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/stage-instances/{channel_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_UPDATE_SELF_VOICE_STATE(guild_id: str, channel_id: str = "",
                                             suppress: bool = False, request_to_speak_timestamp: str = "") -> Any:
    """Updates the current user's voice state.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - channel_id: ID of the voice channel to join (empty string = leave current channel)
    - suppress: Whether to suppress the user's voice (default: false)
    - request_to_speak_timestamp: ISO8601 timestamp to request to speak (empty string = no request)
    
    Note: The bot must be connected to a voice channel to update its voice state.
    """
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "channel_id": channel_id if channel_id else None,
        "suppress": suppress if suppress else None,
        "request_to_speak_timestamp": request_to_speak_timestamp if request_to_speak_timestamp else None
    })
    headers = DEFAULT_HEADERS.copy()
    
    try:
        return await discord_request("PATCH", f"/guilds/{guild_id}/voice-states/@me", json=payload, headers=headers)
    except Exception as e:
        if "404" in str(e) and "Unknown Voice State" in str(e):
            return {
                "error": "Bot not in voice channel",
                "message": "The bot must be connected to a voice channel to update its voice state",
                "code": 10065,
                "suggestion": "Use DISCORDBOT_UPDATE_VOICE_STATE to move the bot to a voice channel first"
            }
        raise

@mcp.tool()
async def DISCORDBOT_UPDATE_VOICE_STATE(guild_id: str, user_id: str, channel_id: str = "",
                                         suppress: bool = False, request_to_speak_timestamp: str = "", reason: str = "") -> Any:
    """Updates another user's voice state.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user to update (required)
    - channel_id: ID of the voice channel to move user to (empty string = leave current channel)
    - suppress: Whether to suppress the user's voice (default: false)
    - request_to_speak_timestamp: ISO8601 timestamp to request to speak (empty string = no request)
    - reason: Reason for updating the voice state (for audit logs)
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    payload = _filter_none({
        "channel_id": channel_id if channel_id else None,
        "suppress": suppress if suppress else None,
        "request_to_speak_timestamp": request_to_speak_timestamp if request_to_speak_timestamp else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    
    try:
        return await discord_request("PATCH", f"/guilds/{guild_id}/voice-states/{user_id}", json=payload, headers=headers)
    except Exception as e:
        if "404" in str(e) and "Unknown Voice State" in str(e):
            return {
                "error": "User not in voice channel",
                "message": "The user must be connected to a voice channel to update their voice state",
                "code": 10065,
                "suggestion": "The user needs to join a voice channel first"
            }
        raise

# ---------------- GATEWAY & CONNECTION (3 tools) ----------------
@mcp.tool()
async def DISCORDBOT_GET_GATEWAY() -> Any:
    """Get the Discord gateway URL and recommended shard count.
    
    This tool retrieves the WebSocket gateway URL and recommended number of shards
    for connecting to Discord's gateway. Essential for bot development and gateway connections.
    
    Returns:
    - dict: Gateway information containing:
        * url: WebSocket gateway URL
        * shards: Recommended number of shards
    - dict: Error information if failed
    
    Example:
    ```python
    # Get gateway information
    gateway = await DISCORDBOT_GET_GATEWAY()
    
    if "error" not in gateway:
        print(f"Gateway URL: {gateway['url']}")
        print(f"Recommended shards: {gateway['shards']}")
    else:
        print(f"Error: {gateway['error']}")
    ```
    """
    return await discord_request("GET", "/gateway")

@mcp.tool()
async def DISCORDBOT_GET_BOT_GATEWAY() -> Any:
    """Get the Discord gateway URL and recommended shard count for bots.
    
    This tool retrieves the WebSocket gateway URL and recommended number of shards
    specifically for bot connections. Includes additional bot-specific information.
    
    Returns:
    - dict: Bot gateway information containing:
        * url: WebSocket gateway URL
        * shards: Recommended number of shards
        * session_start_limit: Session start limit information
    - dict: Error information if failed
    
    Example:
    ```python
    # Get bot gateway information
    bot_gateway = await DISCORDBOT_GET_BOT_GATEWAY()
    
    if "error" not in bot_gateway:
        print(f"Gateway URL: {bot_gateway['url']}")
        print(f"Recommended shards: {bot_gateway['shards']}")
        print(f"Session limits: {bot_gateway.get('session_start_limit', {})}")
    else:
        print(f"Error: {bot_gateway['error']}")
    ```
    """
    return await discord_request("GET", "/gateway/bot")

@mcp.tool()
async def DISCORDBOT_GET_PUBLIC_KEYS() -> Any:
    """Get public keys for verifying interaction payloads."""
    return await discord_request("GET", "/oauth2/keys")

# ---------------- MESSAGE MANAGEMENT (16 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_MESSAGE(channel_id: str, content: str = "", nonce: int = 0,
                                   tts: bool = False, embeds: str = "", allowed_mentions: str = "",
                                   message_reference: str = "", components: str = "", sticker_ids: str = "",
                                   files: str = "", attachments: str = "", flags: int = 0, poll: str = "") -> Any:
    """Send a message to a Discord channel.
    
    This tool sends a message to a Discord channel with support for text, embeds, files, components,
    and other rich content. Perfect for bot communication, notifications, and interactive messages.
    
    Parameters:
    - channel_id (str): The unique identifier of the target channel (required)
    - content (str): Message text content (max 2000 characters, optional)
    - nonce (int): Unique integer to confirm message sending (optional)
    - tts (bool): Send as text-to-speech message (optional)
    - embeds (str): JSON string of embed objects (max 10, 6000 chars total, optional)
    - allowed_mentions (str): JSON string for mention controls (optional)
    - message_reference (str): JSON string for replying to messages (optional)
    - components (str): JSON string of message components like buttons and select menus (optional)
    - sticker_ids (str): JSON string of sticker IDs (max 3, optional)
    - files (str): JSON string of file paths for uploads (optional)
    - attachments (str): JSON string of attachment objects (optional)
    - flags (int): Bitwise value for message flags (optional)
    - poll (str): JSON string of poll object (optional)
    
    Returns:
    - dict: Message object on success containing:
        * id: Message ID
        * channel_id: Channel ID
        * author: User object of message author
        * content: Message content
        * timestamp: When message was sent
        * edited_timestamp: When message was last edited
        * tts: Whether message is TTS
        * mention_everyone: Whether message mentions @everyone
        * mentions: Array of mentioned users
        * mention_roles: Array of mentioned roles
        * mention_channels: Array of mentioned channels
        * attachments: Array of attachments
        * embeds: Array of embeds
        * reactions: Array of reactions
        * nonce: Message nonce
        * pinned: Whether message is pinned
        * webhook_id: Webhook ID (if applicable)
        * type: Message type
        * activity: Activity object (if applicable)
        * application: Application object (if applicable)
        * application_id: Application ID (if applicable)
        * message_reference: Message reference (if applicable)
        * flags: Message flags
        * referenced_message: Referenced message (if applicable)
        * interaction: Interaction object (if applicable)
        * thread: Thread object (if applicable)
        * components: Array of components
        * sticker_items: Array of sticker items
        * stickers: Array of stickers
        * position: Position in thread
        * role_subscription_data: Role subscription data (if applicable)
        * poll: Poll object (if applicable)
    - dict: Error information if failed
    
    Example:
    ```python
    # Send a simple text message
    message = await DISCORDBOT_CREATE_MESSAGE(
        channel_id="123456789012345678",
        content="Hello, Discord!"
    )
    
    # Send a message with an embed
    embed = '[{"title": "Bot Status", "description": "Bot is online and running!", "color": 65280}]'
    embed_message = await DISCORDBOT_CREATE_MESSAGE(
        channel_id="123456789012345678",
        content="System Update:",
        embeds=embed
    )
    
    # Reply to a message
    reply_ref = '{"message_id": "987654321098765432"}'
    reply = await DISCORDBOT_CREATE_MESSAGE(
        channel_id="123456789012345678",
        content="This is a reply!",
        message_reference=reply_ref
    )
    
    # Send a message with components (buttons)
    components = '[{"type": 1, "components": [{"type": 2, "style": 1, "label": "Click me!", "custom_id": "button_1"}]}]'
    interactive_message = await DISCORDBOT_CREATE_MESSAGE(
        channel_id="123456789012345678",
        content="Click the button below!",
        components=components
    )
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "content": _safe_str(content) if content else None,
        "nonce": nonce if nonce > 0 else None,
        "tts": tts if tts else None,
        "embeds": parse_json_param(embeds, "embeds"),
        "allowed_mentions": parse_json_param(allowed_mentions, "allowed_mentions"),
        "message_reference": parse_json_param(message_reference, "message_reference"),
        "components": parse_json_param(components, "components"),
        "sticker_ids": parse_json_param(sticker_ids, "sticker_ids"),
        "attachments": parse_json_param(attachments, "attachments"),
        "flags": flags if flags > 0 else None,
        "poll": parse_json_param(poll, "poll")
    })
    
    # Handle file uploads
    files_list = parse_json_param(files, "files")
    if files_list:
        multipart_data = await _handle_file_upload(files_list, payload)
        return await discord_request("POST", f"/channels/{channel_id}/messages", data=multipart_data)
    else:
        return await discord_request("POST", f"/channels/{channel_id}/messages", json=payload)

@mcp.tool()
async def DISCORDBOT_GET_MESSAGE(channel_id: str, message_id: str) -> Any:
    """Get a specific message from a Discord channel.
    
    This tool retrieves a single message by its ID from a Discord channel.
    Useful for getting message details, checking message content, or retrieving message metadata.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel containing the message (required)
    - message_id (str): The unique identifier of the message to retrieve (required)
    
    Returns:
    - dict: Message object on success containing:
        * id: Message ID
        * channel_id: Channel ID
        * author: User object of message author
        * content: Message content
        * timestamp: When message was sent
        * edited_timestamp: When message was last edited
        * tts: Whether message is TTS
        * mention_everyone: Whether message mentions @everyone
        * mentions: Array of mentioned users
        * mention_roles: Array of mentioned roles
        * mention_channels: Array of mentioned channels
        * attachments: Array of attachments
        * embeds: Array of embeds
        * reactions: Array of reactions
        * nonce: Message nonce
        * pinned: Whether message is pinned
        * webhook_id: Webhook ID (if applicable)
        * type: Message type
        * activity: Activity object (if applicable)
        * application: Application object (if applicable)
        * application_id: Application ID (if applicable)
        * message_reference: Message reference (if applicable)
        * flags: Message flags
        * referenced_message: Referenced message (if applicable)
        * interaction: Interaction object (if applicable)
        * thread: Thread object (if applicable)
        * components: Array of components
        * sticker_items: Array of sticker items
        * stickers: Array of stickers
        * position: Position in thread
        * role_subscription_data: Role subscription data (if applicable)
        * poll: Poll object (if applicable)
    - dict: Error information if failed
    
    Example:
    ```python
    # Get a specific message
    message = await DISCORDBOT_GET_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432"
    )
    
    if "error" not in message:
        print(f"Message from {message['author']['username']}")
        print(f"Content: {message['content']}")
        print(f"Sent at: {message['timestamp']}")
        print(f"Has embeds: {len(message.get('embeds', []))}")
        print(f"Has attachments: {len(message.get('attachments', []))}")
    else:
        print(f"Error: {message['error']}")
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    return await discord_request("GET", f"/channels/{channel_id}/messages/{message_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_MESSAGE(channel_id: str, message_id: str, content: str = "",
                                   embeds: str = "", flags: int = 0, allowed_mentions: str = "",
                                   components: str = "", attachments: str = "", sticker_ids: str = "") -> Any:
    """Update/edit a message previously sent by the bot.
    
    This tool allows you to edit a message that was previously sent by your bot.
    You can update the content, embeds, components, and other message properties.
    Only provide fields you want to change.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel where the message is located (required)
    - message_id (str): The unique identifier of the message to update (required)
    - content (str): New message content (up to 2000 chars). Set to empty string to remove (optional)
    - embeds (str): JSON string of embed objects (max 10). Set to empty string to remove all (optional)
    - flags (int): Message flags to set (e.g., 4 for SUPPRESS_EMBEDS, optional)
    - allowed_mentions (str): JSON string for mention controls. Set to empty string for default (optional)
    - components (str): JSON string of message components (buttons, select menus). Set to empty string to remove (optional)
    - attachments (str): JSON string of attachment objects to keep/update metadata. Set to empty string to remove (optional)
    - sticker_ids (str): JSON string of sticker IDs (max 3). Set to empty string to remove (optional)
    
    Returns:
    - dict: Updated message object on success containing all message properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Update message content
    updated = await DISCORDBOT_UPDATE_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432",
        content="This message has been updated!"
    )
    
    # Update message with new embed
    new_embed = '[{"title": "Updated Status", "description": "Status has been updated!", "color": 16711680}]'
    embed_updated = await DISCORDBOT_UPDATE_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432",
        content="Status Update:",
        embeds=new_embed
    )
    
    # Remove all embeds from a message
    no_embeds = await DISCORDBOT_UPDATE_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432",
        embeds=""  # Empty string removes all embeds
    )
    ```
    
    Note: Only provide fields you want to change. Use empty strings to clear existing values.
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "content": _safe_str(content) if content else None,
        "embeds": parse_json_param(embeds, "embeds"),
        "flags": flags if flags > 0 else None,
        "allowed_mentions": parse_json_param(allowed_mentions, "allowed_mentions"),
        "components": parse_json_param(components, "components"),
        "attachments": parse_json_param(attachments, "attachments"),
        "sticker_ids": parse_json_param(sticker_ids, "sticker_ids")
    })
    
    return await discord_request("PATCH", f"/channels/{channel_id}/messages/{message_id}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_MESSAGE(channel_id: str, message_id: str) -> Any:
    """Delete a message from a Discord channel.
    
    This tool permanently deletes a message from a Discord channel.
    Can only delete messages sent by the bot or messages less than 2 weeks old.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel containing the message (required)
    - message_id (str): The unique identifier of the message to delete (required)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Delete a message
    result = await DISCORDBOT_DELETE_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432"
    )
    
    if result.get("status") == 204:
        print("Message deleted successfully")
    else:
        print(f"Failed to delete message: {result.get('error', 'Unknown error')}")
    ```
    
    Note: Can only delete messages sent by the bot or messages less than 2 weeks old.
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")

@mcp.tool()
async def DISCORDBOT_LIST_MESSAGES(channel_id: str, around: str = "", before: str = "",
                                  after: str = "", limit: int = 50) -> Any:
    """Get a list of messages from a Discord channel.
    
    This tool retrieves messages from a Discord channel with various filtering options.
    Useful for message history, searching, or retrieving recent messages.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel to get messages from (required)
    - around (str): Get messages around this message ID (optional)
    - before (str): Get messages before this message ID (optional)
    - after (str): Get messages after this message ID (optional)
    - limit (int): Maximum number of messages to return (0-100, default: 50)
    
    Returns:
    - list: Array of message objects, each containing:
        * id: Message ID
        * channel_id: Channel ID
        * author: User object of message author
        * content: Message content
        * timestamp: When message was sent
        * edited_timestamp: When message was last edited
        * tts: Whether message is TTS
        * mention_everyone: Whether message mentions @everyone
        * mentions: Array of mentioned users
        * mention_roles: Array of mentioned roles
        * mention_channels: Array of mentioned channels
        * attachments: Array of attachments
        * embeds: Array of embeds
        * reactions: Array of reactions
        * pinned: Whether message is pinned
        * type: Message type
        * All other message properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Get recent messages
    messages = await DISCORDBOT_LIST_MESSAGES(
        channel_id="123456789012345678",
        limit=10
    )
    
    print(f"Retrieved {len(messages)} messages")
    
    for message in messages:
        print(f"{message['author']['username']}: {message['content'][:50]}...")
    
    # Get messages before a specific message
    older_messages = await DISCORDBOT_LIST_MESSAGES(
        channel_id="123456789012345678",
        before="987654321098765432",
        limit=20
    )
    
    # Get messages after a specific message
    newer_messages = await DISCORDBOT_LIST_MESSAGES(
        channel_id="123456789012345678",
        after="987654321098765432",
        limit=20
    )
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    params = _filter_none({
        "around": around if around else None,
        "before": before if before else None,
        "after": after if after else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/messages", params=params)

@mcp.tool()
async def DISCORDBOT_PIN_MESSAGE(channel_id: str, message_id: str) -> Any:
    """Pin a message in a channel.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to pin (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("PUT", f"/channels/{channel_id}/pins/{message_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_UNPIN_MESSAGE(channel_id: str, message_id: str) -> Any:
    """Unpin a message from a Discord channel.
    
    This tool removes a pinned message from a Discord channel, making it no longer appear
    at the top of the channel's pinned messages list.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel containing the message (required)
    - message_id (str): The unique identifier of the message to unpin (required)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Unpin a message
    result = await DISCORDBOT_UNPIN_MESSAGE(
        channel_id="123456789012345678",
        message_id="987654321098765432"
    )
    
    if result.get("status") == 204:
        print("Message unpinned successfully")
    else:
        print(f"Failed to unpin message: {result.get('error', 'Unknown error')}")
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("DELETE", f"/channels/{channel_id}/pins/{message_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_PINNED_MESSAGES(channel_id: str) -> Any:
    """Get all pinned messages from a Discord channel.
    
    This tool retrieves all pinned messages from a Discord channel. Pinned messages
    are important announcements or information that stay at the top of the channel.
    
    Parameters:
    - channel_id (str): The unique identifier of the channel to get pinned messages from (required)
    
    Returns:
    - list: Array of pinned message objects, each containing:
        * id: Message ID
        * channel_id: Channel ID
        * author: User object of message author
        * content: Message content
        * timestamp: When message was sent
        * edited_timestamp: When message was last edited
        * tts: Whether message is TTS
        * mention_everyone: Whether message mentions @everyone
        * mentions: Array of mentioned users
        * mention_roles: Array of mentioned roles
        * mention_channels: Array of mentioned channels
        * attachments: Array of attachments
        * embeds: Array of embeds
        * reactions: Array of reactions
        * pinned: Whether message is pinned (always true)
        * type: Message type
        * All other message properties
    - dict: Error information if failed
    
    Example:
    ```python
    # Get all pinned messages
    pinned = await DISCORDBOT_LIST_PINNED_MESSAGES(
        channel_id="123456789012345678"
    )
    
    print(f"Found {len(pinned)} pinned messages")
    
    for message in pinned:
        print(f"Pinned: {message['content'][:50]}...")
        print(f"Author: {message['author']['username']}")
        print(f"Pinned at: {message['timestamp']}")
        print("---")
    ```
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}/pins")

@mcp.tool()
async def DISCORDBOT_ADD_MY_MESSAGE_REACTION(channel_id: str, message_id: str, emoji: str) -> Any:
    """Create a reaction for the message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to react to (required)
    - emoji: Emoji to react with (unicode emoji or custom emoji format)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    emoji = _encode_emoji(emoji)
    return await discord_request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me")

@mcp.tool()
async def DISCORDBOT_DELETE_MY_MESSAGE_REACTION(channel_id: str, message_id: str, emoji: str) -> Any:
    """Delete a reaction the current user has made for the message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to remove reaction from (required)
    - emoji: Emoji to remove (unicode emoji or custom emoji format)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    emoji = _encode_emoji(emoji)
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me")

@mcp.tool()
async def DISCORDBOT_DELETE_USER_MESSAGE_REACTION(channel_id: str, message_id: str, emoji: str, user_id: str) -> Any:
    """Deletes another user's reaction.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to remove reaction from (required)
    - emoji: Emoji to remove (unicode emoji or custom emoji format)
    - user_id: ID of the user whose reaction to remove (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    user_id = _validate_user_id(user_id)
    emoji = _encode_emoji(emoji)
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/{user_id}")

@mcp.tool()
async def DISCORDBOT_DELETE_ALL_MESSAGE_REACTIONS(channel_id: str, message_id: str) -> Any:
    """Deletes all reactions on a message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to clear all reactions from (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}/reactions")

@mcp.tool()
async def DISCORDBOT_DELETE_ALL_MESSAGE_REACTIONS_BY_EMOJI(channel_id: str, message_id: str, emoji: str) -> Any:
    """Deletes all the reactions for the given emoji on a message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to clear emoji reactions from (required)
    - emoji: Emoji to clear all reactions for (unicode emoji or custom emoji format)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    emoji = _encode_emoji(emoji)
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}")

@mcp.tool()
async def DISCORDBOT_LIST_MESSAGE_REACTIONS_BY_EMOJI(channel_id: str, message_id: str, emoji: str,
                                                    after: str = "", limit: int = 25) -> Any:
    """Get a list of users that reacted with this emoji.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to get reactions from (required)
    - emoji: Emoji to get reactions for (unicode emoji or custom emoji format)
    - after: Get users after this user ID
    - limit: Max number of users to return (1-100, default: 25)
    
    Returns:
    - list: List of user objects who reacted, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    emoji = _encode_emoji(emoji)
    params = _filter_none({
        "after": after if after else None,  
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}", params=params)

@mcp.tool()
async def DISCORDBOT_BULK_DELETE_MESSAGES(channel_id: str, messages: List[str]) -> Any:
    """Delete multiple messages in a single request.
    
    Parameters:
    - channel_id: ID of the channel containing the messages (required)
    - messages: List of message IDs to delete (required, 2-100 messages)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    
    Note: Messages must be less than 2 weeks old. Cannot delete messages older than 2 weeks.
    """
    channel_id = _validate_channel_id(channel_id)
    payload = {
        "messages": _safe_list(messages)
    }
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("POST", f"/channels/{channel_id}/messages/bulk-delete", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_CROSSPOST_MESSAGE(channel_id: str, message_id: str) -> Any:
    """
    Crossposts a message from an announcement (news) channel.

    Args:
        channel_id: ID of the announcement channel containing the message.
        message_id: ID of the message to be crossposted.
    
    Returns:
        dict containing:
            - data: the crossposted message object (or empty dict)
            - successful: bool
            - error: error message if any
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    return await discord_request("POST", f"/channels/{channel_id}/messages/{message_id}/crosspost")

# ---------------- MODERATION & AUTOMATION (8 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_AUTO_MODERATION_RULE(guild_id: str, name: str, event_type: int, trigger_type: int,
                                                 trigger_metadata: str = "", actions: str = "",
                                                 enabled: bool = True, exempt_roles: str = "",
                                                 exempt_channels: str = "", reason: str = "") -> Any:
    """Create a new auto moderation rule for a Discord guild.
    
    Parameters:
    - guild_id: The unique identifier of the Discord guild (server) where the rule will be created (required)
    - name: Name of the auto moderation rule (required)
    - event_type: Type of event that triggers the rule (required)
        * 1 = MESSAGE_SEND
    - trigger_type: Type of trigger for the rule (required)
        * 1 = KEYWORD
        * 2 = SPAM
        * 3 = KEYWORD_PRESET
        * 4 = MENTION_SPAM
    - trigger_metadata: JSON string of trigger-specific metadata
    - actions: JSON string of actions to take when rule is triggered (default: delete message if empty)
    - enabled: Whether the rule is enabled (default: true)
    - exempt_roles: JSON string of role IDs exempt from the rule
    - exempt_channels: JSON string of channel IDs exempt from the rule
    - reason: Reason for creating the rule (for audit logs)
    
    Requires 'manage guild' permission.
    
    Example actions:
    - Delete message: '[{"type": 1, "metadata": {}}]'
    - Send alert: '[{"type": 2, "metadata": {"channel_id": "123456789"}}]'
    - Timeout user: '[{"type": 3, "metadata": {"duration_seconds": 60}}]'
    """
    guild_id = _validate_guild_id(guild_id)
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    # Parse actions with default fallback
    actions_data = parse_json_param(actions, "actions")
    if not actions_data:
        # Default action: delete message
        actions_data = [{"type": 1, "metadata": {}}]
    
    payload = _filter_none({
        "name": _safe_str(name),
        "event_type": event_type,
        "trigger_type": trigger_type,
        "trigger_metadata": parse_json_param(trigger_metadata, "trigger_metadata"),
        "actions": actions_data,
        "enabled": enabled,
        "exempt_roles": parse_json_param(exempt_roles, "exempt_roles"),
        "exempt_channels": parse_json_param(exempt_channels, "exempt_channels")
    })
    
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/auto-moderation/rules", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_AUTO_MODERATION_RULE(guild_id: str, rule_id: str) -> Any:
    """Get a single auto moderation rule."""
    guild_id = _validate_guild_id(guild_id)
    rule_id = _validate_snowflake(rule_id, "Rule ID")
    return await discord_request("GET", f"/guilds/{guild_id}/auto-moderation/rules/{rule_id}")

@mcp.tool()
async def DISCORDBOT_LIST_AUTO_MODERATION_RULES(guild_id: str) -> Any:
    """Get all auto moderation rules for a guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/auto-moderation/rules")

@mcp.tool()
async def DISCORDBOT_UPDATE_AUTO_MODERATION_RULE(guild_id: str, rule_id: str, name: str = "",
                                                 event_type: int = 0, trigger_metadata: str = "",
                                                 actions: str = "", enabled: bool = True,
                                                 exempt_roles: str = "", exempt_channels: str = "",
                                                 reason: str = "") -> Any:
    """Modify an existing auto moderation rule.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - rule_id: ID of the rule to update (required)
    - name: New name for the rule
    - event_type: New event type (0 = no change)
        * 1 = MESSAGE_SEND
    - trigger_metadata: JSON string of trigger metadata
    - actions: JSON string of actions to take
    - enabled: Whether the rule is enabled (default: true)
    - exempt_roles: JSON string of role IDs to exempt
    - exempt_channels: JSON string of channel IDs to exempt
    - reason: Reason for updating the rule (for audit logs)
    """
    guild_id = _validate_guild_id(guild_id)
    rule_id = _validate_snowflake(rule_id, "Rule ID")
    
    # Parse JSON strings to objects
    def parse_json_param(param_str: str, param_name: str):
        if not param_str:
            return None
        try:
            return json.loads(param_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for {param_name}: {e}")
    
    payload = _filter_none({
        "name": _safe_str(name) if name else None,
        "event_type": event_type if event_type > 0 else None,
        "trigger_metadata": parse_json_param(trigger_metadata, "trigger_metadata"),
        "actions": parse_json_param(actions, "actions"),
        "enabled": enabled,
        "exempt_roles": parse_json_param(exempt_roles, "exempt_roles"),
        "exempt_channels": parse_json_param(exempt_channels, "exempt_channels")
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/auto-moderation/rules/{rule_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_AUTO_MODERATION_RULE(guild_id: str, rule_id: str) -> Any:
    """Delete an auto moderation rule."""
    guild_id = _validate_guild_id(guild_id)
    rule_id = _validate_snowflake(rule_id, "Rule ID")
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("DELETE", f"/guilds/{guild_id}/auto-moderation/rules/{rule_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_BULK_BAN_USERS_FROM_GUILD(guild_id: str, user_ids: List[str], delete_message_seconds: int = 0,
                                                reason: str = "") -> Any:
    """Bulk ban users from a guild.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_ids: List of user IDs to ban (required)
    - delete_message_seconds: Number of seconds to delete messages (0 = don't delete)
    - reason: Reason for banning users (for audit logs)
    
    Note: Discord API doesn't support true bulk banning, so this tool performs individual bans sequentially.
    """
    guild_id = _validate_guild_id(guild_id)
    
    if not user_ids:
        return {
            "error": "No users to ban",
            "message": "user_ids list cannot be empty"
        }
    
    results = []
    errors = []
    
    for user_id in user_ids:
        try:
            user_id = _validate_user_id(user_id)
            payload = _filter_none({
                "delete_message_seconds": delete_message_seconds if delete_message_seconds > 0 else None
            })
            headers = DEFAULT_HEADERS.copy()
            if reason:
                headers["X-Audit-Log-Reason"] = _safe_str(reason)
            
            result = await discord_request("PUT", f"/guilds/{guild_id}/bans/{user_id}", json=payload, headers=headers)
            results.append({
                "user_id": user_id,
                "status": "success",
                "result": result
            })
        except Exception as e:
            errors.append({
                "user_id": user_id,
                "status": "error",
                "error": str(e)
            })
    
    return {
        "total_users": len(user_ids),
        "successful_bans": len(results),
        "failed_bans": len(errors),
        "results": results,
        "errors": errors
    }

@mcp.tool()
async def DISCORDBOT_BAN_USER_FROM_GUILD(guild_id: str, user_id: str, delete_message_seconds: int = 0,
                                          reason: str = "") -> Any:
    """Ban a user from a Discord server.
    
    This tool permanently bans a user from a Discord server. The user will be unable to rejoin
    unless unbanned. You can optionally delete their recent messages.
    
    Parameters:
    - guild_id (str): The unique identifier of the Discord server (required)
    - user_id (str): The unique identifier of the user to ban (required)
    - delete_message_seconds (int): Number of seconds of messages to delete (0 = don't delete, optional)
        * 0 = Don't delete any messages
        * 604800 = Delete messages from the last 7 days
        * 1209600 = Delete messages from the last 14 days
        * 2592000 = Delete messages from the last 30 days
    - reason (str): Reason for banning the user (for audit logs, optional)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Ban a user without deleting messages
    result = await DISCORDBOT_BAN_USER_FROM_GUILD(
        guild_id="876543210987654321",
        user_id="123456789012345678",
        reason="Violation of server rules"
    )
    
    # Ban a user and delete their messages from the last 7 days
    result = await DISCORDBOT_BAN_USER_FROM_GUILD(
        guild_id="876543210987654321",
        user_id="123456789012345678",
        delete_message_seconds=604800,  # 7 days
        reason="Spam and harassment"
    )
    
    if result.get("status") == 204:
        print("User banned successfully")
    else:
        print(f"Failed to ban user: {result.get('error', 'Unknown error')}")
    ```
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    payload = _filter_none({
        "delete_message_seconds": delete_message_seconds if delete_message_seconds > 0 else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PUT", f"/guilds/{guild_id}/bans/{user_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_UNBAN_USER_FROM_GUILD(guild_id: str, user_id: str, reason: str = "") -> Any:
    """Remove a ban for a user from a Discord server.
    
    This tool removes a ban for a user, allowing them to rejoin the Discord server.
    The user will need to use a new invite link to rejoin.
    
    Parameters:
    - guild_id (str): The unique identifier of the Discord server (required)
    - user_id (str): The unique identifier of the user to unban (required)
    - reason (str): Reason for unbanning the user (for audit logs, optional)
    
    Returns:
    - dict: Empty response on success (status 204)
    - dict: Error information if failed
    
    Example:
    ```python
    # Unban a user
    result = await DISCORDBOT_UNBAN_USER_FROM_GUILD(
        guild_id="876543210987654321",
        user_id="123456789012345678",
        reason="Appeal approved"
    )
    
    if result.get("status") == 204:
        print("User unbanned successfully")
    else:
        print(f"Failed to unban user: {result.get('error', 'Unknown error')}")
    ```
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/bans/{user_id}", headers=headers)

# ---------------- USER & MEMBER MANAGEMENT (12 tools) ----------------
@mcp.tool()
async def DISCORDBOT_GET_USER(user_id: str) -> Any:
    """Get information about a Discord user.
    
    This tool retrieves detailed information about a Discord user including their username,
    avatar, discriminator, and other public profile information.
    
    Parameters:
    - user_id (str): The unique identifier of the user to retrieve (required)
    
    Returns:
    - dict: User object on success containing:
        * id: User ID
        * username: Username
        * discriminator: User discriminator
        * global_name: Global display name
        * avatar: Avatar hash
        * bot: Whether user is a bot
        * system: Whether user is a system user
        * mfa_enabled: Whether user has MFA enabled
        * banner: Banner hash
        * accent_color: Accent color
        * locale: User locale
        * verified: Whether user is verified
        * email: Email address (if applicable)
        * flags: User flags
        * premium_type: Premium type
        * public_flags: Public flags
    - dict: Error information if failed
    
    Example:
    ```python
    # Get user information
    user = await DISCORDBOT_GET_USER(
        user_id="123456789012345678"
    )
    
    if "error" not in user:
        print(f"Username: {user['username']}")
        print(f"Discriminator: {user.get('discriminator', 'N/A')}")
        print(f"Avatar: {user.get('avatar', 'No avatar')}")
        print(f"Is Bot: {user.get('bot', False)}")
        print(f"Verified: {user.get('verified', False)}")
    else:
        print(f"Error: {user['error']}")
    ```
    """
    user_id = _validate_user_id(user_id)
    return await discord_request("GET", f"/users/{user_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_MY_USER(username: str, avatar: str = "") -> Any:
    """Updates the current authenticated user's discord username and/or avatar.
    
    Parameters:
    - username: New username for the user (required)
    - avatar: Base64 encoded avatar data (empty string = no change)
    """
    payload = _filter_none({
        "username": _safe_str(username),
        "avatar": avatar if avatar else None
    })
    return await discord_request("PATCH", "/users/@me", json=payload)

@mcp.tool()
async def DISCORDBOT_UPDATE_MY_GUILD_MEMBER(guild_id: str, nick: str = "") -> Any:
    """Modifies the nickname of the currently authenticated user within a specified discord guild.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - nick: New nickname (empty string = remove nickname)
    """
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "nick": _safe_str(nick) if nick else None
    })
    return await discord_request("PATCH", f"/guilds/{guild_id}/members/@me", json=payload)

@mcp.tool()
async def DISCORDBOT_ADD_GUILD_MEMBER(guild_id: str, user_id: str, access_token: str, nick: str = "",
                                      roles: str = "", mute: bool = False, deaf: bool = False) -> Any:
    """Adds a user to the guild.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user to add (required)
    - access_token: OAuth2 access token for the user (required)
    - nick: Nickname for the user (empty string = no nickname)
    - roles: JSON string of role IDs to assign (empty string = no roles)
    - mute: Whether to mute the user (default: false)
    - deaf: Whether to deafen the user (default: false)
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    
    # Parse roles JSON string
    roles_list = None
    if roles:
        try:
            roles_list = json.loads(roles)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON for roles: {e}")
    
    payload = _filter_none({
        "access_token": access_token,
        "nick": _safe_str(nick) if nick else None,
        "roles": roles_list,
        "mute": mute if mute else None,
        "deaf": deaf if deaf else None
    })
    return await discord_request("PUT", f"/guilds/{guild_id}/members/{user_id}", json=payload)

@mcp.tool()
async def DISCORDBOT_ADD_GUILD_MEMBER_ROLE(guild_id: str, user_id: str, role_id: str, reason: str = "") -> Any:
    """Adds a role to a guild member.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user (required)
    - role_id: ID of the role to add (required)
    - reason: Reason for adding the role (for audit logs)
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PUT", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_MEMBER_ROLE(guild_id: str, user_id: str, role_id: str, reason: str = "") -> Any:
    """Removes a role from a guild member.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user (required)
    - role_id: ID of the role to remove (required)
    - reason: Reason for removing the role (for audit logs)
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_MEMBER(guild_id: str, user_id: str, reason: str = "") -> Any:
    """Remove a member from a guild.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user to remove (required)
    - reason: Reason for removing the member (for audit logs)
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/members/{user_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_ADD_THREAD_MEMBER(channel_id: str, user_id: str) -> Any:
    """Adds another member to a thread."""
    channel_id = _validate_channel_id(channel_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("PUT", f"/channels/{channel_id}/thread-members/{user_id}")

@mcp.tool()
async def DISCORDBOT_ADD_GROUP_DM_USER(channel_id: str, user_id: str, access_token: str, nick: str = "") -> Any:
    """Adds a recipient to a Group DM using their access token.
    
    Parameters:
    - channel_id: ID of the group DM channel (required)
    - user_id: ID of the user to add (required)
    - access_token: OAuth2 access token for the user (required)
    - nick: Nickname for the user (empty string = no nickname)
    """
    channel_id = _validate_channel_id(channel_id)
    user_id = _validate_user_id(user_id)
    payload = _filter_none({
        "access_token": access_token,
        "nick": _safe_str(nick) if nick else None
    })
    return await discord_request("PUT", f"/channels/{channel_id}/recipients/{user_id}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GROUP_DM_USER(channel_id: str, user_id: str) -> Any:
    """Removes a recipient from a Group DM."""
    channel_id = _validate_channel_id(channel_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("DELETE", f"/channels/{channel_id}/recipients/{user_id}")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_MEMBER(guild_id: str, user_id: str) -> Any:
    """Get information about a guild member.
    
    This tool retrieves detailed information about a user's membership in a specific Discord server,
    including their roles, nickname, join date, and other guild-specific data.
    
    Parameters:
    - guild_id (str): The unique identifier of the Discord server (required)
    - user_id (str): The unique identifier of the user (required)
    
    Returns:
    - dict: Guild member object on success containing:
        * user: User object
        * nick: Guild nickname
        * avatar: Guild avatar hash
        * roles: Array of role IDs
        * joined_at: When user joined the guild
        * premium_since: When user started boosting
        * deaf: Whether user is deafened
        * mute: Whether user is muted
        * flags: Guild member flags
        * pending: Whether user is pending verification
        * permissions: Computed permissions
        * communication_disabled_until: When communication timeout ends
    - dict: Error information if failed
    
    Example:
    ```python
    # Get guild member information
    member = await DISCORDBOT_GET_GUILD_MEMBER(
        guild_id="876543210987654321",
        user_id="123456789012345678"
    )
    
    if "error" not in member:
        print(f"User: {member['user']['username']}")
        print(f"Nickname: {member.get('nick', 'No nickname')}")
        print(f"Joined: {member['joined_at']}")
        print(f"Roles: {len(member['roles'])}")
        print(f"Boosting since: {member.get('premium_since', 'Not boosting')}")
    else:
        print(f"Error: {member['error']}")
    ```
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("GET", f"/guilds/{guild_id}/members/{user_id}")

@mcp.tool()
async def DISCORDBOT_SEARCH_GUILD_MEMBERS(guild_id: str, query: str = "", limit: int = 0) -> Any:
    """Search for guild members based on query string.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - query: Search query string (empty string = no filter)
    - limit: Maximum number of results (0 = default limit)
    """
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "query": _safe_str(query) if query else None,
        "limit": limit if limit > 0 else None
    })
    return await discord_request("GET", f"/guilds/{guild_id}/members/search", params=params)

# ---------------- EMOJI & STICKER MANAGEMENT (12 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_EMOJI(guild_id: str, name: str, file_path: str, roles: Optional[List[str]] = None,
                                        reason: Optional[str] = None) -> Any:
    """
    Create a new custom emoji in a specified Discord guild from a local file.

    Args:
        guild_id: The ID of the Discord guild (server).
        name: The emoji name (2–32 chars, alphanumeric or underscores).
        file_path: Path to the image file (PNG, JPG, or GIF).
        roles: Optional list of role IDs allowed to use this emoji.
        reason: Optional reason for audit log.

    Returns:
        A dictionary with the created emoji data.
    """
    import base64
    
    guild_id = _validate_guild_id(guild_id)
    
    # Read the image file and convert to Base64
    try:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
            # Determine MIME type from file extension
            if file_path.lower().endswith(".png"):
                mime = "image/png"
            elif file_path.lower().endswith(".gif"):
                mime = "image/gif"
            elif file_path.lower().endswith((".jpg", ".jpeg")):
                mime = "image/jpeg"
            else:
                raise ValueError("Unsupported file type. Use PNG, JPG, or GIF.")
            image_base64 = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
    except FileNotFoundError:
        raise ValueError(f"File not found: {file_path}")
    except Exception as e:
        raise ValueError(f"Error reading file: {str(e)}")

    payload = _filter_none({
        "name": _safe_str(name),
        "image": image_base64,
        "roles": _safe_list(roles)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/emojis", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_EMOJI(guild_id: str, emoji_id: str) -> Any:
    """
    Retrieves a specific custom emoji from a Discord guild.
    Args:
        guild_id: The Discord guild (server) ID.
        emoji_id: The ID of the emoji to fetch.
    Returns:
        A dictionary containing emoji details.
    """
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    return await discord_request("GET", f"/guilds/{guild_id}/emojis/{emoji_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_EMOJI(guild_id: str, emoji_id: str, name: Optional[str] = None,
                                        roles: Optional[List[str]] = None, reason: Optional[str] = None) -> Any:
    """
    Update a guild emoji's name and/or roles.
    Args:
        guild_id: The Discord guild (server) ID.
        emoji_id: The ID of the emoji to update.
        name: Optional new name for the emoji (2-32 chars).
        roles: Optional list of role IDs allowed to use the emoji.
               Empty list makes it available to everyone.
               If None, roles remain unchanged.
        reason: Optional reason for audit log.
    Returns:
        A dictionary with the updated emoji data.
    """
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    
    payload = {}
    if name is not None:
        payload["name"] = _safe_str(name)
    if roles is not None:
        payload["roles"] = _safe_list(roles)

    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/emojis/{emoji_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_EMOJI(guild_id: str, emoji_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes a custom emoji from a Discord guild.
    Args:
        guild_id: The Discord guild (server) ID.
        emoji_id: The ID of the emoji to delete.
        reason: Optional reason for audit log.
    Returns:
        A dictionary indicating success or error.
    """
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/emojis/{emoji_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_EMOJIS(guild_id: str) -> Any:
    """
    Retrieves all custom emojis for a specified Discord guild.
    Args:
        guild_id: The Discord guild (server) ID.
    Returns:
        A dictionary containing a list of emojis and their details.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/emojis")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_STICKER(guild_id: str, name: str, description: str, tags: str,
                                          file: str, reason: Optional[str] = None) -> Any:
    """
    Creates a new sticker in a specified Discord guild.

    Args:
        guild_id: ID of the guild.
        name: Name of the sticker (2-30 characters).
        description: Description of the sticker (2-100 characters).
        tags: Autocomplete tags (comma-separated, max 200 chars).
        file: Sticker file path (PNG, APNG, Lottie JSON; max 512KB; 320x320px recommended).
        reason: Optional reason for audit log.

    Returns:
        dict containing:
            - data: newly created sticker object
            - successful: bool
            - error: error message if any
    """
    guild_id = _validate_guild_id(guild_id)
    
    # Validate tags parameter
    if tags and len(tags) > 200:
        raise ValueError("Tags must be 200 characters or less.")

    # Read the file as bytes
    if not file or not os.path.exists(file):
        raise FileNotFoundError("Sticker file not found or path invalid.")

    with open(file, "rb") as f:
        file_data = f.read()

    # Determine MIME type
    ext = os.path.splitext(file)[1].lower()
    if ext == ".png":
        mime = "image/png"
    elif ext == ".apng":
        mime = "image/apng"
    elif ext == ".json":
        mime = "application/json"
    else:
        raise ValueError("Unsupported file type. Use PNG, APNG, or Lottie JSON.")

    # Prepare form data
    form_data = {
        "name": name or "new_sticker",
        "description": description or "",
        "tags": tags or "sticker"
    }
    
    files = {"file": (os.path.basename(file), file_data, mime)}
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    headers.pop("Content-Type", None)  # Remove for multipart
    
    return await discord_request("POST", f"/guilds/{guild_id}/stickers", data=form_data, files=files, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_STICKER(guild_id: str, sticker_id: str) -> Any:
    """
    Retrieves a Discord sticker from a specified guild.

    Args:
        guild_id: The ID of the guild (server) where the sticker exists.
        sticker_id: The ID of the sticker to retrieve.

    Returns:
        dict containing:
            - data: the retrieved sticker object
            - successful: bool
            - error: error message if any
    """
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    return await discord_request("GET", f"/guilds/{guild_id}/stickers/{sticker_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_STICKER(guild_id: str, sticker_id: str, name: Optional[str] = None,
                                          description: Optional[str] = None, tags: Optional[str] = None,
                                          reason: Optional[str] = None) -> Any:
    """
    Updates a sticker in a specified Discord guild. Supports partial updates.

    Args:
        guild_id: ID of the guild where the sticker exists.
        sticker_id: ID of the sticker to update.
        name: New name of the sticker (2-30 characters).
        description: New description of the sticker (2-100 characters).
        tags: New autocomplete tags (comma-separated, max 200 chars).
        reason: Optional reason for audit log.

    Returns:
        dict containing:
            - data: updated sticker object
            - successful: bool
            - error: error message if any
    """
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    
    payload = {}
    if name is not None:
        payload["name"] = _safe_str(name)
    if description is not None:
        payload["description"] = _safe_str(description)
    if tags is not None:
        payload["tags"] = _safe_str(tags)

    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/stickers/{sticker_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_STICKER(guild_id: str, sticker_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes a sticker from a specified Discord guild.

    Args:
        guild_id: ID of the guild where the sticker exists.
        sticker_id: ID of the sticker to delete.
        reason: Optional reason for audit log.

    Returns:
        dict containing:
            - data: typically empty on successful deletion
            - successful: bool
            - error: error message if any
    """
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/stickers/{sticker_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_STICKERS(guild_id: str) -> Any:
    """
    Retrieves a list of all custom stickers in the specified Discord guild.

    Args:
        guild_id: ID of the Discord guild.

    Returns:
        dict containing:
            - data: list of sticker objects
            - successful: bool
            - error: error message if any
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/stickers")

@mcp.tool()
async def DISCORDBOT_LIST_STICKER_PACKS() -> Any:
    """
    Lists all standard sticker packs available to Nitro subscribers.
    
    Returns:
        dict containing:
            - data: an object with a list of sticker packs and their stickers
            - successful: bool
            - error: error message if any
    """
    return await discord_request("GET", "/sticker-packs")

@mcp.tool()
async def DISCORDBOT_GET_STICKER(sticker_id: str) -> Any:
    """
    Retrieves a specific Discord sticker by its ID.

    Args:
        sticker_id: The unique ID of the sticker to retrieve.

    Returns:
        dict containing:
            - data: a dictionary representing the sticker object
            - successful: bool
            - error: error message if any
    """
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    return await discord_request("GET", f"/stickers/{sticker_id}")

# ---------------- WEBHOOK MANAGEMENT (17 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_WEBHOOK(channel_id: str, name: str, avatar: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """
    Creates a new webhook for a Discord channel.

    NOTE: Requires the 'Manage Webhooks' permission.

    Args:
        channel_id (str): The ID of the channel to create the webhook in.
        name (str): The name of the webhook (1-80 characters).
        avatar (Optional[str]): Base64 encoded image data for the webhook avatar.
        reason: Optional reason for audit log.
    
    Returns:
        dict: Webhook object containing id, token, url, and other webhook details.
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "avatar": avatar
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/channels/{channel_id}/webhooks", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_WEBHOOK(webhook_id: str) -> Any:
    """
    Retrieves a webhook by its ID.

    Args:
        webhook_id (str): The ID of the webhook to retrieve.

    Returns:
        dict: Webhook object containing webhook details.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    return await discord_request("GET", f"/webhooks/{webhook_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_WEBHOOK(webhook_id: str, name: Optional[str] = None, avatar: Optional[str] = None,
                                    channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """
    Updates a webhook's properties.

    NOTE: Requires the 'Manage Webhooks' permission.

    Args:
        webhook_id (str): The ID of the webhook to update.
        name (Optional[str]): The new name of the webhook (1-80 characters).
        avatar (Optional[str]): Base64 encoded image data for the webhook avatar.
        channel_id (Optional[str]): The new channel ID to move the webhook to.
        reason: Optional reason for audit log.

    Returns:
        dict: Updated webhook object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "avatar": avatar,
        "channel_id": channel_id
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/webhooks/{webhook_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_WEBHOOK(webhook_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes a webhook permanently.

    NOTE: Requires the 'Manage Webhooks' permission.

    Args:
        webhook_id (str): The ID of the webhook to delete.
        reason: Optional reason for audit log.

    Returns:
        dict: Confirmation of deletion.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/webhooks/{webhook_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str) -> Any:
    """
    Retrieves a webhook by its ID and token.

    Args:
        webhook_id (str): The ID of the webhook to retrieve.
        webhook_token (str): The token of the webhook.

    Returns:
        dict: Webhook object containing webhook details.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    return await discord_request("GET", f"/webhooks/{webhook_id}/{webhook_token}")

@mcp.tool()
async def DISCORDBOT_UPDATE_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str, name: Optional[str] = None,
                                             avatar: Optional[str] = None, channel_id: Optional[str] = None) -> Any:
    """
    Updates a webhook's properties using its token.

    Args:
        webhook_id (str): The ID of the webhook to update.
        webhook_token (str): The token of the webhook.
        name (Optional[str]): The new name of the webhook (1-80 characters).
        avatar (Optional[str]): Base64 encoded image data for the webhook avatar.
        channel_id (Optional[str]): The new channel ID to move the webhook to.

    Returns:
        dict: Updated webhook object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "avatar": avatar,
        "channel_id": channel_id
    })
    return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str) -> Any:
    """
    Deletes a webhook permanently using its token.

    Args:
        webhook_id (str): The ID of the webhook to delete.
        webhook_token (str): The token of the webhook.

    Returns:
        dict: Confirmation of deletion.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    return await discord_request("DELETE", f"/webhooks/{webhook_id}/{webhook_token}")

@mcp.tool()
async def DISCORDBOT_EXECUTE_WEBHOOK(webhook_id: str, webhook_token: str, content: Optional[str] = None,
                                     username: Optional[str] = None, avatar_url: Optional[str] = None,
                                     tts: Optional[bool] = None, embeds: Optional[List[Dict[str, Any]]] = None,
                                     allowed_mentions: Optional[Dict[str, Any]] = None, components: Optional[List[Dict[str, Any]]] = None,
                                     files: Optional[List[Union[str, BinaryIO]]] = None, payload_json: Optional[str] = None,
                                     attachments: Optional[List[Dict[str, Any]]] = None, flags: Optional[int] = None,
                                     thread_name: Optional[str] = None, wait: Optional[bool] = None) -> Any:
    """
    Executes a webhook to send a message to a Discord channel.

    Args:
        webhook_id (str): The ID of the webhook to execute.
        webhook_token (str): The token of the webhook.
        content (Optional[str]): The message content (max 2000 characters).
        username (Optional[str]): Override the webhook's username.
        avatar_url (Optional[str]): Override the webhook's avatar URL.
        tts (Optional[bool]): Whether to send as text-to-speech.
        embeds (Optional[List[Dict[str, Any]]]): Array of embed objects.
        allowed_mentions (Optional[Dict[str, Any]]): Allowed mentions configuration.
        components (Optional[List[Dict[str, Any]]]): Array of message components.
        files (Optional[List[Union[str, BinaryIO]]]): Array of files to upload.
        payload_json (Optional[str]): JSON payload string.
        attachments (Optional[List[Dict[str, Any]]]): Array of attachment objects.
        flags (Optional[int]): Message flags.
        thread_name (Optional[str]): Name for thread creation.
        wait (Optional[bool]): Whether to wait for message creation.
    
    Returns:
        dict: Message object if wait=True, otherwise empty response.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "content": _safe_str(content),
        "username": _safe_str(username),
        "avatar_url": avatar_url,
        "embeds": _safe_list(embeds),
        "allowed_mentions": _safe_dict(allowed_mentions),
        "components": _safe_list(components),
        "payload_json": payload_json,
        "attachments": _safe_list(attachments),
        "flags": flags,
        "thread_name": _safe_str(thread_name)
    })
    
    # Handle boolean parameters separately to avoid filtering out False values
    if tts is not None:
        payload["tts"] = tts
    if wait is not None:
        payload["wait"] = wait
    
    if files:
        multipart_data = await _handle_file_upload(files, payload)
        return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}", data=multipart_data)
    else:
        return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}", json=payload)

@mcp.tool()
async def DISCORDBOT_EXECUTE_SLACK_COMPATIBLE_WEBHOOK(webhook_id: str, webhook_token: str, payload: Dict[str, Any],
                                                      wait: Optional[bool] = None, thread_id: Optional[str] = None) -> Any:
    """
    Executes a webhook in Slack-compatible mode.

    Args:
        webhook_id (str): The ID of the webhook to execute.
        webhook_token (str): The token of the webhook.
        payload (Dict[str, Any]): The Slack-compatible payload.
        wait (Optional[bool]): Whether to wait for message creation.
        thread_id (Optional[str]): The thread ID to send the message to.

    Returns:
        dict: Response from the webhook execution.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "wait": wait,
        "thread_id": thread_id
    })
    return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}/slack", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_EXECUTE_GITHUB_COMPATIBLE_WEBHOOK(webhook_id: str, webhook_token: str, payload: Dict[str, Any],
                                                       wait: Optional[bool] = None, thread_id: Optional[str] = None) -> Any:
    """
    Executes a webhook in GitHub-compatible mode.

    Args:
        webhook_id (str): The ID of the webhook to execute.
        webhook_token (str): The token of the webhook.
        payload (Dict[str, Any]): The GitHub-compatible payload.
        wait (Optional[bool]): Whether to wait for message creation.
        thread_id (Optional[str]): The thread ID to send the message to.

    Returns:
        dict: Response from the webhook execution.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "wait": wait,
        "thread_id": thread_id
    })
    return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}/github", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_GET_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, message_id: str, thread_id: Optional[str] = None) -> Any:
    """
    Retrieves a previously-sent webhook message.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        message_id (str): The ID of the message to retrieve.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: The webhook message object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    message_id = _validate_message_id(message_id)
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("GET", f"/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}", params=params)

@mcp.tool()
async def DISCORDBOT_UPDATE_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, message_id: str,
                                           content: Optional[str] = None, embeds: Optional[List[Dict[str, Any]]] = None,
                                           allowed_mentions: Optional[Dict[str, Any]] = None, components: Optional[List[Dict[str, Any]]] = None,
                                           files: Optional[List[Union[str, BinaryIO]]] = None, attachments: Optional[List[Dict[str, Any]]] = None,
                                           thread_id: Optional[str] = None) -> Any:
    """
    Updates a previously-sent webhook message.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        message_id (str): The ID of the message to update.
        content (Optional[str]): The new message content.
        embeds (Optional[List[Dict[str, Any]]]): Array of embed objects.
        allowed_mentions (Optional[Dict[str, Any]]): Allowed mentions configuration.
        components (Optional[List[Dict[str, Any]]]): Array of message components.
        files (Optional[List[Union[str, BinaryIO]]]): Array of files to upload.
        attachments (Optional[List[Dict[str, Any]]]): Array of attachment objects.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: The updated webhook message object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    message_id = _validate_message_id(message_id)
    payload = _filter_none({
        "content": _safe_str(content),
        "embeds": _safe_list(embeds),
        "allowed_mentions": _safe_dict(allowed_mentions),
        "components": _safe_list(components),
        "attachments": _safe_list(attachments)
    })
    params = _filter_none({
        "thread_id": thread_id
    })
    
    if files:
        multipart_data = await _handle_file_upload(files, payload)
        return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}", data=multipart_data, params=params)
    else:
        return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_DELETE_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, message_id: str, thread_id: Optional[str] = None) -> Any:
    """
    Deletes a message that was created by the webhook.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        message_id (str): The ID of the message to delete.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: Confirmation of deletion.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    message_id = _validate_message_id(message_id)
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("DELETE", f"/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}", params=params)

@mcp.tool()
async def DISCORDBOT_GET_ORIGINAL_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, thread_id: Optional[str] = None) -> Any:
    """
    Retrieves the original message that was created by the webhook.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: The original webhook message object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("GET", f"/webhooks/{webhook_id}/{webhook_token}/messages/@original", params=params)

@mcp.tool()
async def DISCORDBOT_UPDATE_ORIGINAL_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str,
                                                     content: Optional[str] = None, embeds: Optional[List[Dict[str, Any]]] = None,
                                                     allowed_mentions: Optional[Dict[str, Any]] = None, components: Optional[List[Dict[str, Any]]] = None,
                                                     files: Optional[List[Union[str, BinaryIO]]] = None, attachments: Optional[List[Dict[str, Any]]] = None,
                                                     thread_id: Optional[str] = None) -> Any:
    """
    Updates the original message that was created by the webhook.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        content (Optional[str]): The new message content.
        embeds (Optional[List[Dict[str, Any]]]): Array of embed objects.
        allowed_mentions (Optional[Dict[str, Any]]): Allowed mentions configuration.
        components (Optional[List[Dict[str, Any]]]): Array of message components.
        files (Optional[List[Union[str, BinaryIO]]]): Array of files to upload.
        attachments (Optional[List[Dict[str, Any]]]): Array of attachment objects.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: The updated original webhook message object.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "content": _safe_str(content),
        "embeds": _safe_list(embeds),
        "allowed_mentions": _safe_dict(allowed_mentions),
        "components": _safe_list(components),
        "attachments": _safe_list(attachments)
    })
    params = _filter_none({
        "thread_id": thread_id
    })
    
    if files:
        multipart_data = await _handle_file_upload(files, payload)
        return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}/messages/@original", data=multipart_data, params=params)
    else:
        return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}/messages/@original", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_DELETE_ORIGINAL_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, thread_id: Optional[str] = None) -> Any:
    """
    Deletes the original message that was created by the webhook.

    Args:
        webhook_id (str): The ID of the webhook.
        webhook_token (str): The token of the webhook.
        thread_id (Optional[str]): The thread ID if the message is in a thread.

    Returns:
        dict: Confirmation of deletion.
    """
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("DELETE", f"/webhooks/{webhook_id}/{webhook_token}/messages/@original", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_CHANNEL_WEBHOOKS(channel_id: str) -> Any:
    """
    Retrieves a list of webhooks for a channel.

    NOTE: Requires the 'Manage Webhooks' permission.

    Args:
        channel_id (str): The ID of the channel to retrieve webhooks from.

    Returns:
        dict: List of webhook objects.
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}/webhooks")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WEBHOOKS(guild_id: str) -> Any:
    """
    Retrieves a list of webhooks for a guild.

    NOTE: Requires the 'Manage Webhooks' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve webhooks from.

    Returns:
        dict: List of webhook objects.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/webhooks")

# ---------------- GUILD MANAGEMENT (46 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_GUILD(name: str, **kwargs) -> Any:
    """
    Creates a new Discord guild (server).
    NOTE: Unverified bots are limited to 10 guilds.

    Args:
        name (str): The name of the new guild (2-100 characters).
        **kwargs: Optional parameters such as 'icon', 'roles', or 'channels'.
    """
    payload = _filter_none({
        "name": _safe_str(name),
        **kwargs
    })
    return await discord_request("POST", "/guilds", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD(guild_id: str) -> Any:
    """
    Deletes a guild permanently. 

    WARNING: This is an irreversible action. The bot MUST be the owner of the 
    guild to perform this operation.

    Args:
        guild_id: The ID of the guild (server) to be deleted.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/guilds/{guild_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD(guild_id: str, **kwargs) -> Any:
    """
    Updates a guild's settings.

    The bot must have the 'Manage Server' permission in the guild.

    Args:
        guild_id (str): The ID of the guild (server) to update.
        **kwargs: Any other optional parameters from the Discord API documentation,
                  such as 'name', 'description', 'icon', etc. These should be
                  provided as keyword arguments.
    """
    if not kwargs:
        raise ValueError("At least one setting (e.g., name, description) must be provided to update.")

    guild_id = _validate_guild_id(guild_id)
    
    # The keyword arguments are passed directly as the payload
    payload = kwargs
    
    headers = DEFAULT_HEADERS.copy()
    if "reason" in kwargs:
        headers["X-Audit-Log-Reason"] = _safe_str(kwargs.pop("reason"))
        
    return await discord_request("PATCH", f"/guilds/{guild_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD(guild_id: str, with_counts: Optional[bool] = None) -> Any:
    """
    Retrieves detailed information about a specific guild (server).

    The bot must be a member of the guild to retrieve its information.

    Args:
        guild_id (str): The ID of the guild to retrieve.
        with_counts (Optional[bool]): When true, includes approximate member 
                                      and presence counts.
    """
    guild_id = _validate_guild_id(guild_id)
    
    # Add the with_counts parameter to the URL if requested
    if with_counts:
        return await discord_request("GET", f"/guilds/{guild_id}?with_counts=true")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_MEMBERS(guild_id: str, limit: Optional[int] = None, after: Optional[str] = None) -> Any:
    """
    Retrieves a list of members from a specific guild (server).

    NOTE: Requires the privileged 'Server Members Intent' to be enabled for your
    bot in the Discord Developer Portal.

    Args:
        guild_id (str): The ID of the guild to retrieve members from.
        limit (Optional[int]): Max number of members to return (1-1000).
        after (Optional[str]): The user ID to start fetching members after.
    """
    guild_id = _validate_guild_id(guild_id)
    
    params = {}
    if limit is not None:
        params["limit"] = limit
    if after is not None:
        params["after"] = after
        
    if params:
        query_string = urlencode(params)
        return await discord_request("GET", f"/guilds/{guild_id}/members?{query_string}")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/members")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_MEMBER(guild_id: str, user_id: str, **kwargs) -> Any:
    """
    Updates attributes of a specific guild member.

    Requires different permissions based on the action:
    - nick: MANAGE_NICKNAMES
    - roles: MANAGE_ROLES
    - mute: MUTE_MEMBERS
    - deaf: DEAFEN_MEMBERS
    - channel_id (moving): MOVE_MEMBERS
    - communication_disabled_until (timeout): MODERATE_MEMBERS

    Args:
        guild_id (str): The ID of the guild.
        user_id (str): The ID of the user to update.
        **kwargs: Fields to update, e.g., nick="NewNick", roles=["role_id_1"].
    """
    if not kwargs:
        raise ValueError("At least one attribute to update must be provided.")

    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    
    payload = kwargs

    headers = DEFAULT_HEADERS.copy()
    if "reason" in kwargs:
        headers["X-Audit-Log-Reason"] = _safe_str(kwargs.pop("reason"))
    
    return await discord_request("PATCH", f"/guilds/{guild_id}/members/{user_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_BANS(guild_id: str, limit: Optional[int] = None, before: Optional[str] = None,
                                     after: Optional[str] = None) -> Any:
    """
    Retrieves a list of banned users from a specific guild (server).

    NOTE: Requires the 'Ban Members' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve bans from.
        limit (Optional[int]): Max number of bans to return (1-1000).
        before (Optional[str]): The user ID to get bans before.
        after (Optional[str]): The user ID to get bans after.
    """
    guild_id = _validate_guild_id(guild_id)
    
    params = {}
    if limit is not None:
        params["limit"] = limit
    if before is not None:
        params["before"] = before
    if after is not None:
        params["after"] = after
        
    if params:
        query_string = urlencode(params)
        return await discord_request("GET", f"/guilds/{guild_id}/bans?{query_string}")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/bans")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_BAN(guild_id: str, user_id: str) -> Any:
    """
    Retrieves the ban information for a specific user in a guild.

    NOTE: Requires the 'Ban Members' permission.

    Args:
        guild_id (str): The ID of the guild.
        user_id (str): The ID of the user to check for a ban.
    """
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("GET", f"/guilds/{guild_id}/bans/{user_id}")

@mcp.tool()
async def DISCORDBOT_PRUNE_GUILD(guild_id: str, days: Optional[int] = None, compute_prune_count: Optional[bool] = None,
                                 include_roles: Optional[List[str]] = None, reason: Optional[str] = None) -> Any:
    """
    Kicks inactive members from a guild (server).

    NOTE: Requires the 'Kick Members' permission.

    Args:
        guild_id (str): The ID of the guild to prune.
        days (Optional[int]): Number of inactivity days before pruning (1-30).
        compute_prune_count (Optional[bool]): If true, returns the number of members
            that would be pruned without actually kicking them.
        include_roles (Optional[List[str]]): List of role IDs to restrict pruning to.
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    
    payload = {}
    if days is not None:
        payload["days"] = days
    if compute_prune_count is not None:
        payload["compute_prune_count"] = compute_prune_count
    if include_roles is not None:
        payload["include_roles"] = include_roles

    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    
    return await discord_request("POST", f"/guilds/{guild_id}/prune", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_PREVIEW_PRUNE_GUILD(guild_id: str, days: Optional[int] = None,
                                         include_roles: Optional[List[str]] = None) -> Any:
    """
    Previews the number of members that would be pruned from a guild.

    NOTE: Requires the 'Kick Members' permission. This does not kick anyone.

    Args:
        guild_id (str): The ID of the guild to preview the prune for.
        days (Optional[int]): Number of inactivity days to check (1-30).
        include_roles (Optional[List[str]]): List of role IDs to restrict the count to.
    """
    guild_id = _validate_guild_id(guild_id)
    
    params = {}
    if days is not None:
        params["days"] = days
    if include_roles is not None:
        # The API expects multiple roles to be passed as separate query params
        # e.g., ?include_roles=id1&include_roles=id2
        # aiohttp's ClientSession handles this automatically if we pass a list
        params["include_roles"] = include_roles
        
    if params:
        query_string = urlencode(params, doseq=True)
        return await discord_request("GET", f"/guilds/{guild_id}/prune?{query_string}")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/prune")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_ROLES(guild_id: str) -> Any:
    """
    Retrieves a list of all roles in a specific guild (server).

    The bot must be a member of the guild.

    Args:
        guild_id (str): The ID of the guild to retrieve roles from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/roles")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_ROLE(guild_id: str, **kwargs) -> Any:
    """
    Creates a new role in a guild.

    NOTE: Requires the 'Manage Roles' permission.

    Args:
        guild_id (str): The ID of the guild to create the role in.
        **kwargs: Optional parameters for the role, such as:
                  name, permissions, color, hoist, mentionable, position, etc.
    """
    guild_id = _validate_guild_id(guild_id)
    payload = kwargs

    # Discord expects JSON, not form data
    return await discord_request("POST", f"/guilds/{guild_id}/roles", json=payload)

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_ROLE(guild_id: str, role_id: str, **kwargs) -> Any:
    """
    Updates an existing role in a guild.

    NOTE: Requires the 'Manage Roles' permission. The bot's highest role must
    be above the role being modified.

    Args:
        guild_id (str): The ID of the guild where the role exists.
        role_id (str): The ID of the role to update.
        **kwargs: Optional parameters for the role to update, such as 'name', 
                  'permissions', 'color', etc.
    """
    if not kwargs:
        raise ValueError("At least one attribute to update (e.g., name, color) must be provided.")

    guild_id = _validate_guild_id(guild_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    
    # Pass kwargs directly as JSON payload
    payload = kwargs
    
    headers = DEFAULT_HEADERS.copy()
    if "reason" in kwargs:
        headers["X-Audit-Log-Reason"] = _safe_str(kwargs.pop("reason"))
        
    return await discord_request("PATCH", f"/guilds/{guild_id}/roles/{role_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_ROLE(guild_id: str, role_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes a role from a guild.

    NOTE: Requires the 'Manage Roles' permission.

    Args:
        guild_id (str): The ID of the guild where the role exists.
        role_id (str): The ID of the role to delete.
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/roles/{role_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LEAVE_GUILD(guild_id: str) -> Any:
    """
    Makes the bot leave a guild (server).

    Args:
        guild_id (str): The ID of the guild for the bot to leave.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/users/@me/guilds/{guild_id}")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_INVITES(guild_id: str) -> Any:
    """
    Retrieves a list of all active invite links for a specific guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve invites from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/invites")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_FROM_TEMPLATE(code: str, name: str, icon: Optional[str] = None) -> Any:
    """
    Creates a new guild from a guild template.

    NOTE: Unverified bots are limited to being in 10 guilds.

    Args:
        code (str): The code for the guild template.
        name (str): The name for the new guild (2-100 characters).
        icon (Optional[str]): A Base64 encoded 128x128 image for the guild icon.
    """
    payload = _filter_none({
        "name": _safe_str(name),
        "icon": icon
    })
    return await discord_request("POST", f"/guilds/templates/{code}", json=payload)

@mcp.tool()
async def DISCORDBOT_SYNC_GUILD_TEMPLATE(guild_id: str, code: str) -> Any:
    """
    Synchronizes a guild template with its source guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the source guild.
        code (str): The code of the template to sync.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("PUT", f"/guilds/{guild_id}/templates/{code}")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_TEMPLATE(code: str) -> Any:
    """
    Retrieves information about a guild template.

    Args:
        code (str): The unique code of the guild template.
    """
    return await discord_request("GET", f"/guilds/templates/{code}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_TEMPLATE(guild_id: str, code: str, name: str, description: str) -> Any:
    """
    Updates a guild template's metadata (name and/or description).

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild where the template exists.
        code (str): The code of the template to update.
        name (Optional[str]): The new name for the template.
        description (Optional[str]): The new description for the template.
    """
    if name is None and description is None:
        raise ValueError("At least one attribute (name or description) must be provided.")

    guild_id = _validate_guild_id(guild_id)
    
    payload = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
        
    return await discord_request("PATCH", f"/guilds/{guild_id}/templates/{code}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_TEMPLATE(guild_id: str, code: str) -> Any:
    """
    Deletes a guild template.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild where the template exists.
        code (str): The code of the template to delete.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/guilds/{guild_id}/templates/{code}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_TEMPLATE(guild_id: str, name: str, description: str) -> Any:
    """
    Creates a new guild template from an existing guild's structure.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to create the template from.
        name (str): The name for the new template (1-100 characters).
        description (Optional[str]): The description for the template (0-120 characters).
    """
    guild_id = _validate_guild_id(guild_id)
    
    payload = {
        "name": name,
    }
    if description is not None:
        payload["description"] = description
        
    return await discord_request("POST", f"/guilds/{guild_id}/templates", json=payload)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_TEMPLATES(guild_id: str) -> Any:
    """
    Retrieves a list of all guild templates for a specific guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve templates from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/templates")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_PREVIEW(guild_id: str) -> Any:
    """
    Retrieves a public preview of a guild.

    The bot does not need to be a member of the guild for this to work,
    but the guild must be discoverable.

    Args:
        guild_id (str): The ID of the guild to preview.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/preview")

@mcp.tool()
async def DISCORDBOT_GET_GUILDS_ONBOARDING(guild_id: str) -> Any:
    """
    Retrieves the onboarding configuration for a specific guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve the onboarding settings from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/onboarding")

@mcp.tool()
async def DISCORDBOT_PUT_GUILDS_ONBOARDING(guild_id: str, prompts: Optional[List[Dict]] = None,
                                           default_channel_ids: Optional[List[str]] = None,
                                           enabled: bool = True, mode: int = 0, reason: Optional[str] = None) -> Any:
    """
    Updates a guild's onboarding configuration. Replaces the entire configuration.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to update.
        prompts (Optional[List[Dict]]): The list of onboarding prompt objects. If None, uses empty list.
        default_channel_ids (Optional[List[str]]): The list of default channel IDs. If None, uses empty list.
        enabled (bool): Whether onboarding is enabled.
        mode (int): The onboarding mode (must be 0 for now).
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    
    # Handle None values and ensure proper types
    prompts_list = prompts if prompts is not None else []
    channel_ids_list = default_channel_ids if default_channel_ids is not None else []
    
    payload = {
        "prompts": prompts_list,
        "default_channel_ids": channel_ids_list,
        "enabled": enabled,
        "mode": mode
    }
    
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
        
    return await discord_request("PUT", f"/guilds/{guild_id}/onboarding", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WIDGET(guild_id: str) -> Any:
    """
    Retrieves the widget object for a given guild.

    NOTE: The guild widget must be enabled in Server Settings for this to work.

    Args:
        guild_id (str): The ID of the guild to retrieve the widget for.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/widget.json")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WIDGET_SETTINGS(guild_id: str) -> Any:
    """
    Retrieves the widget settings for a specific guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to get widget settings for.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/widget")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_WIDGET_SETTINGS(guild_id: str, enabled: Optional[bool] = None,
                                                   channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """
    Updates the widget settings for a specific guild to point to a non-default channel.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to update the widget settings for.
        channel_id (str): The ID of the channel to use for the widget.
        enabled (bool): Whether the widget is enabled (default True).
        reason: Optional reason for audit log.
    """
    if enabled is None and channel_id is None:
        raise ValueError("At least one setting (enabled or channel_id) must be provided.")

    guild_id = _validate_guild_id(guild_id)
    
    payload = {}
    if enabled is not None:
        payload["enabled"] = enabled
    if channel_id is not None:
        payload["channel_id"] = channel_id
    
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
        
    return await discord_request("PATCH", f"/guilds/{guild_id}/widget", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WELCOME_SCREEN(guild_id: str) -> Any:
    """
    Retrieves the welcome screen configuration for a guild.

    NOTE: Requires the 'Manage Server' permission. The guild must also
    have the Welcome Screen feature enabled.

    Args:
        guild_id (str): The ID of the guild to retrieve the welcome screen from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/welcome-screen")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_WELCOME_SCREEN(guild_id: str, enabled: Optional[bool] = None,
                                                welcome_channels: Optional[List[Dict]] = None,
                                                description: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """
    Updates the welcome screen for a guild.

    NOTE: Requires the 'Manage Server' permission. The guild must have the
    Welcome Screen feature enabled (be a Community server).

    Args:
        guild_id (str): The ID of the guild to update the welcome screen for.
        enabled (Optional[bool]): Whether the welcome screen is enabled.
        welcome_channels (Optional[List[Dict]]): Array of welcome channel objects.
        description (Optional[str]): The server description shown in the welcome screen.
        reason: Optional reason for audit log.
    """
    if enabled is None and welcome_channels is None and description is None:
        raise ValueError("At least one field (enabled, welcome_channels, or description) must be provided.")

    guild_id = _validate_guild_id(guild_id)
    
    payload = {}
    if enabled is not None:
        payload["enabled"] = enabled
    if welcome_channels is not None:
        payload["welcome_channels"] = welcome_channels
    if description is not None:
        payload["description"] = description
    
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
        
    return await discord_request("PATCH", f"/guilds/{guild_id}/welcome-screen", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_VANITY_URL(guild_id: str) -> Any:
    """
    Retrieves the vanity URL information for a specific guild.

    NOTE: Requires the 'Manage Server' permission. The guild must have a
    vanity URL set (usually through Server Boosting).

    Args:
        guild_id (str): The ID of the guild to retrieve the vanity URL from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/vanity-url")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str, with_user_count: Optional[bool] = None) -> Any:
    """
    Retrieves a specific scheduled event from a guild.

    The bot must be a member of the guild.

    Args:
        guild_id (str): The ID of the guild where the event exists.
        guild_scheduled_event_id (str): The ID of the scheduled event to retrieve.
        with_user_count (Optional[bool]): If true, includes the number of subscribed users.
    """
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    
    if with_user_count:
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}?with_user_count=true")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_SCHEDULED_EVENT(guild_id: str, name: str, privacy_level: int,
                                                  scheduled_start_time: str, entity_type: int,
                                                  channel_id: str, description: str,
                                                  scheduled_end_time: str, location: Optional[str] = None,
                                                  image: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """
    Creates a new scheduled event in a guild.

    NOTE: Requires the 'Manage Events' permission. Depending on the event
    type, other permissions like 'Manage Channels' may be needed.

    Args:
        guild_id (str): The ID of the guild to create the event in.
        name (str): The name of the event.
        privacy_level (int): Privacy level (1 = Guild Only, 2 = Public).
        scheduled_start_time (str): ISO 8601 timestamp for start time.
        entity_type (int): Event type (1 = Stage, 2 = Voice, 3 = External).
        channel_id (Optional[str]): Channel ID for voice/stage events.
        description (Optional[str]): Event description.
        scheduled_end_time (Optional[str]): ISO 8601 timestamp for end time.
        location (Optional[str]): Location for external events.
        image (Optional[str]): Base64 encoded image data.
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    
    payload = {
        "name": name,
        "privacy_level": privacy_level,
        "scheduled_start_time": scheduled_start_time,
        "entity_type": entity_type
    }
    
    if channel_id is not None:
        payload["channel_id"] = channel_id
    if description is not None:
        payload["description"] = description
    if scheduled_end_time is not None:
        payload["scheduled_end_time"] = scheduled_end_time
    if location is not None:
        payload["location"] = location
    if image is not None:
        payload["image"] = image
    
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
        
    return await discord_request("POST", f"/guilds/{guild_id}/scheduled-events", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str,
                                                  **kwargs) -> Any:
    """
    Updates a guild's scheduled event.

    NOTE: Requires the 'Manage Events' permission.

    Args:
        guild_id (str): The ID of the guild where the event exists.
        guild_scheduled_event_id (str): The ID of the event to update.
        **kwargs: Fields to update, e.g., name="New Event Name",
                  description="Updated info.", status=2 (to start).
    """
    if not kwargs:
        raise ValueError("At least one attribute to update (e.g., name, status) must be provided.")

    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    
    # The keyword arguments are passed directly as the payload
    payload = kwargs
    
    headers = DEFAULT_HEADERS.copy()
    if "reason" in kwargs:
        headers["X-Audit-Log-Reason"] = _safe_str(kwargs.pop("reason"))
        
    return await discord_request("PATCH", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes a guild scheduled event.

    NOTE: Requires the 'Manage Events' permission.

    Args:
        guild_id (str): The ID of the guild where the event exists.
        guild_scheduled_event_id (str): The ID of the event to delete.
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_SCHEDULED_EVENTS(guild_id: str, with_user_count: Optional[bool] = None) -> Any:
    """
    Retrieves a list of scheduled events for a guild.

    The bot must be a member of the guild.

    Args:
        guild_id (str): The ID of the guild to retrieve events from.
        with_user_count (Optional[bool]): If true, includes the number of subscribed users.
    """
    guild_id = _validate_guild_id(guild_id)
    
    if with_user_count:
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events?with_user_count=true")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_SCHEDULED_EVENT_USERS(guild_id: str, guild_scheduled_event_id: str,
                                                      limit: Optional[int] = None, with_member: Optional[bool] = None,
                                                      before: Optional[str] = None, after: Optional[str] = None) -> Any:
    """
    Retrieves a list of users subscribed to a guild scheduled event.

    The bot must be a member of the guild.

    Args:
        guild_id (str): The ID of the guild where the event exists.
        guild_scheduled_event_id (str): The ID of the scheduled event.
        limit (Optional[int]): Max number of users to return (1-100).
        with_member (Optional[bool]): If true, includes guild member data.
        before (Optional[str]): The user ID to start fetching users before.
        after (Optional[str]): The user ID to start fetching users after.
    """
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    
    params = {}
    if limit is not None:
        params["limit"] = limit
    if with_member is not None:
        params["with_member"] = with_member
    if before is not None:
        params["before"] = before
    if after is not None:
        params["after"] = after
        
    if params:
        query_string = urlencode(params)
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}/users?{query_string}")
    else:
        return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}/users")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_VOICE_REGIONS(guild_id: str) -> Any:
    """
    Retrieves a list of voice regions available for a guild.

    The bot must be a member of the guild.

    Args:
        guild_id (str): The ID of the guild to retrieve voice regions for.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/regions")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_INTEGRATIONS(guild_id: str) -> Any:
    """
    Retrieves a list of integrations for a guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild to retrieve integrations from.
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/integrations")

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_INTEGRATION(guild_id: str, integration_id: str, reason: Optional[str] = None) -> Any:
    """
    Deletes an integration from a guild.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        guild_id (str): The ID of the guild where the integration exists.
        integration_id (str): The ID of the integration to delete.
        reason: Optional reason for audit log.
    """
    guild_id = _validate_guild_id(guild_id)
    integration_id = _validate_snowflake(integration_id, "Integration ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/integrations/{integration_id}", headers=headers)

# ---------------- INVITES & TEMPLATES (8 tools) ----------------
@mcp.tool()
async def DISCORDBOT_INVITE_RESOLVE(invite_code: str, with_counts: Optional[bool] = None,
                                   with_expiration: Optional[bool] = None, guild_scheduled_event_id: Optional[str] = None) -> Any:
    """
    Retrieves an invite object for the given invite code.

    Args:
        invite_code (str): The invite code to resolve.
        with_counts (Optional[bool]): Whether to include approximate member counts.
        with_expiration (Optional[bool]): Whether to include expiration date.
        guild_scheduled_event_id (Optional[str]): The scheduled event ID to include.

    Returns:
        dict: Invite object containing invite details.
    """
    params = _filter_none({
        "with_counts": with_counts,
        "with_expiration": with_expiration,
        "guild_scheduled_event_id": guild_scheduled_event_id
    })
    return await discord_request("GET", f"/invites/{invite_code}", params=params)

@mcp.tool()
async def DISCORDBOT_INVITE_REVOKE(invite_code: str, reason: Optional[str] = None) -> Any:
    """
    Deletes an invite.

    NOTE: Requires the 'Manage Server' permission.

    Args:
        invite_code (str): The invite code to delete.
        reason: Optional reason for audit log.

    Returns:
        dict: Confirmation of deletion.
    """
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/invites/{invite_code}", headers=headers)

# ---------------- MISCELLANEOUS / UTILITY (4 tools) ----------------

@mcp.tool()
async def DISCORDBOT_LIST_VOICE_REGIONS() -> Any:
    """
    Lists all available voice regions in Discord.

    Returns:
        dict containing:
            - data: list of voice region objects with properties id, name, custom, deprecated, optimal
            - successful: bool
            - error: str if any error occurred
    """
    return await discord_request("GET", "/voice/regions")

@mcp.tool()
async def DISCORDBOT_CREATE_DM(recipient_id: str = None, access_tokens: list = None, nicks: dict = None) -> Any:
    """
    Creates a DM channel with a single user or a group DM.

    Parameters:
        recipient_id (str, optional): The User ID for a 1-on-1 DM. Use this OR `access_tokens`.
        access_tokens (list, optional): OAuth2 tokens for multiple users in a group DM (1–9 others). Use this OR `recipient_id`.
        nicks (dict, optional): Custom nicknames for group DM users. Only used with `access_tokens`.

    Returns:
        dict: Contains 'data' (DM channel object), 'successful' (bool), 'error' (str if any)
    """
    payload = {}
    if recipient_id:
        recipient_id = _validate_user_id(recipient_id)
        payload["recipient_id"] = recipient_id
    if access_tokens:
        payload["access_tokens"] = access_tokens
    if nicks:
        payload["nicks"] = nicks

    return await discord_request("POST", "/users/@me/channels", json=payload)

@mcp.tool()
async def DISCORDBOT_VIEW_DM_MEMBERS(channel_id: str) -> Any:
    """
    Views the members/recipients in a Discord DM or group DM channel.

    Parameters:
        channel_id (str): The ID of the DM or group DM channel.

    Returns:
        dict: Contains channel information including recipients/members
    """
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}")

@mcp.tool()
async def DISCORDBOT_CREATE_GROUP_DM_USER(access_tokens: List[str], nicks: Optional[Dict[str, str]] = None) -> Any:
    """Create a new group DM channel with multiple users."""
    payload = _filter_none({
        "access_tokens": _safe_list(access_tokens),
        "nicks": _safe_dict(nicks)
    })
    return await discord_request("POST", "/users/@me/channels", json=payload)

# ---------------- MAIN EXECUTION ----------------

if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        raise
