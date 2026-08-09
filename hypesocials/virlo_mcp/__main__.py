"""Arg-free stdio entry point: `python -m hypesocials.virlo_mcp` (20 §3, D21).

Spawned by `mcp_client` from the `mcp_servers.virlo` config command, in this same virtual
environment. Takes no arguments — everything it needs arrives in the per-server env dict.
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
