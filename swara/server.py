"""Local web app: python -m swara.server  (or the swara-app launcher)."""
import os
import socket
import tempfile
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .convert import convert
from .readers import read_file, read_text

STATIC = Path(__file__).parent / "static"
MAX_BYTES = 20 * 1024 * 1024
app = FastAPI(title="Swara")


def _bad(message, status=400):
    return JSONResponse({"error": message}, status_code=status)


@app.post("/api/convert")
async def api_convert(
    file: UploadFile | None = File(None),
    notes: str = Form(""),
    sa: str = Form("D#"),
    key: str = Form(""),
    absolute: bool = Form(False),
    part: int | None = Form(None),
    subdiv: int | None = Form(None),
    long: bool = Form(False),
):
    try:
        if file is not None and file.filename:
            data = await file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return _bad("That file is too big (20 MB max).", 413)
            suffix = Path(file.filename).suffix.lower()
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "upload" + suffix)
                with open(path, "wb") as f:
                    f.write(data)
                piece = read_file(path)
            if not piece.title:
                piece.title = Path(file.filename).stem
        elif notes.strip():
            piece = read_text(notes)
        else:
            return _bad("Choose a file or type some notes.")
        return convert(piece, sa=sa, key=key.strip() or None, absolute=absolute, part=part,
                       subdiv=subdiv, long=long)
    except (ValueError, KeyError, OSError, EOFError) as e:
        return _bad(str(e) or "Couldn't read that file.")
    except Exception:  # corrupt files can trip a reader in odd ways
        return _bad("Couldn't read that file. Is it a valid MIDI or MusicXML file?")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _already_running(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    port = int(os.environ.get("SWARA_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    if _already_running(port):  # a second launch just brings the page up again
        if not os.environ.get("SWARA_NO_BROWSER"):
            webbrowser.open(url)
        return
    if not os.environ.get("SWARA_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
