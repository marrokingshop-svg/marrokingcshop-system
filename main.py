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

# =====================================================
# CONFIGURACIÓN DE SEGURIDAD
# =====================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12
)


SECRET_KEY = os.environ.get("SECRET_KEY", "CAMBIAR_ESTO_POR_ALGO_SUPER_SEGURO")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

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
)

# =====================================================
# CONEXIÓN A BASE DE DATOS
# =====================================================

def get_connection():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise Exception("DATABASE_URL no está configurada en Render")

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor
    )

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
# RUTAS SISTEMA
# =====================================================

@app.get("/")
def home():
    return {"message": "Marrokingcshop System is Running", "status": "online"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/db-test")
def db_test():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT NOW()")
        result = cur.fetchone()
        conn.close()
        return {"database": "connected", "time": result["now"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# PRODUCTOS
# =====================================================

@app.get("/create-products-table")
def create_products_table():
    try:
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()
        conn.close()

        return {"status": "products table ready"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    try:
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/products")
def get_products():
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM products ORDER BY id DESC")
        products = cur.fetchall()

        conn.close()

        return {"products": products}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sell-product/{product_id}")
def sell_product(product_id: int, quantity: int = Body(...)):
    try:
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# USUARIOS
# =====================================================

@app.get("/create-users-table")
def create_users_table():
    try:
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/create-user")
def create_user(
    username: str = Body(...),
    password: str = Body(...),
    role: str = Body(...)
):
    try:
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

    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="El usuario ya existe")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/login")
def login(
    username: str = Body(...),
    password: str = Body(...)
):
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

        if not user:
            raise HTTPException(status_code=400, detail="Credenciales inválidas")

        if not pwd_context.verify(password, user["password"]):
            raise HTTPException(status_code=400, detail="Credenciales inválidas")

        token = create_access_token({
            "sub": user["username"],
            "role": user["role"]
        })

        conn.close()

        return {"access_token": token, "token_type": "bearer"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
