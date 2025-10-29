# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식 - 동적 사진(최대 9컷), 3xN 그리드 PDF

import io
import os
import re
import unicodedata
from math import ceil
from datetime import date
from typing import List, Tuple, Optional

import streamlit as st
from PIL import Image

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="캐스케이드/환기 기성 청구 양식",
    layout="wide"
)

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
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont(family, path))
                try:
                    pdfmetrics.registerFont(TTFont(f"{family}-Bold", path))
                    pdfmetrics.registerFont(TTFont(f"{family}-Italic", path))
                    pdfmetrics.registerFont(TTFont(f"{family}-BoldItalic", path))
                except Exception:
                    pass
                return family, True
        except Exception:
            pass
    return "Helvetica", False

BASE_FONT, FONT_OK = try_register_font()
if not FONT_OK:
    st.warning("⚠️ 한글 폰트 임베드 실패. 실행 폴더에 `NanumGothic.ttf`를 두면 PDF 한글이 깨지지 않습니다.")

ss = getSampleStyleSheet()
styles = {
    "title": ParagraphStyle(
        name="title", parent=ss["Heading1"], fontName=BASE_FONT,
        fontSize=18, leading=22, alignment=1, spaceAfter=8
    ),
    "cell": ParagraphStyle(
        name="cell", parent=ss["Normal"], fontName=BASE_FONT,
        fontSize=10, leading=13
    ),
    "small_center": ParagraphStyle(
        name="small_center", parent=ss["Normal"], fontName=BASE_FONT,
        fontSize=8.5, leading=11, alignment=1
    ),
}

# ─────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".")
    return name or "output"

