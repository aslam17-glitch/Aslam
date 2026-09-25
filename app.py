import os
import io
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from PIL import Image

from fastapi import (
    FastAPI, HTTPException, Depends, File, UploadFile,
    Form, Request, status, Cookie
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv
import asyncio
from pathlib import Path

load_dotenv()

from gemini_utils import (
    get_home_recommendations,
    get_party_recommendations,
    get_jewelry_recommendations
)

# App Setup
app = FastAPI(title="PocketSmart: AI Budget Planner")

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(BASE_DIR / "static" / "uploads", exist_ok=True)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# In-Memory DB & Sessions (Easily replacable with SQLite or MongoDB)
users_db: Dict[str, dict] = {}
active_sessions: Dict[str, dict] = {}
blacklisted_tokens = set()
user_recommendations: Dict[str, List[dict]] = {}

# Pydantic Models
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None
    password: str

# Helpers
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user_from_token(token: Optional[str]) -> Optional[str]:
    if not token or token in blacklisted_tokens:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username and username in users_db:
            return username
    except JWTError:
        return None
    return None

async def get_logged_in_user(request: Request) -> Optional[str]:
    token = request.cookies.get("access_token")
    return await get_current_user_from_token(token)

def save_to_history(username: str, rec_type: str, input_summary: dict, full_result: dict):
    if username not in user_recommendations:
        user_recommendations[username] = []
    
    history_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%b %d, %Y - %I:%M %p"),
        "type": rec_type,
        "input": input_summary,
        "result": full_result
    }
    user_recommendations[username].insert(0, history_entry)

# Background Task for Expired Session Cleanup
@app.on_event("startup")
async def setup_session_cleanup():
    async def cleanup_task():
        while True:
            await asyncio.sleep(300)
            now = datetime.utcnow()
            expired = [
                uname for uname, sess in active_sessions.items()
                if (now - sess.get("last_activity", now)).total_seconds() > 1800
            ]
            for uname in expired:
                del active_sessions[uname]
    asyncio.create_task(cleanup_task())

# Auth Routes
@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = await get_logged_in_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "register.html", {"user": None})

@app.post("/register")
async def register_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    if password != confirm_password:
        return templates.TemplateResponse(request, "register.html", {"user": None, "error": "Passwords do not match"})
    if len(password.encode("utf-8")) < 8:
        return templates.TemplateResponse(request, "register.html", {"user": None, "error": "Password must be at least 8 characters"})
    if len(password.encode("utf-8")) > 72:
        return templates.TemplateResponse(request, "register.html", {"user": None, "error": "Password must be 72 bytes or fewer"})
    if username in users_db:
        return templates.TemplateResponse(request, "register.html", {"user": None, "error": "Username already taken"})
    
    users_db[username] = {
        "username": username,
        "email": email,
        "hashed_password": get_password_hash(password)
    }
    return RedirectResponse(url="/login?registered=1", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_logged_in_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"user": None})

@app.post("/login")
async def login_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = users_db.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return templates.TemplateResponse(request, "login.html", {"user": None, "error": "Invalid username or password"})
    
    token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    active_sessions[username] = {
        "token": token,
        "login_time": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
        "user_data": {}
    }
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("access_token")
    user = await get_current_user_from_token(token) if token else None
    if token:
        blacklisted_tokens.add(token)
    if user and user in active_sessions:
        del active_sessions[user]
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="access_token")
    return response

# Main Navigation
@app.get("/", response_class=HTMLResponse)
async def home_landing(request: Request):
    user = await get_logged_in_user(request)
    return templates.TemplateResponse(request, "index.html", {"user": user})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    history = user_recommendations.get(user, [])[:3]
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "history": history})

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    history = user_recommendations.get(user, [])
    return templates.TemplateResponse(request, "history.html", {"user": user, "history": history})

# Planners
@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner_page(request: Request):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "home_planner.html", {"user": user})

