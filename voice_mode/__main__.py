"""
Main entry point for voice-mode when called as a module.

Runs the MCP server for TTS functionality.
"""

from .server import mcp

if __name__ == "__main__":
    mcp.run()
