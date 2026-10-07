import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import api_router
from api.automation_routes import automation_router
from config.settings import FRONTEND_DIST, DOWNLOADS_DIR, AUTOMATION_OUTPUT_DIR

web_application_instance = FastAPI()

web_application_instance.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@web_application_instance.middleware("http")
async def inject_security_and_wasm_headers(http_request, next_handler):
    http_response = await next_handler(http_request)
    http_response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    http_response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    http_response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    return http_response

web_application_instance.include_router(api_router, prefix="/api")
# 「自动搬运」页面：状态、配置、投稿队列、B 站账号（和 mover 通过 userdata 下的文件协作）
web_application_instance.include_router(automation_router, prefix="/api/automation")
web_application_instance.mount("/api/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")
# 自动搬运的成品，媒体库里标「自动搬运」的那些（api/routes.py 的 LIBRARY_SOURCES）
web_application_instance.mount("/api/outputs", StaticFiles(directory=str(AUTOMATION_OUTPUT_DIR)), name="outputs")

if FRONTEND_DIST.exists():
    web_application_instance.mount("/_next", StaticFiles(directory=str(FRONTEND_DIST / "_next")), name="next_static")
    
    @web_application_instance.api_route("/{file_path:path}", methods=["GET", "HEAD", "OPTIONS"])
    async def serve_frontend_assets_and_spa(file_path: str):
        if file_path.startswith("api"): 
            return None
            
        requested_resource_path = FRONTEND_DIST / file_path.split("?")[0]
        if requested_resource_path.exists() and requested_resource_path.is_file():
            return FileResponse(requested_resource_path)
            
        return FileResponse(FRONTEND_DIST / "index.html")

if __name__ == "__main__":
    uvicorn.run(web_application_instance, host="0.0.0.0", port=8501)