@app.post("/generate-home", response_class=HTMLResponse)
async def generate_home_plan(
    request: Request,
    total_budget: float = Form(...),
    num_lights: int = Form(0),
    num_fans: int = Form(0),
    num_furniture: int = Form(0),
    num_dining_tables: int = Form(0),
    living_room: Optional[str] = Form(None),
    kitchen: Optional[str] = Form(None),
    bedroom: Optional[str] = Form(None),
    additional_requirements: Optional[str] = Form("")
):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    rooms = []
    if living_room: rooms.append("Living Room")
    if kitchen: rooms.append("Kitchen")
    if bedroom: rooms.append("Bedroom")

    try:
        result = get_home_recommendations(
            budget=total_budget,
            lights=num_lights,
            fans=num_fans,
            furniture=num_furniture,
            dining_tables=num_dining_tables,
            rooms=rooms,
            requirements=additional_requirements
        )
    except Exception as exc:
        return templates.TemplateResponse(request, "home_planner.html", { "user": user, "result": None,
            "input_budget": total_budget,
            "error": f"Could not generate the AI plan. {str(exc)}"
        }, status_code=502)

    input_summary = {
        "budget": f"₹{total_budget:,.2f}",
        "rooms": ", ".join(rooms) if rooms else "General",
        "fixtures": f"{num_lights} Lights, {num_fans} Fans, {num_furniture} Furniture"
    }
    save_to_history(user, "Home Interior", input_summary, result)

    return templates.TemplateResponse(request, "home_planner.html", {
        "user": user,
        "result": result,
        "input_budget": total_budget
    })

@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner_page(request: Request):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "party_planner.html", {"user": user})

@app.post("/generate-party", response_class=HTMLResponse)
async def generate_party_plan(
    request: Request,
    total_budget: float = Form(...),
    num_guests: int = Form(...),
    party_type: str = Form(...),
    venue_type: str = Form(...),
    catering: Optional[str] = Form(None),
    decoration: Optional[str] = Form(None),
    entertainment: Optional[str] = Form(None),
    additional_requirements: Optional[str] = Form("")
):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    needs_cat = catering is not None
    needs_dec = decoration is not None
    needs_ent = entertainment is not None

    try:
        result = get_party_recommendations(
            budget=total_budget,
            guests=num_guests,
            event_type=party_type,
            venue_type=venue_type,
            needs_catering=needs_cat,
            needs_decoration=needs_dec,
            needs_entertainment=needs_ent,
            requirements=additional_requirements
        )
    except Exception as exc:
        return templates.TemplateResponse(request, "party_planner.html", { "user": user, "result": None,
            "input_budget": total_budget,
            "error": f"Could not generate the AI plan. {str(exc)}"
        }, status_code=502)

    input_summary = {
        "budget": f"₹{total_budget:,.2f}",
        "party_type": party_type,
        "guests": num_guests
    }
    save_to_history(user, "Party Planning", input_summary, result)

    return templates.TemplateResponse(request, "party_planner.html", {
        "user": user,
        "result": result,
        "input_budget": total_budget
    })

@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner_page(request: Request):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "jewelry_planner.html", {"user": user})

@app.post("/generate-jewelry", response_class=HTMLResponse)
async def generate_jewelry_plan(
    request: Request,
    total_budget: float = Form(...),
    occasion: str = Form(...),
    style_preferences: Optional[str] = Form(""),
    outfit_image: Optional[UploadFile] = File(None)
):
    user = await get_logged_in_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    pil_image = None
    has_image = False
    if outfit_image and outfit_image.filename:
        try:
            image_data = await outfit_image.read()
            if len(image_data) > 10 * 1024 * 1024:
                raise ValueError("Image must be smaller than 10 MB")
            pil_image = Image.open(io.BytesIO(image_data)).convert("RGB")
            has_image = True
        except Exception as exc:
            return templates.TemplateResponse(request, "jewelry_planner.html", {
                "user": user, "result": None,
                "input_budget": total_budget,
                "error": f"Invalid outfit image: {str(exc)}"
            }, status_code=400)

    try:
        result = get_jewelry_recommendations(
            budget=total_budget,
            occasion=occasion,
            style_preferences=style_preferences,
            image=pil_image
        )
    except Exception as exc:
        return templates.TemplateResponse(request, "jewelry_planner.html", { "user": user, "result": None,
            "input_budget": total_budget,
            "error": f"Could not generate the AI plan. {str(exc)}"
        }, status_code=502)

    input_summary = {
        "budget": f"₹{total_budget:,.2f}",
        "occasion": occasion,
        "outfit_image": "Yes" if has_image else "No"
    }
    save_to_history(user, "Jewelry Matching", input_summary, result)

    return templates.TemplateResponse(request, "jewelry_planner.html", {
        "user": user,
        "result": result,
        "input_budget": total_budget
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)