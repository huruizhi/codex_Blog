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
DRAFTS_DIR = POSTS_DIR / "drafts"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")


def slugify(title: str) -> str:
    """Simple slugify implementation."""
    return "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")


def render_markdown(content: str) -> tuple[str, str]:
    """Render markdown content to HTML and return body and toc."""
    md = markdown.Markdown(extensions=["fenced_code", "codehilite", "toc"])
    body = md.convert(content)
    return body, md.toc


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
        return RedirectResponse(url="/admin/posts", status_code=302)
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


@app.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    drafts = [p.name for p in DRAFTS_DIR.glob("*.md")] if DRAFTS_DIR.exists() else []
    published = [p.name for p in POSTS_DIR.glob("*.md")]
    return templates.TemplateResponse(
        "admin_posts.html",
        {"request": request, "drafts": drafts, "published": published},
    )


@app.get("/admin/posts/new", response_class=HTMLResponse)
async def admin_new_post(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "admin_edit.html",
        {"request": request, "title": "", "content": "", "is_new": True},
    )


@app.post("/admin/posts/new")
async def admin_new_post_post(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    action: str = Form(...),
):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    if action == "preview":
        body, _ = render_markdown(content)
        return templates.TemplateResponse(
            "admin_preview.html",
            {"request": request, "title": title, "content": body},
        )
    filename = f"{slugify(title)}.md"
    if action == "publish":
        path = POSTS_DIR / filename
    else:
        path = DRAFTS_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return RedirectResponse(url="/admin/posts", status_code=302)


@app.get("/admin/posts/edit/{status}/{name}", response_class=HTMLResponse)
async def admin_edit_post(request: Request, status: str, name: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    base = DRAFTS_DIR if status == "draft" else POSTS_DIR
    file_path = base / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Post not found")
    content = file_path.read_text(encoding="utf-8")
    title = name.rsplit(".", 1)[0].replace("-", " ")
    return templates.TemplateResponse(
        "admin_edit.html",
        {
            "request": request,
            "title": title,
            "content": content,
            "is_new": False,
            "status": status,
            "name": name,
        },
    )


@app.post("/admin/posts/edit/{status}/{name}")
async def admin_edit_post_post(
    request: Request,
    status: str,
    name: str,
    title: str = Form(...),
    content: str = Form(...),
    action: str = Form(...),
):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    if action == "preview":
        body, _ = render_markdown(content)
        return templates.TemplateResponse(
            "admin_preview.html",
            {"request": request, "title": title, "content": body},
        )
    new_filename = f"{slugify(title)}.md"
    if action == "publish":
        path = POSTS_DIR / new_filename
    else:
        path = DRAFTS_DIR / new_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    old_path = (DRAFTS_DIR if status == "draft" else POSTS_DIR) / name
    if old_path != path and old_path.exists():
        old_path.unlink()
    return RedirectResponse(url="/admin/posts", status_code=302)


@app.post("/admin/posts/delete/{status}/{name}")
async def admin_delete_post(request: Request, status: str, name: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    path = (DRAFTS_DIR if status == "draft" else POSTS_DIR) / name
    if path.exists():
        path.unlink()
    return RedirectResponse(url="/admin/posts", status_code=302)
