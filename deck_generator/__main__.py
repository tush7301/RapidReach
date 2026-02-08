#!/usr/bin/env python3
"""
Entry point for Deck Generator agent.
Run with: python -m deck_generator
"""

import asyncio
import logging

import uvicorn
from deck_generator.agent import app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run the Deck Generator agent."""
    logger.info("🎨 Starting RapidReach Deck Generator...")
    config = uvicorn.Config(app, host="0.0.0.0", port=8086, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())