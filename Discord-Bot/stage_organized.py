import os
import json
import asyncio
import time
from typing import Optional, List, Dict, Any, Union, IO, BinaryIO
from urllib.parse import quote_plus
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
    """Remove None values from dict."""
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
    """Create a new global application command.
    
    Parameters:
    - application_id: ID of the application (required)
    - name: Name of the command (required) - must be lowercase, 1-32 chars, letters/numbers/underscores only
    - description: Description of the command (required)
    - type: Type of command (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT
        * 2 = USER
        * 3 = MESSAGE
    - options: JSON string of command options
    - default_member_permissions: JSON string of default member permissions
    - dm_permission: Whether the command can be used in DMs (default: true)
    - nsfw: Whether the command is NSFW (default: false)
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
    """Delete a global application command.
    
    Parameters:
    - application_id: ID of the application that owns the command (required)
    - command_id: ID of the command to delete (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
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
    """Update a global application command.
    
    Parameters:
    - application_id: ID of the application (required)
    - command_id: ID of the command to update (required)
    - name: New name for the command
    - description: New description for the command
    - type: New type of command (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT
        * 2 = USER
        * 3 = MESSAGE
    - options: JSON string of command options
    - default_member_permissions: JSON string of default member permissions
    - dm_permission: Whether the command can be used in DMs (default: true)
    - nsfw: Whether the command is NSFW (default: false)
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
    
    Parameters:
    - application_id: ID of the application to fetch commands for (required)
    - with_localizations: Whether to include localizations in the response (optional)
    
    Returns:
    - list: List of application command objects, or error information if failed
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    params = _filter_none({
        "with_localizations": with_localizations
    })
    return await discord_request("GET", f"/applications/{application_id}/commands", params=params)

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION_COMMAND(application_id: str, command_id: str) -> Any:
    """Fetch a global application command.
    
    Parameters:
    - application_id: ID of the application that owns the command (required)
    - command_id: ID of the command to fetch (required)
    
    Returns:
    - dict: Application command object on success, or error information if failed
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("GET", f"/applications/{application_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_APPLICATION_COMMAND(application_id: str, guild_id: str, name: str, description: str,
                                                      type: int = 1, options: str = "",
                                                      default_member_permissions: str = "", dm_permission: bool = True,
                                                      nsfw: bool = False) -> Any:
    """Create a new guild application command.
    
    Parameters:
    - application_id: ID of the application (required)
    - guild_id: ID of the guild where the command will be created (required)
    - name: Name of the command (required) - must be lowercase, 1-32 chars, letters/numbers/underscores only
    - description: Description of the command (required)
    - type: Type of command (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT
        * 2 = USER
        * 3 = MESSAGE
    - options: JSON string of command options
    - default_member_permissions: JSON string of default member permissions
    - dm_permission: Whether the command can be used in DMs (default: true)
    - nsfw: Whether the command is NSFW (default: false)
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
    """Delete a guild application command.
    
    Parameters:
    - application_id: ID of the application that owns the command (required)
    - guild_id: ID of the guild where the command exists (required)
    - command_id: ID of the command to delete (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
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
    """Update a guild application command.
    
    Parameters:
    - application_id: ID of the application (required)
    - guild_id: ID of the guild where the command is located (required)
    - command_id: ID of the command to update (required)
    - name: New name for the command
    - description: New description for the command
    - type: New type of command (default: 1 = CHAT_INPUT)
        * 1 = CHAT_INPUT
        * 2 = USER
        * 3 = MESSAGE
    - options: JSON string of command options
    - default_member_permissions: JSON string of default member permissions
    - dm_permission: Whether the command can be used in DMs (default: true)
    - nsfw: Whether the command is NSFW (default: false)
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
    """Fetch a guild application command.
    
    Parameters:
    - application_id: ID of the application that owns the command (required)
    - guild_id: ID of the guild where the command exists (required)
    - command_id: ID of the command to fetch (required)
    
    Returns:
    - dict: Guild application command object on success, or error information if failed
    """
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    command_id = _validate_snowflake(command_id, "Command ID")
    return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands/{command_id}")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_APPLICATION_COMMANDS(application_id: str, guild_id: str, with_localizations: bool = False) -> Any:
    """Fetch all guild commands for an application.
    
    Parameters:
    - application_id: ID of the application (required)
    - guild_id: ID of the guild (required)
    - with_localizations: Whether to include localization data (default: false)
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
    
    Parameters:
    - application_id: ID of the application that owns the command (required)
    - guild_id: ID of the guild where the command exists (required)
    - command_id: ID of the command to get permissions for (required)
    
    Returns:
    - dict: Command permissions object on success, or error information if failed
    
    Note: Returns 404 if the command doesn't exist in the guild or has no permissions set.
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
    """Get all permissions for all commands in a guild."""
    application_id = _validate_snowflake(application_id, "Application ID")
    guild_id = _validate_guild_id(guild_id)
    try:
        return await discord_request("GET", f"/applications/{application_id}/guilds/{guild_id}/commands/permissions")
    except Exception as e:
        return _handle_discord_error(e, "guild command permissions", guild_id=guild_id)

@mcp.tool()
async def DISCORDBOT_GET_APPLICATION(application_id: str) -> Any:
    """Get information about an application."""
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
    """Update an application.
    
    Parameters:
    - application_id: ID of the application to update (required)
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
    """Get information about the current application."""
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
    """Get a channel by ID.
    
    Parameters:
    - channel_id: ID of the channel to retrieve (required)
    
    Returns:
    - dict: Channel object on success, or error information if failed
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
    """Create a new channel for the guild.
    
    Parameters:
    - guild_id: ID of the guild where the channel will be created (required)
    - name: Name of the channel (required)
    - type: Type of channel (default: 0 = TEXT)
        * 0 = TEXT
        * 2 = VOICE
        * 4 = CATEGORY
        * 5 = ANNOUNCEMENT
        * 13 = STAGE
        * 15 = FORUM
    - topic: Topic of the channel
    - bitrate: Bitrate for voice channels (8000-128000)
    - user_limit: User limit for voice channels (0 = no limit)
    - rate_limit_per_user: Slowmode delay in seconds
    - position: Position of the channel
    - permission_overwrites: JSON string of permission overwrites
    - parent_id: ID of the parent category
    - nsfw: Whether the channel is NSFW
    - rtc_region: Voice region for the channel
    - video_quality_mode: Video quality mode for voice channels
    - default_auto_archive_duration: Default auto-archive duration for threads
    - available_tags: JSON string of available tags for forum channels
    - default_reaction_emoji: JSON string of default reaction emoji
    - default_thread_rate_limit_per_user: Default thread slowmode
    - default_sort_order: Default sort order for forum channels
    - reason: Reason for creating the channel (for audit logs)
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
    """Update a channel's settings.
    
    Parameters:
    - channel_id: ID of the channel to update (required)
    - name: New name for the channel
    - type: New type of channel (default: 0 = TEXT)
    - position: New position of the channel
    - topic: New topic of the channel
    - nsfw: Whether the channel is NSFW
    - rate_limit_per_user: Slowmode delay in seconds
    - bitrate: Bitrate for voice channels (8000-128000)
    - user_limit: User limit for voice channels (0 = no limit)
    - permission_overwrites: JSON string of permission overwrites
    - parent_id: ID of the parent category
    - rtc_region: Voice region for the channel
    - video_quality_mode: Video quality mode for voice channels
    - default_auto_archive_duration: Default auto-archive duration for threads
    - flags: Channel flags
    - available_tags: JSON string of available tags for forum channels
    - default_reaction_emoji: JSON string of default reaction emoji
    - default_thread_rate_limit_per_user: Default thread slowmode
    - default_sort_order: Default sort order for forum channels
    - reason: Reason for updating the channel (for audit logs)
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
    """Delete a channel.
    
    Parameters:
    - channel_id: ID of the channel to delete (required)
    
    Returns:
    - dict: Channel object on success, or error information if failed
    
    Note: This action cannot be undone. The channel will be permanently deleted.
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
    """Returns a list of guild channel objects.
    
    Parameters:
    - guild_id: ID of the guild to list channels from (required)
    
    Returns:
    - list: List of channel objects, or error information if failed
    """
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/channels")

@mcp.tool()
async def DISCORDBOT_CREATE_CHANNEL_INVITE(channel_id: str, max_age: int = 0, max_uses: int = 0,
                                           temporary: bool = False, unique: bool = False,
                                           target_type: int = 0, target_user_id: str = "",
                                           target_application_id: str = "", reason: str = "") -> Any:
    """Create a new invite for a channel.
    
    Parameters:
    - channel_id: ID of the channel to create invite for (required)
    - max_age: Duration of invite in seconds (0 = never expires)
    - max_uses: Number of times invite can be used (0 = unlimited)
    - temporary: Whether invite grants temporary membership
    - unique: Whether invite should be unique
    - target_type: Type of target for invite (0 = none, 1 = stream, 2 = embedded application)
    - target_user_id: ID of user whose stream to display
    - target_application_id: ID of embedded application to open
    - reason: Reason for creating the invite (for audit logs)
    """
    channel_id = _validate_channel_id(channel_id)
    payload = _filter_none({
        "max_age": max_age if max_age > 0 else None,
        "max_uses": max_uses if max_uses > 0 else None,
        "temporary": temporary,
        "unique": unique,
        "target_type": target_type if target_type > 0 else None,
        "target_user_id": target_user_id if target_user_id else None,
        "target_application_id": target_application_id if target_application_id else None
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/channels/{channel_id}/invites", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_CHANNEL_INVITES(channel_id: str) -> Any:
    """Returns a list of invite objects (with invite metadata) for the channel.
    
    Parameters:
    - channel_id: ID of the channel to list invites for (required)
    
    Returns:
    - list: List of invite objects, or error information if failed
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
    """Follow a News Channel to send messages to a target channel.
    
    Parameters:
    - channel_id: ID of the news channel to follow (required)
    - webhook_channel_id: ID of the target channel to send messages to (required)
    
    Returns:
    - dict: Followed channel object on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    webhook_channel_id = _validate_channel_id(webhook_channel_id)
    payload = {
        "webhook_channel_id": webhook_channel_id
    }
    return await discord_request("POST", f"/channels/{channel_id}/followers", json=payload)

@mcp.tool()
async def DISCORDBOT_TRIGGER_TYPING_INDICATOR(channel_id: str) -> Any:
    """Post a typing indicator for the specified channel.
    
    Parameters:
    - channel_id: ID of the channel to show typing indicator in (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
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
    """Get the gateway URL and recommended number of shards."""
    return await discord_request("GET", "/gateway")

@mcp.tool()
async def DISCORDBOT_GET_BOT_GATEWAY() -> Any:
    """Get the gateway URL and recommended number of shards for the bot."""
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
    
    Parameters:
    - channel_id: ID of the target channel (required)
    - content: Message text (max 2000 chars)
    - nonce: Unique integer to confirm message sending
    - tts: Send as text-to-speech message
    - embeds: JSON string of embed objects (max 10, 6000 chars total)
    - allowed_mentions: JSON string for mention controls
    - message_reference: JSON string for replying to messages
    - components: JSON string of message components (buttons, select menus)
    - sticker_ids: JSON string of sticker IDs (max 3)
    - files: JSON string of file paths for uploads
    - attachments: JSON string of attachment objects
    - flags: Bitwise value for message flags
    - poll: JSON string of poll object
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
    """Returns a specific message in the channel.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to retrieve (required)
    
    Returns:
    - dict: Message object on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    return await discord_request("GET", f"/channels/{channel_id}/messages/{message_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_MESSAGE(channel_id: str, message_id: str, content: str = "",
                                   embeds: str = "", flags: int = 0, allowed_mentions: str = "",
                                   components: str = "", attachments: str = "", sticker_ids: str = "") -> Any:
    """Updates a message previously sent by the bot in a discord channel.
    
    Parameters:
    - channel_id: ID of the channel where the message is located (required)
    - message_id: ID of the message to update (required)
    - content: New message content (up to 2000 chars). Set to empty string to remove.
    - embeds: JSON string of embed objects (max 10). Set to empty string to remove all.
    - flags: Message flags to set (e.g., 4 for SUPPRESS_EMBEDS)
    - allowed_mentions: JSON string for mention controls. Set to empty string for default.
    - components: JSON string of message components (buttons, select menus). Set to empty string to remove.
    - attachments: JSON string of attachment objects to keep/update metadata. Set to empty string to remove.
    - sticker_ids: JSON string of sticker IDs (max 3). Set to empty string to remove.
    
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
    """Delete a message.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to delete (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    
    Note: Can only delete messages sent by the bot or messages less than 2 weeks old.
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("DELETE", f"/channels/{channel_id}/messages/{message_id}")

@mcp.tool()
async def DISCORDBOT_LIST_MESSAGES(channel_id: str, around: str = "", before: str = "",
                                  after: str = "", limit: int = 50) -> Any:
    """Returns the messages for a channel.
    
    Parameters:
    - channel_id: ID of the channel to get messages from (required)
    - around: Get messages around this message ID
    - before: Get messages before this message ID
    - after: Get messages after this message ID
    - limit: Max number of messages to return (0-100, default: 50)
    
    Returns:
    - list: List of message objects, or error information if failed
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
    """Unpin a message in a channel.
    
    Parameters:
    - channel_id: ID of the channel containing the message (required)
    - message_id: ID of the message to unpin (required)
    
    Returns:
    - dict: Empty response on success, or error information if failed
    """
    channel_id = _validate_channel_id(channel_id)
    message_id = _validate_message_id(message_id)
    headers = DEFAULT_HEADERS.copy()
    return await discord_request("DELETE", f"/channels/{channel_id}/pins/{message_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_PINNED_MESSAGES(channel_id: str) -> Any:
    """Returns all pinned messages in the channel.
    
    Parameters:
    - channel_id: ID of the channel to get pinned messages from (required)
    
    Returns:
    - list: List of pinned message objects, or error information if failed
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
    """Crosspost a message in a News Channel to following channels.
    
    Parameters:
    - channel_id: ID of the news channel containing the message (required)
    - message_id: ID of the message to crosspost (required)
    
    Returns:
    - dict: Message object on success, or error information if failed
    
    Note: Only works in news channels. The message must be published first.
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
    """Create a guild ban.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user to ban (required)
    - delete_message_seconds: Number of seconds to delete messages (0 = don't delete)
    - reason: Reason for banning the user (for audit logs)
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
    """Remove the ban for a user.
    
    Parameters:
    - guild_id: ID of the guild (required)
    - user_id: ID of the user to unban (required)
    - reason: Reason for unbanning the user (for audit logs)
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
    """Returns a user object for a given user ID.
    
    Parameters:
    - user_id: ID of the user to retrieve (required)
    
    Returns:
    - dict: User object on success, or error information if failed
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
    """Returns a guild member object for the specified user.
    
    Parameters:
    - guild_id: ID of the guild to get member from (required)
    - user_id: ID of the user to get guild member info for (required)
    
    Returns:
    - dict: Guild member object on success, or error information if failed
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
async def DISCORDBOT_CREATE_GUILD_EMOJI(guild_id: str, name: str, image: str, roles: Optional[List[str]] = None,
                                        reason: Optional[str] = None) -> Any:
    """Create a new emoji for the guild."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "image": image,
        "roles": _safe_list(roles)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/emojis", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_EMOJI(guild_id: str, emoji_id: str) -> Any:
    """Returns an emoji object for the given guild and emoji IDs."""
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    return await discord_request("GET", f"/guilds/{guild_id}/emojis/{emoji_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_EMOJI(guild_id: str, emoji_id: str, name: Optional[str] = None,
                                        roles: Optional[List[str]] = None, reason: Optional[str] = None) -> Any:
    """Modify the given emoji."""
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "roles": _safe_list(roles)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/emojis/{emoji_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_EMOJI(guild_id: str, emoji_id: str, reason: Optional[str] = None) -> Any:
    """Delete the given emoji."""
    guild_id = _validate_guild_id(guild_id)
    emoji_id = _validate_snowflake(emoji_id, "Emoji ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/emojis/{emoji_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_EMOJIS(guild_id: str) -> Any:
    """Returns a list of emoji objects for the given guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/emojis")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_STICKER(guild_id: str, name: str, description: str, tags: str,
                                          file: Union[str, BinaryIO], reason: Optional[str] = None) -> Any:
    """Create a new sticker for the guild."""
    guild_id = _validate_guild_id(guild_id)
    payload = {
        "name": _safe_str(name),
        "description": _safe_str(description),
        "tags": _safe_str(tags)
    }
    
    # Handle file upload
    if isinstance(file, str):
        if not os.path.exists(file):
            raise FileNotFoundError(f"File not found: {file}")
        with open(file, "rb") as f:
            files = {"file": (os.path.basename(file), f)}
            headers = DEFAULT_HEADERS.copy()
            if reason:
                headers["X-Audit-Log-Reason"] = _safe_str(reason)
            headers.pop("Content-Type", None)  # Remove for multipart
            return await discord_request("POST", f"/guilds/{guild_id}/stickers", data=payload, files=files, headers=headers)
    else:
        files = {"file": ("sticker.png", file)}
        headers = DEFAULT_HEADERS.copy()
        if reason:
            headers["X-Audit-Log-Reason"] = _safe_str(reason)
        headers.pop("Content-Type", None)  # Remove for multipart
        return await discord_request("POST", f"/guilds/{guild_id}/stickers", data=payload, files=files, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_STICKER(guild_id: str, sticker_id: str) -> Any:
    """Returns a sticker object for the given guild and sticker IDs."""
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    return await discord_request("GET", f"/guilds/{guild_id}/stickers/{sticker_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_STICKER(guild_id: str, sticker_id: str, name: Optional[str] = None,
                                          description: Optional[str] = None, tags: Optional[str] = None,
                                          reason: Optional[str] = None) -> Any:
    """Modify the given sticker."""
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "description": _safe_str(description),
        "tags": _safe_str(tags)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/stickers/{sticker_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_STICKER(guild_id: str, sticker_id: str, reason: Optional[str] = None) -> Any:
    """Delete the given sticker."""
    guild_id = _validate_guild_id(guild_id)
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/stickers/{sticker_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_STICKERS(guild_id: str) -> Any:
    """Returns a list of sticker objects for the given guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/stickers")

@mcp.tool()
async def DISCORDBOT_LIST_STICKER_PACKS() -> Any:
    """Returns the list of sticker packs available to Nitro subscribers."""
    return await discord_request("GET", "/sticker-packs")

@mcp.tool()
async def DISCORDBOT_GET_STICKER(sticker_id: str) -> Any:
    """Returns a sticker object for the given sticker ID."""
    sticker_id = _validate_snowflake(sticker_id, "Sticker ID")
    return await discord_request("GET", f"/stickers/{sticker_id}")

# ---------------- WEBHOOK MANAGEMENT (17 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_WEBHOOK(channel_id: str, name: str, avatar: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Create a new webhook.
    
    Parameters:
    - channel_id: ID of the channel to create webhook in (required)
    - name: Name of the webhook (required)
    - avatar: Avatar image data (base64 encoded, optional)
    - reason: Reason for creating the webhook (for audit logs, optional)
    
    Returns:
    - dict: Webhook object on success, or error information if failed
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
    """Returns the new webhook object for the given id."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    return await discord_request("GET", f"/webhooks/{webhook_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_WEBHOOK(webhook_id: str, name: Optional[str] = None, avatar: Optional[str] = None,
                                    channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Modify a webhook."""
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
    """Delete a webhook permanently."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/webhooks/{webhook_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str) -> Any:
    """Returns the new webhook object for the given id."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    return await discord_request("GET", f"/webhooks/{webhook_id}/{webhook_token}")

@mcp.tool()
async def DISCORDBOT_UPDATE_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str, name: Optional[str] = None,
                                             avatar: Optional[str] = None, channel_id: Optional[str] = None) -> Any:
    """Modify a webhook."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "avatar": avatar,
        "channel_id": channel_id
    })
    return await discord_request("PATCH", f"/webhooks/{webhook_id}/{webhook_token}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_WEBHOOK_BY_TOKEN(webhook_id: str, webhook_token: str) -> Any:
    """Delete a webhook permanently."""
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
    """Execute a webhook with the specified parameters."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    payload = _filter_none({
        "content": _safe_str(content),
        "username": _safe_str(username),
        "avatar_url": avatar_url,
        "tts": tts,
        "embeds": _safe_list(embeds),
        "allowed_mentions": _safe_dict(allowed_mentions),
        "components": _safe_list(components),
        "payload_json": payload_json,
        "attachments": _safe_list(attachments),
        "flags": flags,
        "thread_name": _safe_str(thread_name),
        "wait": wait
    })
    
    if files:
        multipart_data = await _handle_file_upload(files, payload)
        return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}", data=multipart_data)
    else:
        return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}", json=payload)

@mcp.tool()
async def DISCORDBOT_EXECUTE_SLACK_COMPATIBLE_WEBHOOK(webhook_id: str, webhook_token: str, payload: Dict[str, Any],
                                                      wait: Optional[bool] = None, thread_id: Optional[str] = None) -> Any:
    """Execute a webhook in Slack-compatible mode."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "wait": wait,
        "thread_id": thread_id
    })
    return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}/slack", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_EXECUTE_GITHUB_COMPATIBLE_WEBHOOK(webhook_id: str, webhook_token: str, payload: Dict[str, Any],
                                                       wait: Optional[bool] = None, thread_id: Optional[str] = None) -> Any:
    """Execute a webhook in GitHub-compatible mode."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "wait": wait,
        "thread_id": thread_id
    })
    return await discord_request("POST", f"/webhooks/{webhook_id}/{webhook_token}/github", json=payload, params=params)

@mcp.tool()
async def DISCORDBOT_GET_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, message_id: str, thread_id: Optional[str] = None) -> Any:
    """Returns a previously-sent webhook message from the same token."""
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
    """Edits a previously-sent webhook message from the same token."""
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
    """Deletes a message that was created by the webhook."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    message_id = _validate_message_id(message_id)
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("DELETE", f"/webhooks/{webhook_id}/{webhook_token}/messages/{message_id}", params=params)

@mcp.tool()
async def DISCORDBOT_GET_ORIGINAL_WEBHOOK_MESSAGE(webhook_id: str, webhook_token: str, thread_id: Optional[str] = None) -> Any:
    """Returns the original message that was created by the webhook."""
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
    """Edits the original message that was created by the webhook."""
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
    """Deletes the original message that was created by the webhook."""
    webhook_id = _validate_snowflake(webhook_id, "Webhook ID")
    params = _filter_none({
        "thread_id": thread_id
    })
    return await discord_request("DELETE", f"/webhooks/{webhook_id}/{webhook_token}/messages/@original", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_CHANNEL_WEBHOOKS(channel_id: str) -> Any:
    """Returns a list of channel webhook objects."""
    channel_id = _validate_channel_id(channel_id)
    return await discord_request("GET", f"/channels/{channel_id}/webhooks")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WEBHOOKS(guild_id: str) -> Any:
    """Returns a list of guild webhook objects."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/webhooks")

# ---------------- GUILD MANAGEMENT (46 tools) ----------------
@mcp.tool()
async def DISCORDBOT_CREATE_GUILD(name: str, region: Optional[str] = None, icon: Optional[str] = None,
                                  verification_level: Optional[int] = None, default_message_notifications: Optional[int] = None,
                                  explicit_content_filter: Optional[int] = None, roles: Optional[List[Dict[str, Any]]] = None,
                                  channels: Optional[List[Dict[str, Any]]] = None, afk_channel_id: Optional[str] = None,
                                  afk_timeout: Optional[int] = None, system_channel_id: Optional[str] = None,
                                  system_channel_flags: Optional[int] = None) -> Any:
    """Create a new guild."""
    payload = _filter_none({
        "name": _safe_str(name),
        "region": _safe_str(region),
        "icon": icon,
        "verification_level": verification_level,
        "default_message_notifications": default_message_notifications,
        "explicit_content_filter": explicit_content_filter,
        "roles": _safe_list(roles),
        "channels": _safe_list(channels),
        "afk_channel_id": afk_channel_id,
        "afk_timeout": afk_timeout,
        "system_channel_id": system_channel_id,
        "system_channel_flags": system_channel_flags
    })
    return await discord_request("POST", "/guilds", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD(guild_id: str) -> Any:
    """Delete a guild permanently."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/guilds/{guild_id}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD(guild_id: str, name: Optional[str] = None, region: Optional[str] = None,
                                  verification_level: Optional[int] = None, default_message_notifications: Optional[int] = None,
                                  explicit_content_filter: Optional[int] = None, afk_channel_id: Optional[str] = None,
                                  afk_timeout: Optional[int] = None, icon: Optional[str] = None, owner_id: Optional[str] = None,
                                  splash: Optional[str] = None, discovery_splash: Optional[str] = None, banner: Optional[str] = None,
                                  system_channel_id: Optional[str] = None, system_channel_flags: Optional[int] = None,
                                  rules_channel_id: Optional[str] = None, public_updates_channel_id: Optional[str] = None,
                                  preferred_locale: Optional[str] = None, features: Optional[List[str]] = None,
                                  description: Optional[str] = None, premium_progress_bar_enabled: Optional[bool] = None,
                                  reason: Optional[str] = None) -> Any:
    """Modify a guild's settings."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "region": _safe_str(region),
        "verification_level": verification_level,
        "default_message_notifications": default_message_notifications,
        "explicit_content_filter": explicit_content_filter,
        "afk_channel_id": afk_channel_id,
        "afk_timeout": afk_timeout,
        "icon": icon,
        "owner_id": owner_id,
        "splash": splash,
        "discovery_splash": discovery_splash,
        "banner": banner,
        "system_channel_id": system_channel_id,
        "system_channel_flags": system_channel_flags,
        "rules_channel_id": rules_channel_id,
        "public_updates_channel_id": public_updates_channel_id,
        "preferred_locale": _safe_str(preferred_locale),
        "features": _safe_list(features),
        "description": _safe_str(description),
        "premium_progress_bar_enabled": premium_progress_bar_enabled
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD(guild_id: str, with_counts: Optional[bool] = None) -> Any:
    """Returns the guild object for the given id."""
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "with_counts": with_counts
    })
    return await discord_request("GET", f"/guilds/{guild_id}", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_MEMBERS(guild_id: str, limit: Optional[int] = None, after: Optional[str] = None) -> Any:
    """Returns a list of guild member objects."""
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "limit": limit,
        "after": after
    })
    return await discord_request("GET", f"/guilds/{guild_id}/members", params=params)

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_MEMBER(guild_id: str, user_id: str, nick: Optional[str] = None,
                                         roles: Optional[List[str]] = None, mute: Optional[bool] = None,
                                         deaf: Optional[bool] = None, channel_id: Optional[str] = None,
                                         communication_disabled_until: Optional[str] = None,
                                         flags: Optional[int] = None, reason: Optional[str] = None) -> Any:
    """Modify attributes of a guild member."""
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    payload = _filter_none({
        "nick": _safe_str(nick),
        "roles": _safe_list(roles),
        "mute": mute,
        "deaf": deaf,
        "channel_id": channel_id,
        "communication_disabled_until": communication_disabled_until,
        "flags": flags
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/members/{user_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_BANS(guild_id: str, limit: Optional[int] = None, before: Optional[str] = None,
                                     after: Optional[str] = None) -> Any:
    """Returns a list of ban objects for the users banned from this guild."""
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "limit": limit,
        "before": before,
        "after": after
    })
    return await discord_request("GET", f"/guilds/{guild_id}/bans", params=params)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_BAN(guild_id: str, user_id: str) -> Any:
    """Returns a ban object for the given user or a 404 not found if the ban cannot be found."""
    guild_id = _validate_guild_id(guild_id)
    user_id = _validate_user_id(user_id)
    return await discord_request("GET", f"/guilds/{guild_id}/bans/{user_id}")

@mcp.tool()
async def DISCORDBOT_PRUNE_GUILD(guild_id: str, days: int, compute_prune_count: Optional[bool] = None,
                                 include_roles: Optional[List[str]] = None, reason: Optional[str] = None) -> Any:
    """Begin a prune operation."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "days": days,
        "compute_prune_count": compute_prune_count,
        "include_roles": _safe_list(include_roles)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/prune", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_PREVIEW_PRUNE_GUILD(guild_id: str, days: Optional[int] = None,
                                         include_roles: Optional[List[str]] = None) -> Any:
    """Returns an object with one 'pruned' key indicating the number of members that would be removed."""
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "days": days,
        "include_roles": _safe_list(include_roles)
    })
    return await discord_request("GET", f"/guilds/{guild_id}/prune", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_ROLES(guild_id: str) -> Any:
    """Returns a list of role objects for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/roles")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_ROLE(guild_id: str, name: str, permissions: Optional[str] = None, 
                                       color: Optional[int] = None, hoist: Optional[bool] = None,
                                       mentionable: Optional[bool] = None, icon: Optional[str] = None,
                                       unicode_emoji: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Create a new role for the guild."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "permissions": permissions,
        "color": color,
        "hoist": hoist,
        "mentionable": mentionable,
        "icon": icon,
        "unicode_emoji": unicode_emoji
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/roles", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_ROLE(guild_id: str, role_id: str, name: Optional[str] = None,
                                       permissions: Optional[str] = None, color: Optional[int] = None,
                                       hoist: Optional[bool] = None, mentionable: Optional[bool] = None,
                                       icon: Optional[str] = None, unicode_emoji: Optional[str] = None,
                                       reason: Optional[str] = None) -> Any:
    """Modify a guild role."""
    guild_id = _validate_guild_id(guild_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "permissions": permissions,
        "color": color,
        "hoist": hoist,
        "mentionable": mentionable,
        "icon": icon,
        "unicode_emoji": unicode_emoji
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/roles/{role_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_ROLE(guild_id: str, role_id: str, reason: Optional[str] = None) -> Any:
    """Delete a guild role."""
    guild_id = _validate_guild_id(guild_id)
    role_id = _validate_snowflake(role_id, "Role ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/roles/{role_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LEAVE_GUILD(guild_id: str) -> Any:
    """Leave a guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/users/@me/guilds/{guild_id}")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_INVITES(guild_id: str) -> Any:
    """Returns a list of invite objects (with invite metadata) for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/invites")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_FROM_TEMPLATE(template_code: str, name: str, icon: Optional[str] = None) -> Any:
    """Create a new guild based on a template."""
    payload = _filter_none({
        "name": _safe_str(name),
        "icon": icon
    })
    return await discord_request("POST", f"/guilds/templates/{template_code}", json=payload)

@mcp.tool()
async def DISCORDBOT_SYNC_GUILD_TEMPLATE(guild_id: str, template_code: str) -> Any:
    """Sync the template to the guild's current state."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("PUT", f"/guilds/{guild_id}/templates/{template_code}")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_TEMPLATE(template_code: str) -> Any:
    """Returns a guild template object for the given code."""
    return await discord_request("GET", f"/guilds/templates/{template_code}")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_TEMPLATE(guild_id: str, template_code: str, name: Optional[str] = None,
                                          description: Optional[str] = None) -> Any:
    """Modify the template's metadata."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "description": _safe_str(description)
    })
    return await discord_request("PATCH", f"/guilds/{guild_id}/templates/{template_code}", json=payload)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_TEMPLATE(guild_id: str, template_code: str) -> Any:
    """Delete the template."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("DELETE", f"/guilds/{guild_id}/templates/{template_code}")

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_TEMPLATE(guild_id: str, name: str, description: Optional[str] = None) -> Any:
    """Creates a template for the guild."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "description": _safe_str(description)
    })
    return await discord_request("POST", f"/guilds/{guild_id}/templates", json=payload)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_TEMPLATES(guild_id: str) -> Any:
    """Returns an array of guild template objects."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/templates")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_PREVIEW(guild_id: str) -> Any:
    """Returns the guild preview object for public guilds."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/preview")

@mcp.tool()
async def DISCORDBOT_GET_GUILDS_ONBOARDING(guild_id: str) -> Any:
    """Returns guild onboarding configuration."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/onboarding")

