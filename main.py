from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
import pymysql
from pyspark.sql import SparkSession

from shorts.router import router as shorts_router
from shorts.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(lifespan=lifespan)
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


def get_spark():
    #hive경로 
    return SparkSession.builder \
        .appName("test") \
        .master("local[*]") \
        .config("spark.sql.warehouse.dir", "hdfs://hdfs-test-namenode:9000/user/hive/warehouse") \
        .config("hive.metastore.uris", "thrift://hive-metastore:9083") \
        .enableHiveSupport() \
        .getOrCreate()


@router.get("/hdfs-write")
def hdfs_write():
    try:
        spark = get_spark()
        data = [("jihee", 1), ("test", 2)]
        df = spark.createDataFrame(data, ["name", "id"])
        path = "hdfs://hdfs-test-namenode:9000/test/sample.parquet" #테이블 저장 경로, 내맘대로 가능 
        df.write.mode("overwrite").parquet(path)
        
        spark.sql("DROP TABLE IF EXISTS test.sample")
        spark.sql(f"CREATE TABLE test.sample (name STRING, id BIGINT) USING parquet LOCATION '{path}'")
        spark.stop()
        return {"status": "success", "path": path}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/hdfs-get")
def hdfs_get():
    try:
        spark = get_spark()
        df = spark.sql("SELECT * FROM test.sample LIMIT 1")
        data = [row.asDict() for row in df.collect()]
        print(f"dicts ~~ {data}")
        spark.stop()
        name_data=data[0]['name']
        return {"status": "success", "data": name_data}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
app.include_router(router)
app.include_router(shorts_router)
