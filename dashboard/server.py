from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn
import sys
import json

# Fix paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from core.settings_manager import settings_manager
except ImportError:
    settings_manager = None
    print("Warning: settings_manager not found")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return FileResponse("dashboard/index.html")

@app.get("/api/state")
def get_state():
    state_file = "outputs/mind_state.json"
    if os.path.exists(state_file):
        return FileResponse(state_file)
    return {"error": "No state found"}

@app.get("/api/settings")
def get_settings():
    if settings_manager:
        settings_manager.load()
        return settings_manager.get_all()
    return {}

@app.post("/api/settings")
async def update_settings(request: Request):
    if not settings_manager:
        return {"status": "error", "message": "Settings manager offline"}
    try:
        data = await request.json()
        settings_manager.update_all(data)
        return {"status": "success", "settings": settings_manager.get_all()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/chat")
async def send_chat(request: Request):
    try:
        data = await request.json()
        msg = data.get("message", "").strip()
        if msg:
            from config import Config
            import os, json
            out_path = os.path.join(Config.OUTPUT_DIR, "web_chat_in.txt")
            with open(out_path, "a", encoding="utf-8") as f:
                json.dump({"role": "user", "content": msg}, f, ensure_ascii=False)
                f.write("\n")
        return {"status": "success"}
    except Exception as e:
        return {"status": "error"}

@app.get("/api/chat")
def get_chat():
    out = []
    try:
        from config import Config
        import os, json
        in_path = os.path.join(Config.OUTPUT_DIR, "web_chat_out.txt")
        if os.path.exists(in_path):
            with open(in_path, "r", encoding="utf-8") as f:
                lines = f.read().strip().split('\n')
            open(in_path, "w").close() # Clear file
            for line in lines:
                if line.strip():
                    out.append(json.loads(line))
    except:
        pass
    return {"messages": out}

def run_dashboard():
    uvicorn.run(app, host="127.0.0.1", port=8050)

if __name__ == "__main__":
    run_dashboard()
