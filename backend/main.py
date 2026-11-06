from fastapi import FastAPI

from api.runs import router as runs_router

app = FastAPI(title="TraceScan")
app.include_router(runs_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
