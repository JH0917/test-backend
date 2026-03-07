from fastapi import FastAPI, APIRouter
import pymysql
from pyspark.sql import SparkSession

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
    return {"message": "Hello, World 22!"}


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


@router.get("/hdfs-write")
def hdfs_write():
    try:
        spark = SparkSession.builder \
            .appName("test-write") \
            .master("local[*]") \
            .getOrCreate()
        data = [("jihee", 1), ("test", 2)]
        df = spark.createDataFrame(data, ["name", "id"])
        df.write.mode("overwrite").parquet("hdfs://hdfs-test:9000/test/sample.parquet")
        spark.stop()
        return {"status": "success", "path": "hdfs://hdfs-test:9000/test/sample.parquet"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


app.include_router(router)