def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4/3) -> Image.Image:
    """이미지 비율을 target_ratio로 맞추기 위해 패딩(흰색) 추가."""
    w, h = img.size
    cur_ratio = w / h
    if abs(cur_ratio - target_ratio) < 1e-3:
        return img

    if cur_ratio > target_ratio:          # 가로가 더 김 → 세로 확장
        new_h = int(round(w / target_ratio))
        new_w = w
    else:                                  # 세로가 더 김 → 가로 확장
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
# PDF 빌더 (3열 그리드, 최대 9장)
# ─────────────────────────────────────────
def build_pdf(doc_title: str, site_addr: str, items: List[Tuple[str, Optional[Image.Image]]]) -> bytes:
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    LEFT_RIGHT_MARGIN = 20
    TOP_BOTTOM_MARGIN = 20

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=TOP_BOTTOM_MARGIN, bottomMargin=TOP_BOTTOM_MARGIN,
        leftMargin=LEFT_RIGHT_MARGIN, rightMargin=LEFT_RIGHT_MARGIN,
        title=doc_title
    )

    story = []
    story.append(Paragraph(doc_title, styles["title"]))
    story.append(Spacer(1, 4))

    # 메타 테이블 (현장 주소만)
    meta_tbl = Table(
        [
            [Paragraph("현장 주소", styles["cell"]), Paragraph(site_addr.strip() or "-", styles["cell"])]
        ],
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

    # 사진 그리드: 3열, 행 높이 조정 (1페이지 수렴)
    col_count = 3
    usable_width = PAGE_W - 2*LEFT_RIGHT_MARGIN
    col_width = usable_width / col_count

    # 행 수에 따라 높이를 조금 조정 (최대 9장 = 3행)
    n = min(len(items), 9)
    rows = ceil(n / col_count)

    ROW_HEIGHT = 200 if rows >= 3 else (230 if rows == 2 else 260)
    CAPTION_HEIGHT = 22
    IMAGE_MAX_H = ROW_HEIGHT - CAPTION_HEIGHT - 8
    IMAGE_MAX_W = col_width - 8

    # 셀 생성
    cells = []
    for label, pil_img in items[:9]:
        if pil_img is not None:
            pil_img = enforce_aspect_pad(pil_img, 4/3)
            img_resized = _resize_for_pdf(pil_img, max_px=1400)
            bio = _pil_to_bytesio(img_resized, quality=85)

            # 4:3 비율로 셀 안 배치
            target_w = IMAGE_MAX_W
            target_h = target_w * 3 / 4
            if target_h > IMAGE_MAX_H:
                target_h = IMAGE_MAX_H
                target_w = target_h * 4 / 3

            rl_img = RLImage(bio, width=target_w, height=target_h)
            rl_img.hAlign = "CENTER"

            cell = Table(
                [[rl_img],
                 [Paragraph(label, styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
            cell.setStyle(TableStyle([
                ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
                ("VALIGN", (0,0), (-1,0), "MIDDLE"),
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("TOPPADDING", (0,0), (-1,0), 2),
                ("BOTTOMPADDING", (0,0), (-1,0), 2),
                ("TOPPADDING", (0,1), (-1,1), 0),
                ("BOTTOMPADDING", (0,1), (-1,1), 0),
            ]))
        else:
            cell = Table(
                [[Paragraph("(사진 없음)", styles["small_center"])],
                 [Paragraph(label, styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
            cell.setStyle(TableStyle([
                ("BOX", (0,0), (-1,-1), 0.3, colors.grey),
                ("VALIGN", (0,0), (-1,0), "MIDDLE"),
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ]))
        cells.append(cell)

    # 빈칸 채우기 (그리드 정렬)
    while len(cells) % col_count != 0:
        cells.append(
            Table(
                [[Paragraph("(빈 칸)", styles["small_center"])],
                 [Paragraph("-", styles["small_center"])]],
                colWidths=[col_width],
                rowHeights=[ROW_HEIGHT - CAPTION_HEIGHT, CAPTION_HEIGHT]
            )
        )

    # 그리드 조립
    grid_rows = [cells[i*col_count:(i+1)*col_count] for i in range(len(cells)//col_count)]
    grid_tbl = Table(
        grid_rows,
        colWidths=[col_width]*col_count,
        rowHeights=[ROW_HEIGHT]*len(grid_rows),
        hAlign="CENTER", spaceBefore=0, spaceAfter=0
    )
    grid_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0,0), (-1,-1), 2),
        ("RIGHTPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
    ]))
    story.append(grid_tbl)

    doc.build(story)
    return buf.getvalue()

# ─────────────────────────────────────────
# 세션 상태
# ─────────────────────────────────────────
if "photo_count" not in st.session_state:
    st.session_state.photo_count = 1  # 기본 1개
if "mode" not in st.session_state:
    st.session_state.mode = "캐스케이드"
if "labels" not in st.session_state:
    st.session_state.labels = {}  # {idx: {"choice": "...", "custom": "..."}}

# ─────────────────────────────────────────
# 상단 UI
# ─────────────────────────────────────────
st.markdown("### 캐스케이드/환기 기성 청구 양식")
st.info("모바일에서는 **촬영(카메라)** 또는 **사진/갤러리 선택**으로 업로드 가능합니다. 모든 사진은 4:3 비율로 자동 보정됩니다.")

# 모드 선택
mode = st.radio("양식 종류 선택", options=["캐스케이드", "환기"], horizontal=True, index=0 if st.session_state.mode=="캐스케이드" else 1)
st.session_state.mode = mode

# 현장 주소
site_addr = st.text_input("현장 주소", value="", placeholder="예: 서울특별시 ○○구 ○○로 12, 101동 101호")

# 라벨 옵션
CASCADE_OPTIONS = [
    "장비납품", "급탕모듈러설치", "난방모듈러설치", "하부배관", "LLH시공",
    "연도시공", "외부연도마감", "드레인호스", "NCC판넬", "완료사진", "직접입력"
]
VENT_OPTIONS = ["직접입력"]

# 사진 영역
st.markdown("#### 현장 사진")

# 동적 사진 블록 생성 (기본 1, 최대 9)
max_photos = 9
for i in range(st.session_state.photo_count):
    with st.container(border=True):
        cols = st.columns([1, 2, 2])
        with cols[0]:
            st.caption(f"사진 {i+1}")
            # 드롭다운
            options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
            current_choice = st.session_state.labels.get(i, {}).get("choice", options[0])
            choice = st.selectbox("항목 선택", options=options, key=f"sel_{i}", index=(options.index(current_choice) if current_choice in options else 0))

            # 직접입력일 때 텍스트
            custom_default = st.session_state.labels.get(i, {}).get("custom", "")
            custom_label = ""
            if choice == "직접입력":
                custom_label = st.text_input("항목명 직접입력", value=custom_default, key=f"custom_{i}", placeholder="예: 배기후드 시공 전·후")

            # 상태 저장
            st.session_state.labels[i] = {"choice": choice, "custom": custom_label}

        with cols[1]:
            cam = st.camera_input("📷 촬영", key=f"cam_{i}")
        with cols[2]:
            fu = st.file_uploader("사진/갤러리 선택", type=["jpg", "jpeg", "png"], key=f"fu_{i}")

# 추가/삭제 버튼
cc1, cc2, cc3 = st.columns([1,1,6])
with cc1:
    if st.button("➕ 사진 추가", use_container_width=True):
        if st.session_state.photo_count < max_photos:
            st.session_state.photo_count += 1
        else:
            st.warning("최대 9장까지 추가할 수 있습니다.")
with cc2:
    if st.button("➖ 마지막 삭제", use_container_width=True):
        if st.session_state.photo_count > 1:
            # 마지막 라벨 상태 제거
            st.session_state.labels.pop(st.session_state.photo_count-1, None)
            st.session_state.photo_count -= 1
        else:
            st.warning("최소 1장은 유지됩니다.")

# 제출 버튼
submitted = st.button("📄 PDF 생성")

if submitted:
    try:
        # 라벨/이미지 수집
        titled_images: List[Tuple[str, Optional[Image.Image]]] = []
        for i in range(st.session_state.photo_count):
            # 라벨 결정
            choice = st.session_state.labels.get(i, {}).get("choice", "직접입력")
            custom = st.session_state.labels.get(i, {}).get("custom", "")
            label = custom.strip() if choice == "직접입력" and custom.strip() else choice

            # 이미지 선택(촬영 우선)
            cam = st.session_state.get(f"cam_{i}")
            fu = st.session_state.get(f"fu_{i}")
            pil_img = None
            if cam is not None:
                pil_img = Image.open(cam).convert("RGB")
            elif fu is not None:
                pil_img = Image.open(fu).convert("RGB")

            if pil_img is not None:
                pil_img = enforce_aspect_pad(pil_img, 4/3)

            titled_images.append((label, pil_img))

        # 제목 결정
        doc_title = "캐스케이드 기성 청구 양식" if mode == "캐스케이드" else "환기 기성 청구 양식"

        pdf_bytes = build_pdf(doc_title, site_addr, titled_images)
        safe_site = sanitize_filename(site_addr if site_addr.strip() else doc_title)
        st.success("PDF 생성 완료! 아래 버튼으로 다운로드하세요.")
        st.download_button(
            label="⬇️ 기성 청구 양식(PDF) 다운로드",
            data=pdf_bytes,
            file_name=f"{safe_site}_기성청구양식.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.error("PDF 생성 중 오류가 발생했습니다. 아래 상세 오류를 확인하세요.")
        st.exception(e)

with st.expander("도움말 / 안내"):
    st.markdown(
        """
- **양식 선택**: 상단에서 *캐스케이드/환기* 중 선택하면 PDF 제목이 자동으로 반영됩니다.
- **현장 주소**: 이 항목만 메타정보로 포함됩니다.
- **사진 추가**: 기본 1장으로 시작하며 **➕ 사진 추가**로 최대 9장까지 늘릴 수 있습니다.
- **항목 라벨**: 캐스케이드는 드롭다운에서 항목을 선택하거나 **직접입력**을 선택해 텍스트를 입력하세요. 환기는 **직접입력**만 제공합니다.
- **사진 비율**: 모든 사진은 **4:3 비율(패딩)** 로 자동 보정됩니다. 용량은 자동으로 리사이즈/압축됩니다.
- **한글 깨짐**: 실행 폴더에 `NanumGothic.ttf`를 두면 PDF 내 한글이 깨지지 않습니다(윈도우는 `맑은고딕` 자동 시도).
        """
    )