@mcp.tool()
async def DISCORDBOT_PUT_GUILDS_ONBOARDING(guild_id: str, prompts: List[Dict[str, Any]], default_channel_ids: List[str],
                                           enabled: bool, mode: int, reason: Optional[str] = None) -> Any:
    """Modify guild onboarding configuration."""
    guild_id = _validate_guild_id(guild_id)
    payload = {
        "prompts": _safe_list(prompts),
        "default_channel_ids": _safe_list(default_channel_ids),
        "enabled": enabled,
        "mode": mode
    }
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PUT", f"/guilds/{guild_id}/onboarding", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WIDGET(guild_id: str) -> Any:
    """Returns the widget for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/widget.json")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WIDGET_SETTINGS(guild_id: str) -> Any:
    """Returns a guild widget settings object."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/widget")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_WIDGET_SETTINGS(guild_id: str, enabled: Optional[bool] = None,
                                                   channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Modify a guild widget."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "enabled": enabled,
        "channel_id": channel_id
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/widget", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_WELCOME_SCREEN(guild_id: str) -> Any:
    """Returns the Welcome Screen object for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/welcome-screen")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_WELCOME_SCREEN(guild_id: str, enabled: Optional[bool] = None,
                                                welcome_channels: Optional[List[Dict[str, Any]]] = None,
                                                description: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Modify the guild's Welcome Screen."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "enabled": enabled,
        "welcome_channels": _safe_list(welcome_channels),
        "description": _safe_str(description)
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/welcome-screen", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_GET_GUILD_VANITY_URL(guild_id: str) -> Any:
    """Returns a partial invite object for guilds with that feature enabled."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/vanity-url")

