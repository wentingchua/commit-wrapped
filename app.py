"""FastAPI web app for GitHub Commit Wrapped."""

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from analyser import run_analysis

load_dotenv()

app = FastAPI(title="Commit Wrapped")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-please-change-in-production")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=3600)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/callback")
GITHUB_OAUTH_SCOPE = "public_repo read:user"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = request.session.get("user")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"user": user, "error": error},
    )


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login():
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID not configured.")
    url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope={GITHUB_OAUTH_SCOPE}"
        "&allow_signup=false"
    )
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?error=oauth_cancelled")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
    token_data = token_resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return RedirectResponse("/?error=token_exchange_failed")

    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
    user_data = user_resp.json()

    request.session["token"] = access_token
    request.session["user"] = {
        "login": user_data["login"],
        "name": user_data.get("name") or user_data["login"],
        "avatar_url": user_data.get("avatar_url", ""),
    }
    return RedirectResponse("/")


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


# ---------------------------------------------------------------------------
# Analysis API
# ---------------------------------------------------------------------------

@app.get("/api/analyse")
async def analyse(request: Request, days: int = 30):
    token = request.session.get("token")
    user = request.session.get("user")

    if not token or not user:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    if not (1 <= days <= 365):
        raise HTTPException(status_code=400, detail="days must be between 1 and 365.")

    try:
        result = await asyncio.to_thread(run_analysis, token, user["login"], days)
        return JSONResponse(result)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")
