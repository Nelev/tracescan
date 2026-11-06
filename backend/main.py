from fastapi import FastAPI

app = FastAPI(title="TraceScan")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
