from pathlib import Path
from datetime import datetime

import os

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import markdown
import nbformat
from nbconvert import HTMLExporter

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")
app.mount("/files", StaticFiles(directory="posts"), name="files")

templates = Jinja2Templates(directory="app/templates")
POSTS_DIR = Path("posts")
DRAFTS_DIR = POSTS_DIR / "drafts"
VERSIONS_DIR = POSTS_DIR / "versions"

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


def parse_metadata(content: str) -> tuple[str, list[str], str]:
    """Extract tags and category metadata from the top of a markdown file."""
    lines = content.splitlines()
    tags: list[str] = []
    category = ""
    while lines:
        lower = lines[0].lower()
        if lower.startswith("tags:"):
            tags = [t.strip() for t in lines.pop(0).split(":", 1)[1].split(",") if t.strip()]
        elif lower.startswith("category:"):
            category = lines.pop(0).split(":", 1)[1].strip()
        else:
            break
    if lines and lines[0] == "":
        lines.pop(0)
    return "\n".join(lines), tags, category


def save_version(status: str, name: str, content: str) -> None:
    """Save a version of a post and keep only the latest three."""
    slug = name.rsplit(".", 1)[0]
    dir_path = VERSIONS_DIR / status / slug
    dir_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    version_file = dir_path / f"{timestamp}.md"
    version_file.write_text(content, encoding="utf-8")
    versions = sorted(dir_path.glob("*.md"))
    if len(versions) > 3:
        for old in versions[:-3]:
            old.unlink()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    posts = [
        p.name
        for p in POSTS_DIR.iterdir()
        if p.is_file() and p.suffix in (".md", ".ipynb")
    ]
    return templates.TemplateResponse("index.html", {"request": request, "posts": posts})


@app.get("/post/{name}", response_class=HTMLResponse)
async def read_post(name: str, request: Request):
    file_path = POSTS_DIR / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Post not found")

    if file_path.suffix == ".md":
        raw = file_path.read_text(encoding="utf-8")
        content, tags, category = parse_metadata(raw)
        body, toc = render_markdown(content)
    elif file_path.suffix == ".ipynb":
        nb = nbformat.read(file_path, as_version=4)
        html_exporter = HTMLExporter()
        body, _ = html_exporter.from_notebook_node(nb)
        toc = ""
        tags = []
        category = ""
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    return templates.TemplateResponse(
        "post.html",
        {
            "request": request,
            "content": body,
            "toc": toc,
            "tags": tags,
            "category": category,
        },
    )


@app.get("/tags", response_class=HTMLResponse)
async def tags_index(request: Request):
    tag_map: dict[str, list[str]] = {}
    for path in POSTS_DIR.glob("*.md"):
        raw = path.read_text(encoding="utf-8")
        _, tags, _ = parse_metadata(raw)
        for t in tags:
            tag_map.setdefault(t, []).append(path.name)
    return templates.TemplateResponse("tags.html", {"request": request, "tags": tag_map})


@app.get("/tags/{tag}", response_class=HTMLResponse)
async def tag_archive(tag: str, request: Request):
    posts: list[str] = []
    for path in POSTS_DIR.glob("*.md"):
        raw = path.read_text(encoding="utf-8")
        _, tags, _ = parse_metadata(raw)
        if tag in tags:
            posts.append(path.name)
    return templates.TemplateResponse("tag.html", {"request": request, "tag": tag, "posts": posts})


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    results: list[str] = []
    if q:
        query = q.lower()
        for path in POSTS_DIR.glob("*.md"):
            if query in path.read_text(encoding="utf-8").lower():
                results.append(path.name)
        for path in POSTS_DIR.glob("*.ipynb"):
            nb = nbformat.read(path, as_version=4)
            text = "".join(
                cell.source for cell in nb.cells if getattr(cell, "cell_type", "") == "markdown"
            )
            if query in text.lower():
                results.append(path.name)
    return templates.TemplateResponse(
        "search.html", {"request": request, "query": q, "results": results}
    )


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


@app.post("/admin/upload")
async def admin_upload_post(
    request: Request, file: UploadFile = File(...)
):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    dest = POSTS_DIR / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())
    return RedirectResponse(url="/admin/posts", status_code=302)


@app.get("/admin/posts", response_class=HTMLResponse)
async def admin_posts(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    def meta(path: Path) -> dict:
        raw = path.read_text(encoding="utf-8")
        _, tags, category = parse_metadata(raw)
        return {"name": path.name, "tags": ", ".join(tags), "category": category}

    drafts = [meta(p) for p in DRAFTS_DIR.glob("*.md")] if DRAFTS_DIR.exists() else []
    published = [meta(p) for p in POSTS_DIR.glob("*.md")] + [
        {"name": p.name, "tags": "", "category": ""} for p in POSTS_DIR.glob("*.ipynb")
    ]
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
        {
            "request": request,
            "title": "",
            "content": "",
            "tags": "",
            "category": "",
            "is_new": True,
        },
    )


