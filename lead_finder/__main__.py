"""
lead_finder/__main__.py
Entrypoint: run the Lead Finder HTTP service.
"""

import uvicorn
from common.config import LEAD_FINDER_PORT

if __name__ == "__main__":
    uvicorn.run(
        "lead_finder.agent:app",
        host="0.0.0.0",
        port=LEAD_FINDER_PORT,
        reload=True,
    )
