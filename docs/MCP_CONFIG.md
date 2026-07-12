# Kettu Squeeze — MCP Configuration
# Подключение к Hermes / OpenClaw / Claude Code / Cursor

# ═══ STDIO Transport (рекомендуется) ═══
# Добавить в mcp.json или mcpServers секцию конфигурации:

# Для Hermes (~/.hermes/mcp.json):
"""
{
  "mcpServers": {
    "kettu-squeeze": {
      "command": "kettu-squeeze-mcp",
      "args": [],
      "env": {}
    }
  }
}
"""

# Для Claude Code (~/.claude/mcp.json или проект .mcp.json):
"""
{
  "mcpServers": {
    "kettu-squeeze": {
      "type": "stdio",
      "command": "kettu-squeeze-mcp",
      "args": []
    }
  }
}
"""

# Для OpenClaw (mcp.json):
"""
{
  "mcpServers": {
    "kettu-squeeze": {
      "command": "kettu-squeeze-mcp",
      "args": []
    }
  }
}
"""

# ═══ Альтернативно: HTTP транспорт ═══
# Запустить сервер:
#   uvicorn kettu_squeeze.api.server:app --host 127.0.0.1 --port 8765
#
# Подключить:
"""
{
  "mcpServers": {
    "kettu-squeeze": {
      "url": "http://127.0.0.1:8765/mcp",
      "transport": "streamable-http"
    }
  }
}
"""
