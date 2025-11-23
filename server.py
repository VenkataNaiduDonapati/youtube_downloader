from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
import subprocess, os, re, yt_dlp, shutil, platform

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)

def get_aria2_path():
    """Return path to bundled aria2c.exe or system PATH fallback."""
    if platform.system() == "Windows":
        bundled = os.path.join(BASE_DIR, "bin", "aria2c.exe")
        if os.path.exists(bundled):
            return bundled
    return shutil.which("aria2c")

@app.get("/metadata")
def metadata(url: str = Query(...)):
    try:
        ydl_opts = {'quiet': True,"cookiesfrombrowser": ()}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            vcodec, acodec = f.get("vcodec"), f.get("acodec")
            if (vcodec == "none" and acodec and acodec != "none") or (vcodec and vcodec != "none" and acodec and acodec != "none"):
                formats.append({
                    "id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "height": f.get("height"),
                    "acodec": acodec,
                    "vcodec": vcodec,
                })

        return {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "formats": formats
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/download")
def download(url: str, format_id: str = Query("best")):
    try:
        # Fetch metadata for filename
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = sanitize_filename(info.get("title", "video"))

        ext = "mp3" if format_id == "bestaudio" else "mp4"
        filename = f"{title}.{ext}"

        # Dedicated downloads folder
        DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        # Build yt-dlp command
        cmd = [
            "yt-dlp",
            "-f", f"{format_id}",
            "-o", filepath,
            "--ffmpeg-location", os.path.join(BASE_DIR, "ffmpeg.exe"),
            "--concurrent-fragments", "16",
            "--extractor-args", "youtube:player_client=default",
            "--force-overwrites",
            "--no-cache-dir",
        ]

        # Use aria2c if available
        aria2_path = get_aria2_path()
        if aria2_path:
            cmd += [
                "--external-downloader", aria2_path,
                "--external-downloader-args", "-x 16 -s 16 -k 1M"
            ]

        if format_id == "bestaudio":
            cmd += ["--audio-format", "mp3"]
        else:
            cmd += ["--merge-output-format", "mp4"]

        cmd.append(url)

        # Run yt-dlp and capture logs
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("YT-DLP CMD:", " ".join(cmd))
        print("YT-DLP STDOUT:", result.stdout)
        print("YT-DLP STDERR:", result.stderr)

        if result.returncode != 0:
            return JSONResponse(status_code=500, content={"error": result.stderr})

        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return JSONResponse(status_code=500, content={"error": "Download failed, empty file"})

        # Stream file in chunks
        def iterfile(path):
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1 MB chunks
                    if not chunk:
                        break
                    yield chunk

        # Delete file after streaming completes
        task = BackgroundTask(lambda: os.remove(filepath))

        return StreamingResponse(
            iterfile(filepath),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
            background=task
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Serve static frontend

app.mount("/", StaticFiles(directory="static", html=True), name="static")
