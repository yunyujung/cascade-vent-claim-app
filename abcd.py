import os
os.system("pip install streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식
# - 모바일에서 드롭다운만 눌렀는데 키보드 올라오는 문제 해결:
#   직접입력 아닐 때는 text_input 자체를 아예 렌더하지 않음
#   직접입력일 때만 text_input을 렌더하고, 즉시 blur() 처리해서 자동 포커스 빼버림
# - 추가 버튼 1번 클릭 즉시 추가 (add_pending)
# - 사진 방향 고정하여 PDF에 넣기

import io, re, unicodedata, uuid, os
from typing import List, Tuple, Optional
import streamlit as st
from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Table,
    TableStyle,
    Spacer,
    Image as RLImage,
)
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ───────────────────────────────
# 페이지 설정
# ───────────────────────────────
st.set_page_config(page_title="캐스케이드/환기 기성 청구 양식", layout="wide")


# ───────────────────────────────
# 세션 초기화 / 추가버튼 처리
# ───────────────────────────────
if "photos" not in st.session_state:
    st.session_state.photos = [
        {
            "id": str(uuid.uuid4()),
            "choice": "장비납품",
            "custom": "",
            "checked": False,
            "img": None,
        }
    ]

if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None

if "add_pending" not in st.session_state:
    st.session_state.add_pending = False

# add_pending 처리: rerun 직후 실제로 1행만 추가
if st.session_state.add_pending:
    st.session_state.photos.append(
        {
            "id": str(uuid.uuid4()),
            "choice": "장비납품",
            "custom": "",
            "checked": False,
            "img": None,
        }
    )
    st.session_state.add_pending = False  # 플래그 해제


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
    "title": ParagraphStyle(
        name="title",
        parent=ss["Heading1"],
        fontName=BASE_FONT,
        fontSize=18,
        leading=22,
        alignment=1,
        spaceAfter=8,
    ),
    "cell": ParagraphStyle(
        name="cell",
        parent=ss["Normal"],
        fontName=BASE_FONT,
        fontSize=10,
        leading=13,
    ),
    "small_center": ParagraphStyle(
        name="small_center",
        parent=ss["Normal"],
        fontName=BASE_FONT,
        fontSize=8.5,
        leading=11,
        alignment=1,
    ),
}

# ───────────────────────────────
# 유틸 함수
# ───────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    return re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".") or "output"

def normalize_orientation(img: Image.Image) -> Image.Image:
    # 앨범에서 보이던 방향 그대로 강제 고정
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img.convert("RGB")

def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4 / 3) -> Image.Image:
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
# (중요) 직접입력 필드 렌더 함수
#   - 직접입력 모드일 때만 실제 text_input 위젯 만들기
#   - 그리고 JS로 blur() 바로 걸어서 자동 포커스 빼기 (모바일 키보드 강제 닫힘 유도)
#   - 직접입력 아닐 때는 text_input 자체를 아예 안 그림 → 키보드 절대 안 뜸
# ───────────────────────────────
def render_custom_input(p):
    is_custom_mode = (p["choice"] == "직접입력")

    if is_custom_mode:
        # 실제 text_input 렌더
        new_val = st.text_input(
            "직접입력",
            value=p.get("custom", ""),
            key=f"custom_{p['id']}",
            placeholder="항목 직접 입력",
        )
        p["custom"] = new_val

        # JS로 이 input에 자동 포커스된 걸 즉시 blur()시켜서 키보드 내려가게
        # (id는 Streamlit이 자동생성하므로 직접 지정은 어렵지만,
        #  document.activeElement.blur() 로 전체 포커스 제거 가능)
        st.markdown(
            """
            <script>
            setTimeout(function(){
                if (document && document.activeElement) {
                    document.activeElement.blur();
                }
            }, 50);
            </script>
            """,
            unsafe_allow_html=True,
        )
    else:
        # 직접입력 모드가 아니면 custom 값 유지만 하고 입력칸은 렌더하지 않는다
        if "custom" not in p:
            p["custom"] = ""


