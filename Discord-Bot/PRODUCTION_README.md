# Discord MCP Production Server

A production-ready Model Context Protocol (MCP) server implementing comprehensive Discord REST API coverage with ~180+ tools.

## 🚀 Production Features

### Core Features
- **179+ Discord REST API Tools** - Complete coverage of Discord's API
- **Production-Ready HTTP Client** - Connection pooling, retry logic, circuit breaker
- **Comprehensive Error Handling** - Graceful error recovery and detailed logging
- **File Upload Support** - Safe multipart uploads with validation
- **Environment-Based Configuration** - No hard-coded secrets
- **Health Monitoring** - Built-in health checks and metrics
- **Graceful Shutdown** - Proper cleanup and signal handling

### Production Enhancements
- **Circuit Breaker Pattern** - Prevents cascade failures
- **Exponential Backoff Retry** - Smart retry logic with jitter
- **Request/Response Logging** - Detailed request tracking with IDs
- **Metrics Collection** - Success rates, response times, error tracking
- **File Validation** - Size limits, type checking, security validation
- **Connection Pooling** - Efficient HTTP connection management
- **Log Rotation** - Automatic log file rotation and cleanup
- **Signal Handling** - Graceful shutdown on SIGINT/SIGTERM

## 📋 Requirements

```bash
pip install httpx mcp
```

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_BOT_TOKEN` | **Required** | Discord bot token (include "Bot " prefix) |
| `DISCORD_API_BASE` | `https://discord.com/api/v10` | Discord API base URL |
| `REQUEST_TIMEOUT` | `30.0` | Request timeout in seconds |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FILE` | `discord_mcp.log` | Log file path |

### Production Configuration

The server uses a `ProductionConfig` class with the following settings:

```python
# API Configuration
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_DELAY = 1.0
CONNECTION_POOL_SIZE = 100
MAX_KEEPALIVE_CONNECTIONS = 20

# Circuit Breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60

# File Upload
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB (Discord limit)
ALLOWED_FILE_TYPES = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mov']

# Logging
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5
```

## 🚀 Usage

### Basic Usage

```bash
# Set your Discord bot token
export DISCORD_BOT_TOKEN="Bot YOUR_TOKEN_HERE"

# Run the server
python stage_organized.py
```

### Docker Usage

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY stage_organized.py .
ENV DISCORD_BOT_TOKEN="Bot YOUR_TOKEN_HERE"

CMD ["python", "stage_organized.py"]
```

### Production Deployment

```bash
# Install dependencies
pip install httpx mcp

# Set production environment
export DISCORD_BOT_TOKEN="Bot YOUR_TOKEN_HERE"
export LOG_LEVEL="INFO"
export REQUEST_TIMEOUT="30.0"

# Run with process manager (PM2, systemd, etc.)
python stage_organized.py
```

## 📊 Monitoring & Health Checks

### Health Check Endpoint

The server provides built-in health monitoring:

```python
# Check server health
health_status = await DISCORDBOT_HEALTH_CHECK()
```

Health check includes:
- Discord API connectivity
- HTTP client status
- Circuit breaker state
- Request metrics
- Server uptime

### Metrics Collection

```python
# Get server metrics
metrics = await DISCORDBOT_GET_METRICS()
```

Metrics include:
- Total requests
- Success/failure rates
- Average response time
- Rate limiting events
- Circuit breaker status

### Circuit Breaker Management

```python
# Reset circuit breaker manually
await DISCORDBOT_RESET_CIRCUIT_BREAKER()
```

## 🛠️ Tool Categories

### Application & Command Management (20 tools)
- Create, update, delete application commands
- Manage command permissions
- Application information and settings

### Channel & Thread Management (26 tools)
- Channel CRUD operations
- Thread management
- Permission overwrites
- Stage instances and voice states

### Message Management (16 tools)
- Send, edit, delete messages
- Message reactions and pins
- Bulk operations and crossposting

