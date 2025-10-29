import os
os.system("pip install streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식 - 버튼 1회 작동 / 테두리 유지 / 제목 유지

import io, re, unicodedata, uuid
from math import ceil
from typing import List, Tuple, Optional
import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ───────────────────────────────
# 페이지 설정
# ───────────────────────────────
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식", layout="wide")


# ───────────────────────────────
# 폰트 등록
# ───────────────────────────────
def try_register_font():
    candidates = [
        ("NanumGothic", "NanumGothic.ttf"),
        ("MalgunGothic", "C:\\Windows\\Fonts\\malgun.ttf"),
        ("MalgunGothic", "C:/Windows/Fonts/malgun.ttf"),
    ]
    for name, path in candidates:
        try:
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(name, path))
                return name, True
        except Exception:
            pass
    return "Helvetica", False


BASE_FONT, _ = try_register_font()
ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(name="title", parent=ss["Heading1"], fontName=BASE_FONT,
                            fontSize=18, leading=22, alignment=1, spaceAfter=8),
    "cell": ParagraphStyle(name="cell", parent=ss["Normal"], fontName=BASE_FONT,
                           fontSize=10, leading=13),
    "small_center": ParagraphStyle(name="small_center", parent=ss["Normal"], fontName=BASE_FONT,
                                   fontSize=8.5, leading=11, alignment=1),
}


# ───────────────────────────────
# 유틸 함수
# ───────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    return re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".") or "output"


def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4/3) -> Image.Image:
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
    canvas.paste(img, ((new_w - w) // 2, (new_h - h) // 2))
    return canvas


def _pil_to_bytesio(img: Image.Image, quality=85) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return buf


# ───────────────────────────────
# PDF 생성 (제목/테두리 유지)
# ───────────────────────────────
def build_pdf(doc_title: str, site_addr: str, items: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 20
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            title=doc_title)
    story = []
    story.append(Paragraph(doc_title, styles["title"]))
    story.append(Spacer(1, 4))

    meta_tbl = Table(
        [[Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr.strip() or "-", styles["cell"])]],
        colWidths=[80, PAGE_W - 2*MARGIN - 80]
    )
    meta_tbl.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.9, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 8))

    col_count = 3
    usable_width = PAGE_W - 2*MARGIN
    col_width = usable_width / col_count
    ROW_HEIGHT = 200
    CAPTION_HEIGHT = 22
    IMAGE_MAX_H = ROW_HEIGHT - CAPTION_HEIGHT - 8
    IMAGE_MAX_W = col_width - 8

    cells = []
    for label, pil_img in items:
        pil_img = enforce_aspect_pad(pil_img)
        bio = _pil_to_bytesio(pil_img)
        rl_img = RLImage(bio, width=IMAGE_MAX_W, height=IMAGE_MAX_H)
        cell = Table([[rl_img], [Paragraph(label, styles["small_center"])]],
                     colWidths=[col_width],
                     rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT])
        cell.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.4, colors.grey),
            ("VALIGN", (0,0), (-1,0), "MIDDLE"),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ]))
        cells.append(cell)

    if cells:
        grid_rows = [cells[i:i+3] for i in range(0, len(cells), 3)]
        grid_tbl = Table(grid_rows, colWidths=[col_width]*3, rowHeights=[ROW_HEIGHT]*len(grid_rows))
        grid_tbl.setStyle(TableStyle([
            ("LEFTPADDING", (0,0), (-1,-1), 2),
            ("RIGHTPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        story.append(grid_tbl)

    doc.build(story)
    return buf.getvalue()


# ───────────────────────────────
# 세션 관리
# ───────────────────────────────
if "photos" not in st.session_state:
    st.session_state.photos = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": "", "checked": False, "img": None}]
if "pdf_ready" not in st.session_state:
    st.session_state.pdf_ready = False
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None

mode = st.radio("양식 선택", ["캐스케이드", "환기"], horizontal=True)
CASCADE_OPTIONS = ["장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공", "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"]
VENT_OPTIONS = ["직접입력"]
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
site_addr = st.text_input("현장 주소", "")

# ───────────────────────────────
# UI: 체크박스 / 번호 / 드롭다운 + 사진
# ───────────────────────────────
for idx, p in enumerate(st.session_state.photos):
    cols = st.columns([0.4, 0.4, 2.2])
    with cols[0]:
        p["checked"] = st.checkbox("", key=f"chk_{p['id']}", value=p.get("checked", False))
    with cols[1]:
        st.markdown(f"**{idx+1}.**")
    with cols[2]:
        p["choice"] = st.selectbox("항목", options, key=f"sel_{p['id']}")
        if p["choice"] == "직접입력":
            p["custom"] = st.text_input("직접입력", value=p["custom"], key=f"custom_{p['id']}")
    upload = st.file_uploader("사진 등록", type=["jpg", "jpeg", "png"], key=f"up_{p['id']}")
    if upload:
        p["img"] = Image.open(upload).convert("RGB")
    if p["img"]:
        st.image(p["img"], use_container_width=True)

# ───────────────────────────────
# 추가 / 삭제 / PDF 생성
# ───────────────────────────────
c1, c2, c3 = st.columns([1,1,2])
with c1:
    if st.button("➕ 추가"):
        st.session_state.photos.append({"id": str(uuid.uuid4()), "choice": options[0], "custom": "", "checked": False, "img": None})
with c2:
    if st.button("🗑 선택 삭제"):
        st.session_state.photos = [p for p in st.session_state.photos if not p["checked"]]
        for p in st.session_state.photos:
            p["checked"] = False
with c3:
    if st.button("📄 PDF 생성", type="primary"):
        valid_items = [(p["custom"] if p["choice"] == "직접입력" and p["custom"].strip() else p["choice"], p["img"])
                       for p in st.session_state.photos if p["img"]]
        if not valid_items:
            st.warning("📸 사진이 등록된 항목이 없습니다.")
        else:
            pdf_bytes = build_pdf(f"{mode} 기성 청구 양식", site_addr, valid_items)
            st.session_state.pdf_ready = True
            st.session_state.pdf_bytes = pdf_bytes

# ───────────────────────────────
# PDF 다운로드 버튼 자동 표시
# ───────────────────────────────
if st.session_state.pdf_ready and st.session_state.pdf_bytes:
    fname = f"{sanitize_filename(site_addr)}_{mode}_기성청구.pdf"
    st.success("✅ PDF 생성 완료! 아래 버튼으로 바로 다운로드하세요.")
    st.download_button("⬇️ PDF 다운로드", st.session_state.pdf_bytes, file_name=fname, mime="application/pdf")
