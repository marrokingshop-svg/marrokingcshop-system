from fastapi import FastAPI
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

# test conexión a base de datos
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
        return {
            "database": "error",
            "error": str(e)
        }
