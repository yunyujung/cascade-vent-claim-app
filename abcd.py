import os
os.system("pip install streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식(현장사진) - 모바일 화면 최적화
# (한 줄 구성: 체크박스 | 항목 | 직접입력/사진 등록)

import io, re, unicodedata, uuid, os
from typing import List, Tuple, Optional
import streamlit as st
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ───────────────────────────────
# 페이지 설정
# ───────────────────────────────
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식(현장사진)", layout="wide")

st.markdown("""
    <h4 style='text-align:center; margin: 0.3rem 0; font-size: 1.1rem;'>
        캐스케이드/환기 기성 청구 양식(현장사진)
    </h4>
    <hr style='border:1px solid #ddd; margin:0.5rem 0 1rem 0;'>
""", unsafe_allow_html=True)

# ───────────────────────────────
# 세션 초기화
# ───────────────────────────────
if "photos" not in st.session_state:
    st.session_state.photos = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": "", "checked": False, "img": None}]
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "add_pending" not in st.session_state:
    st.session_state.add_pending = False

if st.session_state.add_pending:
    st.session_state.photos.append({"id": str(uuid.uuid4()), "choice": "장비납품", "custom": "", "checked": False, "img": None})
    st.session_state.add_pending = False

# ───────────────────────────────
# 폰트 등록
# ───────────────────────────────
def try_register_font():
    for name, path in [("NanumGothic", "NanumGothic.ttf"),
                       ("MalgunGothic", "C:\\Windows\\Fonts\\malgun.ttf"),
                       ("MalgunGothic", "C:/Windows/Fonts/malgun.ttf")]:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                return name
            except Exception:
                pass
    return "Helvetica"

BASE_FONT = try_register_font()
ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(name="title", parent=ss["Heading1"], fontName=BASE_FONT, fontSize=16, alignment=1),
    "cell": ParagraphStyle(name="cell", parent=ss["Normal"], fontName=BASE_FONT, fontSize=9),
    "small_center": ParagraphStyle(name="small_center", parent=ss["Normal"], fontName=BASE_FONT, fontSize=8, alignment=1)
}

# ───────────────────────────────
# 유틸 함수
# ───────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    return re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".") or "output"

def normalize_orientation(img: Image.Image) -> Image.Image:
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert("RGB")

def _pil_to_bytesio(img: Image.Image, quality=85) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)
    return buf

# ───────────────────────────────
# PDF 생성
# ───────────────────────────────
def build_pdf(doc_title: str, site_addr: str, items: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    doc = SimpleDocTemplate(buf, pagesize=A4, title=doc_title, leftMargin=20, rightMargin=20)
    story = [Paragraph(doc_title, styles["title"]), Spacer(1, 6)]
    meta = Table([[Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr or "-", styles["cell"])]],
                 colWidths=[70, PAGE_W - 120])
    meta.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black)]))
    story.append(meta)
    story.append(Spacer(1, 6))
    cols = 3
    col_w = (PAGE_W - 40) / cols
    imgs = []
    for label, img in items:
        img_bio = _pil_to_bytesio(normalize_orientation(img))
        rl_img = RLImage(img_bio, width=col_w - 6, height=150)
        cell = Table([[rl_img], [Paragraph(label, styles["small_center"])]], colWidths=[col_w - 6])
        imgs.append(cell)
    if imgs:
        rows = [imgs[i:i+3] for i in range(0, len(imgs), 3)]
        story.append(Table(rows, colWidths=[col_w]*3))
    doc.build(story)
    return buf.getvalue()

# ───────────────────────────────
# 입력 영역
# ───────────────────────────────
mode = st.radio("양식 선택", ["캐스케이드", "환기"], horizontal=True)
site_addr = st.text_input("현장 주소", "")
st.divider()

CASCADE_OPTIONS = ["장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공", "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"]
VENT_OPTIONS = ["직접입력"]
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS

# ───────────────────────────────
# 한 줄 구성 UI (모바일 최적화)
# ───────────────────────────────
for p in st.session_state.photos:
    with st.container(border=True):
        col1, col2, col3 = st.columns([0.6, 2, 2])
        with col1:
            p["checked"] = st.checkbox("", key=f"chk_{p['id']}", value=p.get("checked", False))
        with col2:
            current_choice = p.get("choice", options[0])
            p["choice"] = st.selectbox("항목", options, key=f"choice_{p['id']}", index=options.index(current_choice), label_visibility="collapsed")
        with col3:
            if p["choice"] == "직접입력":
                p["custom"] = st.text_input("직접입력", p.get("custom", ""), key=f"custom_{p['id']}", label_visibility="collapsed", placeholder="항목 직접 입력")
            upload = st.file_uploader("사진", type=["jpg","jpeg","png"], key=f"up_{p['id']}", label_visibility="collapsed")
            if upload:
                p["img"] = normalize_orientation(Image.open(upload))
            if p["img"]:
                st.image(p["img"], use_container_width=True, caption=p["custom"] or p["choice"], clamp=True)

st.divider()

# ───────────────────────────────
# 버튼 영역
# ───────────────────────────────
b1, b2, b3 = st.columns([1,1,2])
with b1:
    if st.button("➕ 추가", use_container_width=True):
        st.session_state.add_pending = True
        st.rerun()
with b2:
    if st.button("🗑 삭제", use_container_width=True):
        st.session_state.photos = [x for x in st.session_state.photos if not x["checked"]]
        st.rerun()
with b3:
    if st.button("📄 PDF 생성", type="primary", use_container_width=True):
        valid = []
        for p in st.session_state.photos:
            if p.get("img"):
                label = p["custom"].strip() if p["choice"] == "직접입력" and p.get("custom") else p["choice"]
                valid.append((label, p["img"]))
        if not valid:
            st.warning("📸 사진이 등록된 항목이 없습니다.")
        else:
            st.session_state.pdf_bytes = build_pdf("캐스케이드/환기 기성 청구 양식(현장사진)", site_addr, valid)
            st.rerun()

# ───────────────────────────────
# 다운로드 버튼
# ───────────────────────────────
if st.session_state.pdf_bytes:
    fname = f"{sanitize_filename(site_addr)}_{mode}_기성청구(현장사진).pdf"
    st.success("✅ PDF 생성 완료! 아래 버튼으로 다운로드하세요.")
    st.download_button("⬇️ PDF 다운로드", st.session_state.pdf_bytes, file_name=fname, mime="application/pdf", use_container_width=True)
