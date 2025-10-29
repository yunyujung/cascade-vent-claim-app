import os
# 필요 패키지 (requirements.txt 쓰면 이 줄은 생략 가능)
os.system("pip install -q streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식
# - UI: 한 줄(체크박스 · '항목' 라벨 · 드롭다운) + 아래 사진 업로드/미리보기
# - PDF: 제목/현장주소 표/테두리 유지, 업로드된 사진까지만 3열 카드로 출력(빈칸 없음)

import io, re, unicodedata, uuid
from typing import List, Tuple, Optional

import streamlit as st
from PIL import Image

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ───────────────────────────────
# 페이지/폰트/스타일
# ───────────────────────────────
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식", layout="wide")

# 모바일에서도 컬럼이 절대 줄바꿈되지 않도록 강제 (한 줄 유지)
st.markdown("""
<style>
/* 모든 가로 블록(=columns 컨테이너)의 줄바꿈 방지 */
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
/* 각 column의 최소폭 축소 허용 + 수직정렬 중앙 */
div[data-testid="column"] { min-width: 0 !important; }
div[data-testid="column"] > div { display: flex; align-items: center; gap: .5rem; }
/* selectbox 라벨 여백 최소화 */
div[data-baseweb="select"] { margin-top: 0 !important; }
</style>
""", unsafe_allow_html=True)

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
# 유틸
# ───────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    return re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".") or "output"

def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4/3) -> Image.Image:
    """이미지를 target_ratio(4:3)로 흰색 패딩해 캔버스 맞춤."""
    w, h = img.size
    cur_ratio = w / h
    if abs(cur_ratio - target_ratio) < 1e-3:
        return img
    if cur_ratio > target_ratio:  # 가로가 더 김 → 세로 확장
        new_h = int(round(w / target_ratio))
        new_w = w
    else:                         # 세로가 더 김 → 가로 확장
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
# PDF 빌더 (3열 카드, 테두리/제목/주소 유지, 빈칸 없음)
# ───────────────────────────────
def build_pdf(doc_title: str, site_addr: str, items: List[Tuple[str, Image.Image]]) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 20
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            title=doc_title)
    story = []
    # 제목
    story.append(Paragraph(doc_title, styles["title"]))
    story.append(Spacer(1, 4))
    # 현장 주소 표 (테두리 유지)
    meta_tbl = Table(
        [[Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr.strip() or "-", styles["cell"])]],
        colWidths=[80, PAGE_W - 2*MARGIN - 80]
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
    story.append(Spacer(1, 8))

    if not items:
        doc.build(story)
        return buf.getvalue()

    # 카드 크기
    col_count = 3
    usable_width = PAGE_W - 2*MARGIN
    col_width = usable_width / col_count
    ROW_HEIGHT = 200
    CAPTION_HEIGHT = 22
    IMAGE_MAX_H = ROW_HEIGHT - CAPTION_HEIGHT - 8
    IMAGE_MAX_W = col_width - 8

    # 카드 생성 (업로드된 사진만)
    cells = []
    for label, pil_img in items:
        pil_img = enforce_aspect_pad(pil_img, 4/3)
        # 크기 조정(너비 기준)
        target_w = IMAGE_MAX_W
        target_h = target_w * 3 / 4
        if target_h > IMAGE_MAX_H:
            target_h = IMAGE_MAX_H
            target_w = target_h * 4 / 3

        bio = _pil_to_bytesio(pil_img)
        rl_img = RLImage(bio, width=target_w, height=target_h)
        rl_img.hAlign = "CENTER"

        card = Table(
            [[rl_img], [Paragraph(label, styles["small_center"])]],
            colWidths=[col_width],
            rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
        )
        card.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 0.4, colors.grey),
            ("VALIGN", (0,0), (-1,0), "MIDDLE"),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("LEFTPADDING", (0,0), (-1,-1), 2),
            ("RIGHTPADDING", (0,0), (-1,-1), 2),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ]))
        cells.append(card)

    # 3열 그리드(빈칸 없이)
    rows = [cells[i:i+3] for i in range(0, len(cells), 3)]
    grid_tbl = Table(rows, colWidths=[col_width]*3, rowHeights=[ROW_HEIGHT]*len(rows))
    story.append(grid_tbl)

    doc.build(story)
    return buf.getvalue()

