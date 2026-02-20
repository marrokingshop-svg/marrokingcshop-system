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
# CORS
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

@app.get("/health")
def health():
    return {"status": "online"}

# =====================================================
# BASE DE DATOS
# =====================================================
def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("DATABASE_URL no configurada")
    return psycopg2.connect(database_url, cursor_factory=RealDictCursor)

@app.on_event("startup")
def startup_db():
    conn = get_connection()
    cur = conn.cursor()

    # ============================
    # TABLA PRODUCTS (base)
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT,
            price NUMERIC,
            stock INTEGER,
            meli_id TEXT UNIQUE,
            status TEXT DEFAULT 'active'
        );
    """)

    # ============================
    # AGREGAR COLUMNAS NUEVAS (si no existen)
    # ============================
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS item_id TEXT;")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS variation_id TEXT;")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS attributes TEXT;")
    cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_url TEXT;")

    # ============================
    # CREDENTIALS
    # ============================
    cur.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    # ============================
    # USERS
    # ============================
    cur.execute("""
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
# SEGURIDAD
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
# AUTH MERCADO LIBRE
# =====================================================
@app.get("/auth/callback")
async def meli_callback(code: str = None):
    if not code:
        return {"status": "error", "message": "Falta code"}

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
            INSERT INTO credentials (key, value)
            VALUES ('access_token', %s), ('user_id', %s)
            ON CONFLICT (key)
            DO UPDATE SET value = EXCLUDED.value
        """, (data["access_token"], str(data["user_id"])))

        conn.commit()
        conn.close()

        return {"status": "success", "message": "Conectado a Mercado Libre"}

    return {"status": "error", "detail": data}

# =====================================================
# SINCRONIZAR PRODUCTOS (VERSIÓN CORREGIDA)
# =====================================================
@app.post("/meli/sync")
def sync_meli_products(user=Depends(get_current_user)):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Obtener credenciales
        cur.execute("SELECT value FROM credentials WHERE key='access_token'")
        token_row = cur.fetchone()
        cur.execute("SELECT value FROM credentials WHERE key='user_id'")
        user_row = cur.fetchone()

        if not token_row or not user_row:
            raise HTTPException(status_code=400, detail="Mercado Libre no vinculado")

        token = token_row["value"]
        user_id = user_row["value"]

        headers = {"Authorization": f"Bearer {token}"}

        # =====================================================
        # OBTENER TODOS LOS ITEMS (SCAN REAL)
        # =====================================================
        items_ids = []
        url = f"https://api.mercadolibre.com/users/{user_id}/items/search"

        params = {
            "search_type": "scan",
            "limit": 100
        }

        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        scroll_id = data.get("scroll_id")
        items_ids.extend(data.get("results", []))

        while True:
            params = {
                "search_type": "scan",
                "scroll_id": scroll_id
            }

            response = requests.get(url, headers=headers, params=params)
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            items_ids.extend(results)
            scroll_id = data.get("scroll_id")

        # =====================================================
        # GUARDAR PRODUCTOS
        # =====================================================
        count = 0

        for m_id in items_ids:
            detail_resp = requests.get(
                f"https://api.mercadolibre.com/items/{m_id}",
                headers=headers
            )

            if detail_resp.status_code != 200:
                continue

            item = detail_resp.json()
            status = item.get("status", "active")

            products_to_process = []

            if item.get("variations"):
                for var in item["variations"]:
                    attrs = " - ".join(
                        [a["value_name"] for a in var["attribute_combinations"]]
                    )

                    products_to_process.append({
                        "name": f"{item['title']} ({attrs})",
                        "price": item.get("price"),
                        "stock": var.get("available_quantity"),
                        "meli_id": f"{m_id}-{var['id']}",
                        "status": status
                    })
            else:
                products_to_process.append({
                    "name": item.get("title"),
                    "price": item.get("price"),
                    "stock": item.get("available_quantity"),
                    "meli_id": m_id,
                    "status": status
                })

            for p in products_to_process:
                cur.execute("""
                    INSERT INTO products (name, price, stock, meli_id, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (meli_id)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        price = EXCLUDED.price,
                        stock = EXCLUDED.stock,
                        status = EXCLUDED.status;
                """, (
                    p["name"],
                    p["price"],
                    p["stock"],
                    p["meli_id"],
                    p["status"]
                ))
                count += 1

        conn.commit()
        return {
            "status": "sincronizado",
            "total_items_meli": len(items_ids),
            "productos_guardados": count
        }

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()

# =====================================================
# PRODUCTOS
# =====================================================
@app.get("/products-grouped")
def get_products_grouped():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT name, price, stock, meli_id, status
        FROM products
        ORDER BY name
    """)

    rows = cur.fetchall()
    conn.close()

    grouped = {}

    for r in rows:
        # Obtener ID principal de Mercado Libre
        base_id = r["meli_id"].split("-")[0]

        if base_id not in grouped:
            grouped[base_id] = {
                "meli_item_id": base_id,
                "title": r["name"].split("(")[0].strip(),
                "status": r["status"],
                "variations": []
            }

        grouped[base_id]["variations"].append({
            "name": r["name"],
            "price": r["price"],
            "stock": r["stock"],
            "meli_id": r["meli_id"]
        })

    return {"products": list(grouped.values())}
# =====================================================
# LOGIN
# =====================================================
@app.post("/login")
def login(username: str = Body(...), password: str = Body(...)):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    conn.close()

    if not user or not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=400, detail="Credenciales inválidas")

    token = create_access_token({
        "sub": user["username"],
        "role": user["role"]
    })

    return {"access_token": token, "token_type": "bearer"}
