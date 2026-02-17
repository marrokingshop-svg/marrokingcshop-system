from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI(title="Marrokingcshop System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# conexión a postgres
def get_connection():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )

@app.get("/")
def home():
    return {
        "message": "Marrokingcshop System is Running",
        "status": "online"
    }

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

        return {
            "database": "connected",
            "time": result["now"]
        }

    except Exception as e:
        return {"database": "error", "error": str(e)}

@app.get("/create-table")
def create_table():
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
            stock INTEGER
        )
        """)

        conn.commit()
        conn.close()

        return {"status": "table created"}

    except Exception as e:
        return {"error": str(e)}

@app.post("/add-product")
def add_product(
    name: str = Body(...),
    brand: str = Body(...),
    size: str = Body(...),
    color: str = Body(...),
    price: float = Body(...),
    stock: int = Body(...)
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

        return {
            "status": "product added",
            "product_id": new_id
        }

    except Exception as e:
        return {"error": str(e)}


