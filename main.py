"""
TopicTracker — FastAPI application.

Routes:
  GET  /login               login page
  POST /login               authenticate
  GET  /logout              clear cookie
  GET  /                    list user's runs
  GET  /new                 new run form
  POST /new                 create run + start download
  GET  /run/{id}            run dashboard (all phases)
  GET  /api/run/{id}/status download job status (polling)
  POST /api/run/{id}/analyse start NLP analysis
  GET  /api/run/{id}/analysis_status analysis job status (polling)
  GET  /api/run/{id}/entities entity list for a category
  POST /api/run/{id}/plot   generate Bokeh embed
  GET  /run/{id}/plots/{name} serve SVG plot
  GET  /run/{id}/download/{name} download Gephi/data CSV
  GET  /admin               admin: list users
  POST /admin/users         create user
  POST /admin/users/{uid}/toggle toggle active
  POST /admin/users/{uid}/delete  delete user
"""
import os
from datetime import datetime
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import (
    create_token, get_current_user, get_user_or_none,
    hash_password, require_admin, verify_password,
)
from models import Run, User, get_db, init_db
from pipeline import JOBS, get_job, start_download
from analyser import ANALYSIS_JOBS, get_analysis_job, start_analysis
from visualizer import BOKEH_VERSION, generate_plot, load_entity_list

EXPORT_ROOT = Path("export")
EXPORT_ROOT.mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

app = FastAPI(title="TopicTracker")
templates = Jinja2Templates(directory="templates")

init_db()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_export_dir(run: Run) -> Path:
    return EXPORT_ROOT / run.export_dir if run.export_dir else EXPORT_ROOT


def _redirect_login(next: str = "/") -> RedirectResponse:
    return RedirectResponse(f"/login?next={next}", status_code=302)


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(request, "login.html", {
        "next": next, "error": error,
    })


@app.post("/login")
def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse(f"/login?next={next}&error=Invalid+credentials", status_code=302)
    token = create_token(user.id)
    resp = RedirectResponse(next if next.startswith("/") else "/", status_code=302)
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=7 * 86400)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


# ── Run list ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login("/")

    if user.is_admin:
        runs = db.query(Run).order_by(Run.created_at.desc()).all()
    else:
        runs = db.query(Run).filter(Run.user_id == user.id).order_by(Run.created_at.desc()).all()

    return templates.TemplateResponse(request, "index.html", {
        "user": user, "runs": runs,
    })


# ── New run ───────────────────────────────────────────────────────────────────

