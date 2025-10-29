import os
os.system("pip install streamlit reportlab pillow xlsxwriter")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식 - 가로 한줄 UI + PDF/엑셀(1페이지 인쇄) 출력

import io
import re
import unicodedata
import uuid
from math import ceil
from typing import List, Tuple, Optional

import streamlit as st
from PIL import Image

# ReportLab (PDF)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식", layout="wide")

# ─────────────────────────────────────────
# 폰트 등록 (한글 깨짐 방지)
# ─────────────────────────────────────────
def try_register_font():
    candidates = [
        ("NanumGothic", "NanumGothic.ttf"),
        ("MalgunGothic", "C:\\Windows\\Fonts\\malgun.ttf"),
        ("MalgunGothic", "C:/Windows/Fonts/malgun.ttf"),
    ]
    for family, path in candidates:
        try:
            import os as _os
            if _os.path.exists(path):
                pdfmetrics.registerFont(TTFont(family, path))
                return family, True
        except Exception:
            pass
    return "Helvetica", False

BASE_FONT, FONT_OK = try_register_font()
if not FONT_OK:
    st.warning("⚠️ 한글 폰트 임베드 실패. 실행 폴더에 NanumGothic.ttf 파일을 넣으면 한글이 정상 표시됩니다.")

# 스타일 설정
ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(name="title", parent=ss["Heading1"], fontName=BASE_FONT,
                            fontSize=18, leading=22, alignment=1, spaceAfter=8),
    "cell": ParagraphStyle(name="cell", parent=ss["Normal"], fontName=BASE_FONT,
                           fontSize=10, leading=13),
    "small_center": ParagraphStyle(name="small_center", parent=ss["Normal"], fontName=BASE_FONT,
                                   fontSize=8.5, leading=11, alignment=1),
}

# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".")
    return name or "output"

def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4/3) -> Image.Image:
    """이미지 비율을 target_ratio로 맞추기 위해 흰색 패딩 추가"""
    w, h = img.size
    cur_ratio = w / h
    if abs(cur_ratio - target_ratio) < 1e-3:
        return img

    if cur_ratio > target_ratio:
        new_h = int(round(w / target_ratio))
        new_w = w
    else:
        new_w = int(round(h * target_ratio))
        new_h = h

    canvas = Image.new("RGB", (new_w, new_h), (255, 255, 255))
    paste_x = (new_w - w) // 2
    paste_y = (new_h - h) // 2
    canvas.paste(img, (paste_x, paste_y))
    return canvas

def _resize_for_pdf(img: Image.Image, max_px: int = 1400) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_px:
        return img
    if w >= h:
        new_w = max_px
        new_h = int(h * (max_px / w))
    else:
        new_h = max_px
        new_w = int(w * (max_px / h))
    return img.resize((new_w, new_h))