@mcp.tool()
async def DISCORDBOT_GET_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str, with_user_count: Optional[bool] = None) -> Any:
    """Get a guild scheduled event."""
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    params = _filter_none({
        "with_user_count": with_user_count
    })
    return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}", params=params)

@mcp.tool()
async def DISCORDBOT_CREATE_GUILD_SCHEDULED_EVENT(guild_id: str, name: str, scheduled_start_time: str,
                                                  entity_type: int, entity_metadata: Optional[Dict[str, Any]] = None,
                                                  scheduled_end_time: Optional[str] = None, privacy_level: Optional[int] = None,
                                                  description: Optional[str] = None, channel_id: Optional[str] = None,
                                                  reason: Optional[str] = None) -> Any:
    """Create a new scheduled event in the guild."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "name": _safe_str(name),
        "scheduled_start_time": scheduled_start_time,
        "entity_type": entity_type,
        "entity_metadata": _safe_dict(entity_metadata),
        "scheduled_end_time": scheduled_end_time,
        "privacy_level": privacy_level,
        "description": _safe_str(description),
        "channel_id": channel_id
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("POST", f"/guilds/{guild_id}/scheduled-events", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str,
                                                  name: Optional[str] = None, scheduled_start_time: Optional[str] = None,
                                                  entity_type: Optional[int] = None, entity_metadata: Optional[Dict[str, Any]] = None,
                                                  scheduled_end_time: Optional[str] = None, privacy_level: Optional[int] = None,
                                                  status: Optional[int] = None, description: Optional[str] = None,
                                                  channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Modify a guild scheduled event."""
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    payload = _filter_none({
        "name": _safe_str(name),
        "scheduled_start_time": scheduled_start_time,
        "entity_type": entity_type,
        "entity_metadata": _safe_dict(entity_metadata),
        "scheduled_end_time": scheduled_end_time,
        "privacy_level": privacy_level,
        "status": status,
        "description": _safe_str(description),
        "channel_id": channel_id
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_SCHEDULED_EVENT(guild_id: str, guild_scheduled_event_id: str, reason: Optional[str] = None) -> Any:
    """Delete a guild scheduled event."""
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}", headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_SCHEDULED_EVENTS(guild_id: str, with_user_count: Optional[bool] = None) -> Any:
    """Returns a list of guild scheduled event objects for the given guild."""
    guild_id = _validate_guild_id(guild_id)
    params = _filter_none({
        "with_user_count": with_user_count
    })
    return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_SCHEDULED_EVENT_USERS(guild_id: str, guild_scheduled_event_id: str,
                                                      limit: Optional[int] = None, with_member: Optional[bool] = None,
                                                      before: Optional[str] = None, after: Optional[str] = None) -> Any:
    """Get a list of guild scheduled event users."""
    guild_id = _validate_guild_id(guild_id)
    guild_scheduled_event_id = _validate_snowflake(guild_scheduled_event_id, "Scheduled Event ID")
    params = _filter_none({
        "limit": limit,
        "with_member": with_member,
        "before": before,
        "after": after
    })
    return await discord_request("GET", f"/guilds/{guild_id}/scheduled-events/{guild_scheduled_event_id}/users", params=params)

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_VOICE_REGIONS(guild_id: str) -> Any:
    """Returns a list of voice region objects for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/regions")

@mcp.tool()
async def DISCORDBOT_LIST_GUILD_INTEGRATIONS(guild_id: str) -> Any:
    """Returns a list of integration objects for the guild."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/integrations")

