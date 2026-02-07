"""
sdr/__main__.py
Entrypoint: run the SDR Agent HTTP service.
"""

import uvicorn
from common.config import SDR_PORT

if __name__ == "__main__":
    uvicorn.run(
        "sdr.agent:app",
        host="0.0.0.0",
        port=SDR_PORT,
        reload=True,
    )
