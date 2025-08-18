from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import markdown
import nbformat
from nbconvert import HTMLExporter

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
POSTS_DIR = Path("posts")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    posts = [p.name for p in POSTS_DIR.iterdir() if p.is_file()]
    return templates.TemplateResponse("index.html", {"request": request, "posts": posts})


@app.get("/post/{name}", response_class=HTMLResponse)
async def read_post(name: str, request: Request):
    file_path = POSTS_DIR / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Post not found")

    if file_path.suffix == ".md":
        content = file_path.read_text(encoding="utf-8")
        body = markdown.markdown(content)
    elif file_path.suffix == ".ipynb":
        nb = nbformat.read(file_path, as_version=4)
        html_exporter = HTMLExporter()
        body, _ = html_exporter.from_notebook_node(nb)
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    return templates.TemplateResponse("post.html", {"request": request, "content": body})


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.get("/admin/upload", response_class=HTMLResponse)
async def admin_upload(request: Request):
    return templates.TemplateResponse("admin_upload.html", {"request": request})
