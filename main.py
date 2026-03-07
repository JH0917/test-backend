from fastapi import FastAPI, APIRouter
import pymysql

app = FastAPI()
router = APIRouter(prefix="/api_ljh")

DB_CONFIG = {
    "host": "host.docker.internal", #127.0.01
    "port": 3306,
    "user": "root",
    "password": "",
    "database": None,
}

def get_connection():
    return pymysql.connect(**DB_CONFIG)


@router.get("/hello")
def hello():
    return {"message": "Hello, World!"}


@router.get("/db-test")
def db_test():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("select name from testdb.test limit 1;")
            name_result = cursor.fetchone()[0]
        return {"name": name_result, "host": DB_CONFIG["host"]}
    finally:
        conn.close()


app.include_router(router)
