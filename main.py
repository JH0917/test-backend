from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter(prefix="/api_ljh")

@router.get("/hello")
def hello():
    return {"message": "Hello, World!"}

app.include_router(router)
