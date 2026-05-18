from pydantic import BaseModel, Field
from typing import Optional

class SubtitleRequest(BaseModel):
    video_url: str = Field(..., alias="url")
    whisper_model: str = Field("large-v3", alias="model")
    gemini_model: str = Field("gemini-3.1-flash-lite", alias="translation_model")
    target_language_code: str = Field("zh-CN", alias="target_lang")
    is_furigana_enabled: bool = Field(True, alias="enable_furigana")
    should_fix_source_text: bool = Field(False, alias="fix_source")
    
    font_size_main: int = 90
    main_subtitle_bottom_margin: float = Field(0.7, alias="main_bottom")
    main_font_opacity: int = Field(100, alias="font_alpha")
    main_outline_opacity: int = Field(100, alias="outline_alpha")
    main_font_weight: int = Field(700, alias="font_weight")
    main_outline_thickness: float = Field(3.0, alias="outline_main")
    main_shadow_depth: float = Field(1.5, alias="shadow_main")
    
    font_size_sub: int = 75
    secondary_subtitle_bottom_margin: float = Field(92.1, alias="sub_bottom")
    secondary_font_opacity: int = Field(100, alias="sub_alpha")
    secondary_outline_opacity: int = Field(100, alias="outline_sub_alpha")
    secondary_font_weight: int = Field(400, alias="font_weight_sub")
    secondary_outline_thickness: float = Field(2.0, alias="outline_sub")
    secondary_shadow_depth: float = Field(1.5, alias="shadow_sub")

    class Config:
        populate_by_name = True
