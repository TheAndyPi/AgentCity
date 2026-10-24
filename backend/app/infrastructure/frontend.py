"""Optional same-origin serving of the built client; API routes keep priority."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_frontend(app: FastAPI, directory: Path):
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise ValueError("FRONTEND_DIST must contain the built frontend index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path == "api" or path.startswith(("api/", "health/")):
            raise HTTPException(404, "Not found")
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404, "Not found")
        if target.is_file():
            return FileResponse(target)
        if path.startswith("assets/") or Path(path).suffix:
            raise HTTPException(404, "Asset not found")
        return FileResponse(index)
