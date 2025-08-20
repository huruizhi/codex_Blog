from pathlib import Path

import os

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import markdown
import nbformat
from nbconvert import HTMLExporter

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")

templates = Jinja2Templates(directory="app/templates")
POSTS_DIR = Path("posts")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")


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
        md = markdown.Markdown(extensions=["fenced_code", "codehilite", "toc"])
        body = md.convert(content)
        toc = md.toc
    elif file_path.suffix == ".ipynb":
        nb = nbformat.read(file_path, as_version=4)
        html_exporter = HTMLExporter()
        body, _ = html_exporter.from_notebook_node(nb)
        toc = ""
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    return templates.TemplateResponse("post.html", {"request": request, "content": body, "toc": toc})


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin/login")
async def admin_login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["user"] = username
        return RedirectResponse(url="/admin/upload", status_code=302)
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": "Invalid credentials"},
        status_code=401,
    )


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@app.get("/admin/upload", response_class=HTMLResponse)
async def admin_upload(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse("admin_upload.html", {"request": request})