# ───────────────────────────────
# PDF 생성
# ───────────────────────────────
def build_pdf(
    doc_title: str, site_addr: str, items: List[Tuple[str, Optional[Image.Image]]]
) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 20
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        title=doc_title,
    )

    story = []
    story.append(Paragraph(doc_title, styles["title"]))
    story.append(Spacer(1, 4))

    meta_tbl = Table(
        [
            [
                Paragraph("현장 주소", styles["cell"]),
                Paragraph(site_addr.strip() or "-", styles["cell"]),
            ]
        ],
        colWidths=[80, PAGE_W - 2 * MARGIN - 80],
    )
    meta_tbl.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.9, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(meta_tbl)
    story.append(Spacer(1, 8))

    col_count = 3
    usable_width = PAGE_W - 2 * MARGIN
    col_width = usable_width / col_count
    ROW_HEIGHT = 200
    CAPTION_HEIGHT = 22
    IMAGE_MAX_H = ROW_HEIGHT - CAPTION_HEIGHT - 8
    IMAGE_MAX_W = col_width - 8

    cells = []
    for label, pil_img in items:
        pil_img_fixed = normalize_orientation(pil_img)
        pil_img_fixed = enforce_aspect_pad(pil_img_fixed)

        bio = _pil_to_bytesio(pil_img_fixed)
        rl_img = RLImage(bio, width=IMAGE_MAX_W, height=IMAGE_MAX_H)

        cell = Table(
            [
                [rl_img],
                [Paragraph(label, styles["small_center"])],
            ],
            colWidths=[col_width],
            rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT],
        )
        cell.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]
            )
        )
        cells.append(cell)

    if cells:
        grid_rows = [cells[i : i + 3] for i in range(0, len(cells), 3)]
        grid_tbl = Table(
            grid_rows,
            colWidths=[col_width] * 3,
            rowHeights=[ROW_HEIGHT] * len(grid_rows),
        )
        grid_tbl.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(grid_tbl)

    doc.build(story)
    return buf.getvalue()


# ───────────────────────────────
# 상단 공통 입력
# ───────────────────────────────
mode = st.radio(
    "양식 선택", ["캐스케이드", "환기"], horizontal=True, key="mode_radio"
)

CASCADE_OPTIONS = [
    "장비납품",
    "급탕모듈러설치",
    "난방모듈러설치",
    "하부배관",
    "LLH시공",
    "연도시공",
    "외부연도마감",
    "드레인호스",
    "NCC판넬",
    "완료사진",
    "직접입력",
]
VENT_OPTIONS = ["직접입력"]

options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS

site_addr = st.text_input("현장 주소", "", key="site_addr")

st.divider()

# ───────────────────────────────
# 항목별 UI
#   - selectbox로 항목 선택
#   - 직접입력일 경우에만 실제 입력칸 렌더 + 즉시 blur()
#   - 업로드 시 회전 고정
# ───────────────────────────────
for p in st.session_state.photos:
    row = st.container(border=True)
    with row:
        c1, c2 = st.columns([4, 1], vertical_alignment="center")

        with c1:
            # 선택 유지
            if p.get("choice") in options:
                default_index = options.index(p["choice"])
            else:
                default_index = 0

            selected_val = st.selectbox(
                "항목",
                options,
                index=default_index,
                key=f"sel_{p['id']}",
                label_visibility="collapsed",
            )
            p["choice"] = selected_val

            # 여기서만 custom 입력칸 그리기 / blur 처리
            render_custom_input(p)

        with c2:
            p["checked"] = st.checkbox(
                "선택", key=f"chk_{p['id']}", value=p.get("checked", False)
            )

        upload = st.file_uploader(
            "사진 등록",
            type=["jpg", "jpeg", "png"],
            key=f"up_{p['id']}",
        )
        if upload:
            original = Image.open(upload)
            p["img"] = normalize_orientation(original)

        if p["img"]:
            st.image(p["img"], use_container_width=True)

st.divider()

# ───────────────────────────────
# 버튼 영역
# ───────────────────────────────
btn_c1, btn_c2, btn_c3 = st.columns([1, 1, 2])

with btn_c1:
    if st.button("➕ 추가", key="add_row", use_container_width=True):
        st.session_state.add_pending = True
        st.rerun()

with btn_c2:
    if st.button("🗑 선택 삭제", key="del_rows", use_container_width=True):
        st.session_state.photos = [p for p in st.session_state.photos if not p["checked"]]
        for p in st.session_state.photos:
            p["checked"] = False
        st.rerun()

download_area = st.empty()

with btn_c3:
    if st.button("📄 PDF 생성", type="primary", key="make_pdf", use_container_width=True):
        valid_items = []
        for p in st.session_state.photos:
            if p.get("img") is not None:
                label = (
                    p["custom"].strip()
                    if (p["choice"] == "직접입력" and p.get("custom", "").strip())
                    else p["choice"]
                )
                valid_items.append((label, p["img"]))

        if not valid_items:
            st.warning("📸 사진이 등록된 항목이 없습니다.")
        else:
            pdf_bytes = build_pdf(f"{mode} 기성 청구 양식", site_addr, valid_items)
            st.session_state.pdf_bytes = pdf_bytes
            st.rerun()

# ───────────────────────────────
# PDF 다운로드 버튼
# ───────────────────────────────
if st.session_state.pdf_bytes:
    fname = f"{sanitize_filename(site_addr)}_{mode}_기성청구.pdf"
    with download_area.container():
        st.success("✅ PDF 생성 완료! 아래 버튼으로 바로 다운로드하세요.")
        st.download_button(
            "⬇️ PDF 다운로드",
            st.session_state.pdf_bytes,
            file_name=fname,
            mime="application/pdf",
            key="dl_pdf",
            use_container_width=True,
        )