### Guild Management (46 tools)
- Guild settings and members
- Roles and permissions
- Bans and moderation
- Scheduled events and integrations

### Webhook Management (17 tools)
- Webhook CRUD operations
- Message execution and management
- Slack/GitHub compatibility

### User & Member Management (12 tools)
- User information and updates
- Guild member management
- Role assignments

### Emoji & Sticker Management (12 tools)
- Emoji and sticker operations
- File uploads and validation

### Moderation & Automation (8 tools)
- Auto-moderation rules
- Guild bans and pruning

### Gateway & Connection (3 tools)
- Gateway information
- Public keys

### Invites & Templates (8 tools)
- Invite management
- Guild templates

### Miscellaneous/Utility (6 tools)
- Voice regions
- DM creation
- Utility functions

## 🔒 Security Features

### File Upload Security
- File size validation (25MB limit)
- File type checking
- Path traversal prevention
- Proper file cleanup

### Input Validation
- Snowflake ID validation
- Parameter sanitization
- Safe string handling
- None value filtering

### Error Handling
- Comprehensive error logging
- Stack trace capture
- Sensitive data protection
- Graceful failure recovery

## 📈 Performance Features

### Connection Management
- HTTP connection pooling
- Keep-alive connections
- Connection limits and timeouts
- Efficient resource usage

### Retry Logic
- Exponential backoff
- Configurable retry attempts
- Rate limit handling
- Circuit breaker protection

### Monitoring
- Request/response timing
- Success rate tracking
- Error rate monitoring
- Performance metrics

## 🚨 Error Handling

### Circuit Breaker
- Automatic failure detection
- Service protection
- Recovery attempts
- Manual reset capability

### Rate Limiting
- Discord API rate limit handling
- Automatic retry with backoff
- Rate limit metrics
- Graceful degradation

### File Operations
- Safe file handling
- Proper cleanup
- Size validation
- Type checking

## 📝 Logging

### Log Levels
- **DEBUG**: Detailed request/response information
- **INFO**: General operational information
- **WARNING**: Non-critical issues
- **ERROR**: Critical errors and failures

### Log Format
```
2024-01-15 10:30:45 [INFO] discord_mcp_production: [req_1705312245123] Making POST request to https://discord.com/api/v10/channels/123456789/messages (took 0.234s)
```

### Log Rotation
- Automatic log file rotation
- Configurable file size limits
- Backup file management
- Disk space protection

## 🔧 Troubleshooting

### Common Issues

1. **Circuit Breaker Open**
   ```python
   # Reset circuit breaker
   await DISCORDBOT_RESET_CIRCUIT_BREAKER()
   ```

2. **Rate Limiting**
   - Server automatically handles rate limits
   - Check metrics for rate limit events
   - Adjust request frequency if needed

3. **File Upload Failures**
   - Check file size limits (25MB)
   - Verify file type is allowed
   - Ensure file exists and is readable

4. **Connection Issues**
   - Check Discord API status
   - Verify bot token is valid
   - Review network connectivity

### Debug Mode

```bash
export LOG_LEVEL="DEBUG"
python stage_organized.py
```

### Health Check

```python
# Check server health
health = await DISCORDBOT_HEALTH_CHECK()
print(f"Status: {health['status']}")
print(f"Uptime: {health['uptime']}s")
```

## 📚 API Documentation

Each tool includes comprehensive documentation:

```python
@mcp.tool()
async def DISCORDBOT_CREATE_MESSAGE(channel_id: str, content: Optional[str] = None, ...) -> Any:
    """Post a message to a guild text or DM channel.
    
    Args:
        channel_id: The channel ID to send the message to
        content: The message content (optional)
        # ... other parameters
    
    Returns:
        Message object or error information
    """
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs for error details
3. Use the health check tools
4. Open an issue with detailed information

---

**Production-Ready Discord MCP Server** - Built for scale, reliability, and performance.
