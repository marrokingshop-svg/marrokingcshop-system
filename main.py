from fastapi import FastAPI, Body, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

app = FastAPI(title="Marrokingcshop System Pro")

# =====================================================
# CONFIGURACIÓN DE MERCADO LIBRE
# =====================================================
MELI_CLIENT_ID = "2347232636874610"
MELI_CLIENT_SECRET = "cD2NU2eSj7FX1MVGZ29QxMHZyXujia5v"
MELI_REDIRECT_URI = "https://marrokingcshop-api.onrender.com/auth/callback"

# =====================================================
# CONFIGURACIÓN DE SEGURIDAD
# =====================================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("SECRET_KEY", "MARROKING_SECRET_2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 # 24 horas
security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://marrokingshop-svg.github.io",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# =====================================================
# CONEXIÓN A BASE DE DATOS
# =====================================================
def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL no está configurada")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)

# =====================================================
# HELPERS AUTH
# =====================================================
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")

# =====================================================
# RUTAS DE MERCADO LIBRE
# =====================================================

@app.get("/auth/callback")
async def meli_callback(code: str = None):
    if not code:
        return {"status": "error", "message": "Falta el código de autorización"}
    
    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": MELI_CLIENT_ID,
        "client_secret": MELI_CLIENT_SECRET,
        "code": code,
        "redirect_uri": MELI_REDIRECT_URI
    }
    
    resp = requests.post(url, data=payload)
    data = resp.json()
    
    if "access_token" in data:
        os.environ["MELI_ACCESS_TOKEN"] = data["access_token"]
        os.environ["MELI_USER_ID"] = str(data["user_id"])
        return {"status": "success", "message": "¡Conexión Exitosa con Mercado Libre! Ya puedes volver a tu ERP."}
    return {"status": "error", "detail": data}

@app.post("/meli/sync")
def sync_meli_products(user=Depends(get_current_user)):
    token = os.environ.get("MELI_ACCESS_TOKEN")
    user_id = os.environ.get("MELI_USER_ID")
    
    if not token:
        raise HTTPException(status_code=400, detail="Debes vincular tu cuenta de ML primero")

    headers = {"Authorization": f"Bearer {token}"}
    search_url = f"https://api.mercadolibre.com/users/{user_id}/items/search"
    items_ids = requests.get(search_url, headers=headers).json().get("results", [])

    conn = get_connection()
    cur = conn.cursor()
    
    count = 0
    for m_id in items_ids:
        detail = requests.get(f"https://api.mercadolibre.com/items/{m_id}", headers=headers).json()
        cur.execute("""
            INSERT INTO products (name, price, stock, meli_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (meli_id) DO UPDATE 
            SET name = EXCLUDED.name, price = EXCLUDED.price, stock = EXCLUDED.stock;
        """, (detail.get("title"), detail.get("price"), detail.get("available_quantity"), m_id))
        count += 1

    conn.commit()
    conn.close()
    return {"status": "sincronizado", "items": count}

# =====================================================
# RUTAS DE PRODUCTOS Y TABLAS
# =====================================================

@app.get("/create-products-table")
def create_products_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT,
            brand TEXT,
            size TEXT,
            color TEXT,
            price NUMERIC,
            stock INTEGER,
            meli_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return {"status": "Tabla actualizada"}

@app.get("/products")
def get_products():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    res = cur.fetchall()
    conn.close()
    return {"products": res}

@app.get("/health")
def health(): return {"status": "online"}

@app.post("/login")
def login(username: str = Body(...), password: str = Body(...)):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/create-user")
def create_user(username: str = Body(...), password: str = Body(...), role: str = Body(...)):
    conn = get_connection()
    cur = conn.cursor()
    hashed = pwd_context.hash(password)
    cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (username, hashed, role))
    conn.commit()
    conn.close()
    return {"status": "user created"}
