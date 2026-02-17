from fastapi import FastAPI, Body, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

app = FastAPI(title="Marrokingcshop System")

# ===============================
# CONFIGURACIÓN SEGURIDAD
# ===============================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = "CAMBIAR_ESTO_POR_ALGO_SUPER_SEGURO"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

security = HTTPBearer()

# ===============================
# CORS
# ===============================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
# CONEXIÓN DB
# ===============================

def get_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

# ===============================
# AUTH HELPERS
# ===============================

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
        raise HTTPException(status_code=401, detail="Invalid token")

# ===============================
# SYSTEM ROUTES
# ===============================

@app.get("/")
def home():
    return {"message": "Marrokingcshop System is Running", "status": "online"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# ===============================
# PRODUCTS
# ===============================

@app.get("/create-table")
def create_table():
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
        stock INTEGER
    )
    """)

    conn.commit()
    conn.close()
    return {"status": "products table ready"}

@app.post("/add-product")
def add_product(
    name: str = Body(...),
    brand: str = Body(...),
    size: str = Body(...),
    color: str = Body(...),
    price: float = Body(...),
    stock: int = Body(...),
    user=Depends(get_current_user)
):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO products (name, brand, size, color, price, stock)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
    """, (name, brand, size, color, price, stock))

    new_id = cur.fetchone()["id"]

    conn.commit()
    conn.close()

    return {"status": "product added", "product_id": new_id}

@app.get("/products")
def get_products():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()

    conn.close()
    return {"products": products}

@app.post("/sell-product/{product_id}")
def sell_product(product_id: int, quantity: int = Body(...)):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT stock FROM products WHERE id = %s", (product_id,))
    product = cur.fetchone()

    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    if product["stock"] < quantity:
        raise HTTPException(status_code=400, detail="Stock insuficiente")

    cur.execute("""
        UPDATE products
        SET stock = stock - %s
        WHERE id = %s
    """, (quantity, product_id))

    conn.commit()
    conn.close()

    return {"status": "venta registrada"}

# ===============================
# USERS
# ===============================

@app.get("/create-users-table")
def create_users_table():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

    return {"status": "users table ready"}

@app.post("/create-user")
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: str = Body(...)
):
    conn = get_connection()
    cur = conn.cursor()

    hashed_password = pwd_context.hash(password)

    cur.execute("""
    INSERT INTO users (username, password, role)
    VALUES (%s, %s, %s)
    RETURNING id
    """, (username, hashed_password, role))

    user_id = cur.fetchone()["id"]

    conn.commit()
    conn.close()

    return {"status": "user created", "user_id": user_id}

@app.post("/login")
def login(
    username: str = Body(...),
    password: str = Body(...)
):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not pwd_context.verify(password, user["password"]):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token({
        "sub": user["username"],
        "role": user["role"]
    })

    conn.close()

    return {"access_token": token, "token_type": "bearer"}
