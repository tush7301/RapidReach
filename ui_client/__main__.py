"""
ui_client/__main__.py
Entrypoint: run the UI Client dashboard.
"""

import uvicorn
from common.config import UI_CLIENT_PORT

if __name__ == "__main__":
    uvicorn.run(
        "ui_client.main:app",
        host="0.0.0.0",
        port=UI_CLIENT_PORT,
        reload=True,
    )
