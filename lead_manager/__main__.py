"""
lead_manager/__main__.py
Entrypoint: run the Lead Manager HTTP service.
"""

import uvicorn
from common.config import LEAD_MANAGER_PORT

if __name__ == "__main__":
    uvicorn.run(
        "lead_manager.agent:app",
        host="0.0.0.0",
        port=LEAD_MANAGER_PORT,
        reload=True,
    )
