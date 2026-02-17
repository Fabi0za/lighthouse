import uvicorn

from app.dependencies import build_dependencies
from app.main import create_app

deps = build_dependencies()
app = create_app(**deps)

if __name__ == "__main__":
    uvicorn.run("run:app", host="0.0.0.0", port=8000, reload=True)