def _pil_to_bytesio(img: Image.Image, quality=85) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────
# PDF 빌더
# ─────────────────────────────────────────
def build_pdf(doc_title: str, site_addr: str, items: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    LEFT_RIGHT_MARGIN = 20
    TOP_BOTTOM_MARGIN = 20
    RIGHT_MARGIN = LEFT_RIGHT_MARGIN

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=TOP_BOTTOM_MARGIN,
        bottomMargin=TOP_BOTTOM_MARGIN,
        leftMargin=LEFT_RIGHT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        title=doc_title
    )

    story = []
    story.append(Paragraph(doc_title, styles["title"]))
    story.append(Spacer(1, 4))

    meta_tbl = Table(
        [[Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr.strip() or "-", styles["cell"])]],
        colWidths=[80, PAGE_W - 2*LEFT_RIGHT_MARGIN - 80]
    )
    meta_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.9, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 6))

    col_count = 3
    usable_width = PAGE_W - 2*LEFT_RIGHT_MARGIN
    col_width = usable_width / col_count
    n = min(len(items), 9)
    rows = ceil(n / col_count)

    ROW_HEIGHT = 200 if rows >= 3 else (230 if rows == 2 else 260)
    CAPTION_HEIGHT = 22
    IMAGE_MAX_H = ROW_HEIGHT - CAPTION_HEIGHT - 8
    IMAGE_MAX_W = col_width - 8

    cells = []
    for label, pil_img in items[:9]:
        if pil_img is not None:
            pil_img = enforce_aspect_pad(pil_img, 4/3)
            img_resized = _resize_for_pdf(pil_img, max_px=1400)
            bio = _pil_to_bytesio(img_resized, quality=85)
            target_w = IMAGE_MAX_W
            target_h = target_w * 3 / 4
            if target_h > IMAGE_MAX_H:
                target_h = IMAGE_MAX_H
                target_w = target_h * 4 / 3

            rl_img = RLImage(bio, width=target_w, height=target_h)
            rl_img.hAlign = "CENTER"
            cell = Table(
                [[rl_img], [Paragraph(label, styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
        else:
            cell = Table(
                [[Paragraph("(사진 없음)", styles["small_center"])],
                 [Paragraph(label, styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
        cells.append(cell)

    while len(cells) % col_count != 0:
        cells.append(
            Table(
                [[Paragraph("(빈 칸)", styles["small_center"])],
                 [Paragraph("-", styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
        )

    grid_rows = [cells[i*col_count:(i+1)*col_count] for i in range(len(cells)//col_count)]
    grid_tbl = Table(grid_rows, colWidths=[col_width]*col_count, rowHeights=[ROW_HEIGHT]*len(grid_rows))
    story.append(grid_tbl)

    doc.build(story)
    return buf.getvalue()

# ─────────────────────────────────────────
# 세션 상태
# ─────────────────────────────────────────
PHOTOS_KEY = "photos"

if PHOTOS_KEY not in st.session_state:
    st.session_state[PHOTOS_KEY] = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": ""}]
if "mode" not in st.session_state:
    st.session_state.mode = "캐스케이드"

# 옵션
CASCADE_OPTIONS = [
    "장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공",
    "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"
]
VENT_OPTIONS = ["직접입력"]
MAX_PHOTOS = 9

# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
st.markdown("### 캐스케이드/환기 기성 청구 양식")
mode = st.radio("양식 선택", ["캐스케이드", "환기"], horizontal=True)
st.session_state.mode = mode
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
site_addr = st.text_input("현장 주소", placeholder="예: 서울특별시 ○○구 ○○로 12, 101동 101호")

photos = st.session_state[PHOTOS_KEY]
to_delete_ids = []

for idx, item in enumerate(photos):
    item_id = item["id"]
    row = st.columns([2.2, 0.6, 2.2, 2.0, 1.0])
    with row[0]:
        up = st.file_uploader("📷 사진", type=["jpg", "jpeg", "png"], key=f"fu_{item_id}")
    with row[1]:
        st.markdown(f"**{idx+1}.**")
    with row[2]:
        choice = st.selectbox("항목", options=options, key=f"sel_{item_id}")
        item["choice"] = choice
    with row[3]:
        if item["choice"] == "직접입력":
            item["custom"] = st.text_input("직접입력", key=f"custom_{item_id}")
        else:
            st.caption(" ")
    with row[4]:
        if st.button("삭제", key=f"delbtn_{item_id}"):
            to_delete_ids.append(item_id)

    if up:
        img = Image.open(up)
        st.image(img, use_container_width=True)

# 추가 / 삭제 버튼
cc1, cc2 = st.columns([1,1])
with cc1:
    if st.button("➕ 사진 추가"):
        if len(photos) < MAX_PHOTOS:
            photos.append({"id": str(uuid.uuid4()), "choice": options[0], "custom": ""})
with cc2:
    if st.button("🗑 선택 삭제"):
        photos[:] = [p for p in photos if p["id"] not in to_delete_ids]

# PDF 생성
if st.button("📄 PDF 생성"):
    items = []
    for item in photos:
        label = item["custom"] if item["choice"] == "직접입력" and item["custom"].strip() else item["choice"]
        up = st.session_state.get(f"fu_{item['id']}")
        img = None
        if up:
            img = Image.open(up).convert("RGB")
        items.append((label, img))
    pdf_bytes = build_pdf("기성 청구 양식", site_addr, items)
    st.download_button("⬇️ PDF 다운로드", pdf_bytes, "기성청구.pdf", mime="application/pdf")
