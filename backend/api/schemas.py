from pydantic import BaseModel, Field, model_validator
from typing import Optional
from utils.automation_store import STYLE_COLOR_FIELDS, STYLE_FONT_FIELDS, normalize_style

# 视觉实验室的字体和颜色字段（键名和表单、config.json 的 processing.style 一样）
STYLE_TEXT_KEYS = [*STYLE_FONT_FIELDS, *STYLE_COLOR_FIELDS]

class SubtitleRequest(BaseModel):
    video_url: str = Field(..., alias="url")
    whisper_model: str = Field("large-v3-turbo", alias="model")
    gemini_model: str = Field("gemini-3.1-flash-lite", alias="translation_model")
    target_language_code: str = Field("zh-CN", alias="target_lang")
    is_furigana_enabled: bool = Field(True, alias="enable_furigana")
    should_fix_source_text: bool = Field(True, alias="fix_source")
    # 不填就用 entry_cli 的缺省（engines/source_corrector.CORRECTION_MODEL）
    correction_model: Optional[str] = Field(None, alias="correction_model")
    segment_mode: str = Field("rule", alias="segment_mode")
    
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

    # 不填 = entry_cli 的缺省（automation_store.STYLE_DEFAULTS）
    font_main: Optional[str] = None
    font_sub: Optional[str] = None
    color_main: Optional[str] = None
    outline_color_main: Optional[str] = None
    color_sub: Optional[str] = None
    outline_color_sub: Optional[str] = None

    @model_validator(mode="after")
    def check_fonts_and_colors(self):
        """和「设为投稿样式」同一套校验：字体只能选表里对应语言的，颜色统一成 #RRGGBB。"""
        errors = []
        style = normalize_style({key: getattr(self, key) for key in STYLE_TEXT_KEYS}, errors, path="style")
        if errors:
            raise ValueError("; ".join(f"{error['path']}: {error['message']}" for error in errors))
        for key, value in style.items():
            setattr(self, key, value)
        return self

    class Config:
        populate_by_name = True
