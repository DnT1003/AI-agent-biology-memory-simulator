from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
import os
import uvicorn

app = FastAPI()

@app.get("/")
def read_root():
    return FileResponse("dashboard/index.html")

@app.get("/api/state")
def get_state():
    state_file = "outputs/mind_state.json"
    if os.path.exists(state_file):
        return FileResponse(state_file)
    return {"error": "No state found"}

def run_dashboard():
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    run_dashboard()