@app.post("/admin/posts/new")
async def admin_new_post_post(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    tags: str = Form(""),
    category: str = Form(""),
    action: str = Form(...),
):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    if action == "preview":
        body, _ = render_markdown(content)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return templates.TemplateResponse(
            "admin_preview.html",
            {
                "request": request,
                "title": title,
                "content": body,
                "tags": tag_list,
                "category": category,
            },
        )
    filename = f"{slugify(title)}.md"
    if action == "publish":
        path = POSTS_DIR / filename
        version_status = "published"
    else:
        path = DRAFTS_DIR / filename
        version_status = "draft"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        save_version(version_status, filename, path.read_text(encoding="utf-8"))
    header = []
    if category:
        header.append(f"Category: {category}")
    if tags:
        header.append(f"Tags: {tags}")
    full = "\n".join(header + ["", content]) if header else content
    path.write_text(full, encoding="utf-8")
    return RedirectResponse(url="/admin/posts", status_code=302)


@app.get("/admin/posts/edit/{status}/{name}", response_class=HTMLResponse)
async def admin_edit_post(request: Request, status: str, name: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    base = DRAFTS_DIR if status == "draft" else POSTS_DIR
    file_path = base / name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Post not found")
    raw = file_path.read_text(encoding="utf-8")
    content, tags, category = parse_metadata(raw)
    title = name.rsplit(".", 1)[0].replace("-", " ")
    return templates.TemplateResponse(
        "admin_edit.html",
        {
            "request": request,
            "title": title,
            "content": content,
            "tags": ", ".join(tags),
            "category": category,
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
    tags: str = Form(""),
    category: str = Form(""),
    action: str = Form(...),
):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    if action == "preview":
        body, _ = render_markdown(content)
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        return templates.TemplateResponse(
            "admin_preview.html",
            {
                "request": request,
                "title": title,
                "content": body,
                "tags": tag_list,
                "category": category,
            },
        )
    old_path = (DRAFTS_DIR if status == "draft" else POSTS_DIR) / name
    if old_path.exists():
        save_version(status, name, old_path.read_text(encoding="utf-8"))
    new_filename = f"{slugify(title)}.md"
    if action == "publish":
        path = POSTS_DIR / new_filename
    else:
        path = DRAFTS_DIR / new_filename
    path.parent.mkdir(parents=True, exist_ok=True)
    header = []
    if category:
        header.append(f"Category: {category}")
    if tags:
        header.append(f"Tags: {tags}")
    full = "\n".join(header + ["", content]) if header else content
    path.write_text(full, encoding="utf-8")
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


@app.get("/admin/posts/versions/{status}/{name}", response_class=HTMLResponse)
async def admin_post_versions(request: Request, status: str, name: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    slug = name.rsplit(".", 1)[0]
    dir_path = VERSIONS_DIR / status / slug
    versions = sorted(dir_path.glob("*.md"), reverse=True) if dir_path.exists() else []
    return templates.TemplateResponse(
        "admin_versions.html",
        {
            "request": request,
            "name": name,
            "status": status,
            "versions": [v.name for v in versions],
        },
    )


@app.get("/admin/posts/versions/{status}/{name}/{version}", response_class=HTMLResponse)
async def admin_post_version_view(request: Request, status: str, name: str, version: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    slug = name.rsplit(".", 1)[0]
    path = VERSIONS_DIR / status / slug / version
    if not path.exists():
        raise HTTPException(status_code=404, detail="Version not found")
    raw = path.read_text(encoding="utf-8")
    content, tags, category = parse_metadata(raw)
    body, _ = render_markdown(content)
    return templates.TemplateResponse(
        "admin_preview.html",
        {
            "request": request,
            "title": slug.replace("-", " "),
            "content": body,
            "tags": tags,
            "category": category,
        },
    )


@app.post("/admin/posts/versions/{status}/{name}/{version}/restore")
async def admin_post_version_restore(request: Request, status: str, name: str, version: str):
    if not request.session.get("user"):
        return RedirectResponse(url="/admin/login", status_code=302)
    slug = name.rsplit(".", 1)[0]
    version_path = VERSIONS_DIR / status / slug / version
    if not version_path.exists():
        raise HTTPException(status_code=404, detail="Version not found")
    content = version_path.read_text(encoding="utf-8")
    dest = (DRAFTS_DIR if status == "draft" else POSTS_DIR) / name
    if dest.exists():
        save_version(status, name, dest.read_text(encoding="utf-8"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return RedirectResponse(url="/admin/posts", status_code=302)
