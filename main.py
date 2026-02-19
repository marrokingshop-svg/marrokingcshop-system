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
# CONFIGURACIÓN
# =====================================================
MELI_CLIENT_ID = "2347232636874610"
MELI_CLIENT_SECRET = "cD2NU2eSj7FX1MVGZ29QxMHZyXujia5v"
MELI_REDIRECT_URI = "https://marrokingcshop-api.onrender.com/auth/callback"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("SECRET_KEY", "MARROKING_SECRET_2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440 
security = HTTPBearer()

# =====================================================
# CORS Y SEGURIDAD DEFINITIVA
# =====================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.api_route("/{path_name:path}", methods=["OPTIONS"])
async def handle_options(request: Request, path_name: str):
    return {}

@app.get("/despertar")
def despertar():
    return {"status": "servidor despierto y listo"}

# =====================================================
# BASE DE DATOS
# =====================================================
def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL no está configurada")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)

@app.on_event("startup")
def startup_db():
    conn = get_connection()
    cur = conn.cursor()
    # Crear tablas necesarias
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT,
            price NUMERIC,
            stock INTEGER,
            meli_id TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS credentials (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        );
    """)
    conn.commit()
    conn.close()

# =====================================================
# HELPERS
# =====================================================
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
# =====================================================
# RUTA DE REPARACIÓN DE BASE DE DATOS
# =====================================================

@app.get("/repair-db")
def repair_db():
    conn = get_connection()
    cur = conn.cursor()
    try:
        # Este comando agrega la columna meli_id que falta en tu tabla
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS meli_id TEXT UNIQUE;")
        conn.commit()
        return {"status": "Base de datos reparada con éxito"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

# =====================================================
# RUTAS MERCADO LIBRE
# =====================================================

@app.get("/auth/callback")
async def meli_callback(code: str = None):
    if not code: return {"status": "error", "message": "Falta code"}
    
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
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO credentials (key, value) VALUES ('access_token', %s), ('user_id', %s) 
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (data["access_token"], str(data["user_id"])))
        conn.commit()
        conn.close()
        return {"status": "success", "message": "Conexión Exitosa. Ya puedes cerrar esta pestaña."}
    return {"status": "error", "detail": data}

@app.post("/meli/sync")
def sync_meli_products(user=Depends(get_current_user)):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT value FROM credentials WHERE key = 'access_token'")
        token = cur.fetchone()['value']
        cur.execute("SELECT value FROM credentials WHERE key = 'user_id'")
        user_id = cur.fetchone()['value']
        
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Pedir IDs activos
        search_url = f"https://api.mercadolibre.com/users/{user_id}/items/search?status=active"
        response = requests.get(search_url, headers=headers)
        items_ids = response.json().get("results", [])

        count = 0
        for m_id in items_ids:
            detail_resp = requests.get(f"https://api.mercadolibre.com/items/{m_id}", headers=headers)
            if detail_resp.status_code == 200:
                item = detail_resp.json()
                
                # Procesamos tanto productos simples como variantes
                products_to_process = []
                if item.get("variations"):
                    for var in item["variations"]:
                        var_attrs = " - ".join([attr["value_name"] for attr in var["attribute_combinations"]])
                        products_to_process.append({
                            "name": f"{item['title']} ({var_attrs})",
                            "price": item.get("price"),
                            "stock": var.get("available_quantity"),
                            "meli_id": f"{m_id}-{var['id']}" # ID único para variante
                        })
                else:
                    products_to_process.append({
                        "name": item.get("title"),
                        "price": item.get("price"),
                        "stock": item.get("available_quantity"),
                        "meli_id": m_id
                    })

                for p in products_to_process:
                    # UPSERT: Si el meli_id ya existe, actualiza. Si no, inserta.
                    cur.execute("""
                        INSERT INTO products (name, price, stock, meli_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (meli_id) 
                        DO UPDATE SET 
                            name = EXCLUDED.name,
                            price = EXCLUDED.price,
                            stock = EXCLUDED.stock;
                    """, (p["name"], p["price"], p["stock"], p["meli_id"]))
                    count += 1

        conn.commit()
        return {"status": "sincronizado", "items": count}

    except Exception as e:
        if conn: conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn: conn.close()

# =====================================================
# RUTAS GENERALES
# =====================================================

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
    conn.close()
    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")
    token = create_access_token({"sub": user["username"], "role": user["role"]})
    return {"access_token": token, "token_type": "bearer"}