# ───────────────────────────────
# 세션 상태
# ───────────────────────────────
if "photos" not in st.session_state:
    st.session_state.photos = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": "", "checked": False, "img": None}]
if "out_ready" not in st.session_state:
    st.session_state.out_ready = False

# 옵션
CASCADE_OPTIONS = ["장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공",
                   "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"]
VENT_OPTIONS = ["직접입력"]

# ───────────────────────────────
# 상단 UI
# ───────────────────────────────
mode = st.radio("양식 선택", ["캐스케이드", "환기"], horizontal=True)
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
site_addr = st.text_input("현장 주소", "")

st.caption("행 구성: **[체크박스]  [항목] [드롭다운]**  → (아래) 사진 등록/미리보기 — 모바일에서도 한 줄로 유지")

# ───────────────────────────────
# 항목 UI (한 줄: 체크박스 · '항목' 라벨 · 드롭다운 / 아래: 사진 업로드 + 미리보기)
# ───────────────────────────────
for p in st.session_state.photos:
    # 한 줄 (절대 줄바꿈 X)
    row = st.columns([0.5, 0.7, 3.5])
    with row[0]:
        p["checked"] = st.checkbox("", key=f"chk_{p['id']}", value=p.get("checked", False))
    with row[1]:
        st.markdown("**항목**")
    with row[2]:
        p["choice"] = st.selectbox(label="", options=options, key=f"sel_{p['id']}")
        if p["choice"] == "직접입력":
            p["custom"] = st.text_input("직접입력", value=p.get("custom",""), key=f"custom_{p['id']}")
    # 아래 줄: 사진 업로드
    up = st.file_uploader("사진 등록", type=["jpg", "jpeg", "png"], key=f"up_{p['id']}")
    if up:
        p["img"] = Image.open(up).convert("RGB")
    if p.get("img"):
        st.image(p["img"], use_container_width=True)

# ───────────────────────────────
# 버튼: 추가 / 선택 삭제 / PDF 생성
# ───────────────────────────────
c1, c2, c3 = st.columns([1,1,2])
with c1:
    if st.button("➕ 항목 추가"):
        st.session_state.photos.append({"id": str(uuid.uuid4()), "choice": options[0], "custom": "", "checked": False, "img": None})
with c2:
    if st.button("🗑 선택 삭제"):
        st.session_state.photos = [p for p in st.session_state.photos if not p["checked"]]
        for p in st.session_state.photos:
            p["checked"] = False
with c3:
    if st.button("📄 PDF 생성", type="primary"):
        valid = [((p["custom"].strip() if (p["choice"]=="직접입력" and p.get("custom","").strip()) else p["choice"]), p["img"])
                 for p in st.session_state.photos if p.get("img") is not None]
        if not valid:
            st.warning("📸 사진이 등록된 항목이 없습니다.")
        else:
            doc_title = f"{mode} 기성 청구 양식"
            pdf_bytes = build_pdf(doc_title, site_addr, valid)
            st.session_state.out_ready = True
            st.session_state.pdf_bytes = pdf_bytes

# ───────────────────────────────
# 다운로드 버튼
# ───────────────────────────────
if st.session_state.get("out_ready"):
    fname_base = f"{sanitize_filename(site_addr)}_{mode}_기성청구".strip("_")
    st.success("✅ PDF가 생성되었습니다. 아래에서 내려받으세요.")
    st.download_button("⬇️ PDF 다운로드", st.session_state.pdf_bytes,
                       file_name=f"{fname_base}.pdf", mime="application/pdf")
