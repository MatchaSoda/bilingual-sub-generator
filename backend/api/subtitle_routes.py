"""视觉实验室：可选字体和预览图（预览用压制成片的同一套代码渲染，见 services/subtitle_preview.py）。"""
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from services.subtitle_preview import MAX_TEXT_LENGTH, SAMPLE_TEXT, PreviewError, render_preview
from utils import automation_store as store
from utils import subtitle_fonts

subtitle_router = APIRouter()


@subtitle_router.get("/fonts")
def list_fonts():
    return {
        "fonts": subtitle_fonts.catalog(),
        "style_defaults": store.STYLE_DEFAULTS,
        "sample_text": SAMPLE_TEXT,
        "max_text_length": MAX_TEXT_LENGTH,
    }


class PreviewRequest(BaseModel):
    style: Optional[dict] = None
    background: str = "dark"   # dark / light / video（最近下载的源视频的一帧）
    furigana: bool = True
    main_text: Optional[str] = None
    sub_text: Optional[str] = None


@subtitle_router.post("/preview")
def preview(request: PreviewRequest):
    try:
        png, source = render_preview(request.style, request.background, request.furigana,
                                     request.main_text, request.sub_text)
    except PreviewError as error:
        return JSONResponse(status_code=error.status, content={"detail": str(error), "errors": error.errors})
    # 背景用的是哪个视频（文件名是日文，响应头只能放 ASCII，所以 URL 编码）
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Preview-Source": quote(source)})
