import os
os.system("pip install streamlit reportlab pillow")

import io
import re
import unicodedata
import uuid
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

# 페이지 설정
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식", layout="wide")

# 폰트 등록
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

BASE_FONT, FONT_OK = try_register_font()
ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(name="title", parent=ss["Heading1"], fontName=BASE_FONT, fontSize=18, alignment=1, spaceAfter=8),
    "cell": ParagraphStyle(name="cell", parent=ss["Normal"], fontName=BASE_FONT, fontSize=10),
    "small_center": ParagraphStyle(name="small_center", parent=ss["Normal"], fontName=BASE_FONT, fontSize=8.5, alignment=1),
}

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

def build_pdf(title: str, site_addr: str, images: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    story = [Paragraph(title, styles["title"]), Spacer(1, 6)]
    meta_tbl = Table([[Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr or "-", styles["cell"])]],
                     colWidths=[80, 400])
    meta_tbl.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black)]))
    story.append(meta_tbl)
    story.append(Spacer(1, 6))

    col_count = 3
    usable_width = A4[0] - 40
    col_width = usable_width / col_count
    rows = ceil(len(images) / col_count)
    ROW_HEIGHT = 200
    CAPTION_HEIGHT = 20
    cells = []
    for label, img in images:
        if img:
            img = enforce_aspect_pad(img, 4/3)
            img_buf = _pil_to_bytesio(img)
            rl_img = RLImage(img_buf, width=col_width - 10, height=(col_width - 10) * 0.75)
            cells.append(Table([[rl_img], [Paragraph(label, styles["small_center"])]],
                               colWidths=[col_width], rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]))
        else:
            cells.append(Table([[Paragraph("(사진 없음)", styles["small_center"])], [Paragraph(label, styles["small_center"])]],
                               colWidths=[col_width], rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]))

    while len(cells) % col_count != 0:
        cells.append(Table([[Paragraph("(빈칸)", styles["small_center"])], [Paragraph("-", styles["small_center"])]],
                           colWidths=[col_width], rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]))
    rows_tbl = [cells[i*col_count:(i+1)*col_count] for i in range(len(cells)//col_count)]
    story.append(Table(rows_tbl, colWidths=[col_width]*col_count, rowHeights=[ROW_HEIGHT]*rows))
    doc.build(story)
    return buf.getvalue()

# 세션
if "photos" not in st.session_state:
    st.session_state.photos = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": "", "checked": False}]
mode = st.radio("양식 선택", ["캐스케이드", "환기"], horizontal=True)
CASCADE_OPTIONS = ["장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공", "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"]
VENT_OPTIONS = ["직접입력"]
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
site_addr = st.text_input("현장 주소", "")

# 한 줄 구성: 체크박스, 번호, 드롭다운 + 아래 사진
delete_targets = []
for idx, p in enumerate(st.session_state.photos):
    cols = st.columns([0.6, 0.5, 2])
    with cols[0]:
        checked = st.checkbox("", key=f"chk_{p['id']}", value=p.get("checked", False))
        p["checked"] = checked
    with cols[1]:
        st.markdown(f"**{idx+1}.**")
    with cols[2]:
        p["choice"] = st.selectbox("항목", options, key=f"sel_{p['id']}")
        if p["choice"] == "직접입력":
            p["custom"] = st.text_input("직접입력", value=p["custom"], key=f"custom_{p['id']}")
    # 아래줄 - 사진 업로드
    upload = st.file_uploader("사진 등록", type=["jpg", "jpeg", "png"], key=f"up_{p['id']}")
    if upload:
        img = Image.open(upload)
        st.image(img, use_container_width=True)
        p["img"] = img
    elif "img" in p:
        st.image(p["img"], use_container_width=True)

# 추가/삭제 버튼
c1, c2 = st.columns([1,1])
with c1:
    if st.button("➕ 사진 추가"):
        if len(st.session_state.photos) < 9:
            st.session_state.photos.append({"id": str(uuid.uuid4()), "choice": options[0], "custom": "", "checked": False})
        else:
            st.warning("최대 9장까지 가능합니다.")
with c2:
    if st.button("🗑 선택 삭제"):
        st.session_state.photos = [p for p in st.session_state.photos if not p["checked"]]
        for i, p in enumerate(st.session_state.photos):
            p["checked"] = False  # 체크 초기화

# PDF 생성
if st.button("📄 PDF 생성"):
    pdf_imgs = []
    for p in st.session_state.photos:
        label = p["custom"].strip() if p["choice"] == "직접입력" and p["custom"].strip() else p["choice"]
        img = p.get("img")
        pdf_imgs.append((label, img))
    pdf_bytes = build_pdf(f"{mode} 기성 청구 양식", site_addr, pdf_imgs)
    fname = f"{sanitize_filename(site_addr)}_{mode}_기성청구.pdf"
    st.download_button("⬇️ PDF 다운로드", pdf_bytes, file_name=fname, mime="application/pdf")