@mcp.tool()
async def DISCORDBOT_DELETE_GUILD_INTEGRATION(guild_id: str, integration_id: str, reason: Optional[str] = None) -> Any:
    """Delete the attached integration object for the guild."""
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
    """Returns an invite object for the given code."""
    params = _filter_none({
        "with_counts": with_counts,
        "with_expiration": with_expiration,
        "guild_scheduled_event_id": guild_scheduled_event_id
    })
    return await discord_request("GET", f"/invites/{invite_code}", params=params)

@mcp.tool()
async def DISCORDBOT_INVITE_REVOKE(invite_code: str, reason: Optional[str] = None) -> Any:
    """Delete an invite."""
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("DELETE", f"/invites/{invite_code}", headers=headers)

# ---------------- MISCELLANEOUS / UTILITY (6 tools) ----------------
@mcp.tool()
async def DISCORDBOT_GET_GUILD_WIDGET_SETTINGS(guild_id: str) -> Any:
    """Returns a guild widget settings object."""
    guild_id = _validate_guild_id(guild_id)
    return await discord_request("GET", f"/guilds/{guild_id}/widget")

@mcp.tool()
async def DISCORDBOT_UPDATE_GUILD_WIDGET_SETTINGS(guild_id: str, enabled: Optional[bool] = None,
                                                   channel_id: Optional[str] = None, reason: Optional[str] = None) -> Any:
    """Updates an existing discord guild's widget settings, such as its enabled state or clearing its invite channel."""
    guild_id = _validate_guild_id(guild_id)
    payload = _filter_none({
        "enabled": enabled,
        "channel_id": channel_id
    })
    headers = DEFAULT_HEADERS.copy()
    if reason:
        headers["X-Audit-Log-Reason"] = _safe_str(reason)
    return await discord_request("PATCH", f"/guilds/{guild_id}/widget", json=payload, headers=headers)

@mcp.tool()
async def DISCORDBOT_LIST_VOICE_REGIONS() -> Any:
    """Returns an array of voice region objects that can be used when creating servers."""
    return await discord_request("GET", "/voice/regions")

@mcp.tool()
async def DISCORDBOT_CREATE_DM(recipient_id: str) -> Any:
    """Create a new DM channel with a user."""
    recipient_id = _validate_user_id(recipient_id)
    payload = {
        "recipient_id": recipient_id
    }
    return await discord_request("POST", "/users/@me/channels", json=payload)

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