@app.get("/new", response_class=HTMLResponse)
def new_run_page(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login("/new")
    current_year = datetime.now().year
    return templates.TemplateResponse(request, "new.html", {
        "user": user, "current_year": current_year,
    })


@app.post("/new")
def create_run(
    session: str | None = Cookie(default=None),
    title: str = Form(...),
    query: str = Form(...),
    year_from: int = Form(...),
    year_to: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login("/new")

    if year_from > year_to:
        year_from, year_to = year_to, year_from

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    export_dir_rel = timestamp
    export_dir = EXPORT_ROOT / export_dir_rel
    export_dir.mkdir(parents=True, exist_ok=True)

    run = Run(
        user_id=user.id,
        title=title,
        query=query,
        year_from=year_from,
        year_to=year_to,
        status="downloading",
        export_dir=export_dir_rel,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    start_download(run.id, query, year_from, year_to, export_dir)

    return RedirectResponse(f"/run/{run.id}", status_code=302)


# ── Run dashboard ─────────────────────────────────────────────────────────────

@app.get("/run/{run_id}", response_class=HTMLResponse)
def run_page(
    run_id: int,
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login(f"/run/{run_id}")

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        raise HTTPException(404, "Run not found")

    export_dir = _run_export_dir(run)
    has_analysis = (export_dir / "data").exists()

    return templates.TemplateResponse(request, "run.html", {
        "user": user,
        "run": run,
        "has_analysis": has_analysis,
        "categories": ["keywords", "mesh", "authors", "journals", "lemmas"],
        "bokeh_version": BOKEH_VERSION,
    })


# ── API: download status ──────────────────────────────────────────────────────

@app.get("/api/run/{run_id}/status")
def download_status(
    run_id: int,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        return JSONResponse({"error": "not found"}, status_code=404)

    job = get_job(run_id)
    if not job:
        # Job not in memory (server restarted?) — infer from DB status
        return JSONResponse({"status": run.status, "message": run.status, "total": 0, "downloaded": 0})

    # Sync DB status when job finishes
    if job["status"] == "done" and run.status == "downloading":
        run.status = "done_download"
        run.paper_count = job.get("paper_count")
        db.commit()
    elif job["status"] == "error" and run.status not in ("error",):
        run.status = "error"
        run.error_msg = job.get("error", "")
        db.commit()

    return JSONResponse(job)


# ── API: start analysis ───────────────────────────────────────────────────────

@app.post("/api/run/{run_id}/analyse")
def start_analysis_route(
    run_id: int,
    top_n: int = Form(300),
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        return JSONResponse({"error": "not found"}, status_code=404)

    if run.status not in ("done_download", "done"):
        return JSONResponse({"error": "Download not complete yet"}, status_code=400)

    run.status = "analysing"
    db.commit()

    export_dir = _run_export_dir(run)
    start_analysis(run_id, export_dir, top_n_network=top_n)

    return JSONResponse({"ok": True})


# ── API: analysis status ──────────────────────────────────────────────────────

@app.get("/api/run/{run_id}/analysis_status")
def analysis_status(
    run_id: int,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        return JSONResponse({"error": "not found"}, status_code=404)

    job = get_analysis_job(run_id)
    if not job:
        export_dir = _run_export_dir(run)
        if (export_dir / "data").exists():
            return JSONResponse({"status": "done", "message": "Analysis complete.", "step": 7, "steps": 7})
        return JSONResponse({"status": run.status, "message": run.status})

    if job["status"] == "done" and run.status == "analysing":
        run.status = "done"
        db.commit()
    elif job["status"] == "error":
        run.status = "error"
        run.error_msg = job.get("error", "")
        db.commit()

    return JSONResponse(job)


# ── API: entity list for autocomplete ────────────────────────────────────────

@app.get("/api/run/{run_id}/entities")
def entity_list(
    run_id: int,
    category: str,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        return JSONResponse({"error": "not found"}, status_code=404)

    export_dir = _run_export_dir(run)
    entities = load_entity_list(export_dir, category)
    return JSONResponse({"entities": entities})


# ── API: generate Bokeh plot ──────────────────────────────────────────────────

@app.post("/api/run/{run_id}/plot")
async def make_plot(
    run_id: int,
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return JSONResponse({"error": "unauthenticated"}, status_code=401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    category   = body.get("category", "keywords")
    entities   = body.get("entities", [])
    normalized = body.get("normalized", False)

    if not entities:
        return JSONResponse({"error": "No entities selected"}, status_code=400)

    export_dir = _run_export_dir(run)
    try:
        item = generate_plot(export_dir, category, entities, normalized)
        return JSONResponse({"item": item})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Static: serve SVG plots ───────────────────────────────────────────────────

@app.get("/run/{run_id}/plots/{name}")
def serve_plot(
    run_id: int,
    name: str,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        raise HTTPException(401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        raise HTTPException(404)

    path = _run_export_dir(run) / "plots" / name
    if not path.exists() or not path.suffix == ".svg":
        raise HTTPException(404)
    return FileResponse(path, media_type="image/svg+xml")


# ── Download: data/gephi CSVs ─────────────────────────────────────────────────

@app.get("/run/{run_id}/download-xlsx/{filepath:path}")
def download_xlsx(
    run_id: int,
    filepath: str,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    import io
    import pandas as pd
    user = get_user_or_none(session, db)
    if not user:
        raise HTTPException(401)
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        raise HTTPException(404)
    if ".." in filepath:
        raise HTTPException(400, "Invalid path")
    base = _run_export_dir(run)
    csv_path = base / filepath
    if not csv_path.exists():
        raise HTTPException(404)
    sep = ";" if csv_path.name == "PubMed full records.csv" else ","
    df = pd.read_csv(csv_path, sep=sep, low_memory=False)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    xlsx_name = csv_path.stem + ".xlsx"
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{xlsx_name}"'},
    )


@app.get("/run/{run_id}/download/{filepath:path}")
def download_file(
    run_id: int,
    filepath: str,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        raise HTTPException(401)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        raise HTTPException(404)

    if ".." in filepath:
        raise HTTPException(400, "Invalid path")

    base = _run_export_dir(run)
    path = base / filepath
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=path.name)


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login("/admin")
    if not user.is_admin:
        raise HTTPException(403)
    users = db.query(User).order_by(User.created_at).all()
    return templates.TemplateResponse(request, "admin.html", {"user": user, "users": users})


@app.post("/run/{run_id}/delete")
def delete_run(
    run_id: int,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user:
        return _redirect_login("/")
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run or (run.user_id != user.id and not user.is_admin):
        raise HTTPException(404)
    export_dir = _run_export_dir(run)
    db.delete(run)
    db.commit()
    import shutil
    if export_dir.exists():
        shutil.rmtree(export_dir, ignore_errors=True)
    return RedirectResponse("/", status_code=302)


@app.post("/admin/users")
def create_user(
    session: str | None = Cookie(default=None),
    email: str = Form(...),
    name: str = Form(""),
    password: str = Form(...),
    is_admin: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user or not user.is_admin:
        raise HTTPException(403)
    if db.query(User).filter(User.email == email).first():
        return RedirectResponse("/admin?error=Email+already+exists", status_code=302)
    db.add(User(email=email, name=name, password_hash=hash_password(password), is_admin=is_admin))
    db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/users/{uid}/toggle")
def toggle_user(
    uid: int,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user or not user.is_admin:
        raise HTTPException(403)
    target = db.query(User).filter(User.id == uid).first()
    if not target:
        raise HTTPException(404)
    target.is_active = not target.is_active
    db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/users/{uid}/delete")
def delete_user(
    uid: int,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    user = get_user_or_none(session, db)
    if not user or not user.is_admin:
        raise HTTPException(403)
    target = db.query(User).filter(User.id == uid).first()
    if target:
        db.delete(target)
        db.commit()
    return RedirectResponse("/admin", status_code=302)
