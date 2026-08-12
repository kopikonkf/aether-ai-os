"""Aether MCP OAuth Edge — package root.

ADR-0056: OAuth 2.0 Authorization Server facade in front of Living Machine MCP.
Provides principal identity (principal_id) and scoped capabilities to external
model frontends (ChatGPT, Claude, Gemini, etc.) without exposing AETHER_MCP_TOKEN.
"""
