import os
os.system("pip install streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식 - 동적 사진(최대 9컷), 3xN 그리드 PDF

import io
import re
import unicodedata
from math import ceil
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
                # 볼드/이탤릭은 동일 폰트로 매핑 시도
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
    st.warning("⚠️ 한글 폰트 임베드 실패. 저장소 루트에 `NanumGothic.ttf`를 두면 PDF 한글이 깨지지 않습니다.")

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
# 유틸
# ─────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip().strip(".")
    return name or "output"

def enforce_aspect_pad(img: Image.Image, target_ratio: float = 4/3) -> Image.Image:
    """이미지 비율을 target_ratio로 맞추기 위해 흰색 패딩 추가."""
    w, h = img.size
    cur_ratio = w / h
    if abs(cur_ratio - target_ratio) < 1e-3:
        return img

    if cur_ratio > target_ratio:  # 가로가 더 김 → 세로 확장
        new_h = int(round(w / target_ratio))
        new_w = w
    else:  # 세로가 더 김 → 가로 확장
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
from typing import Optional, Tuple, List  # 재확인

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

    # 사진 그리드: 3열
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
# 도우미: 선택 삭제 시 세션키 재배열
# ─────────────────────────────────────────
def reindex_after_delete(keep_indices):
    """선택 삭제 후, fu_i/sel_i/custom_i/del_i 키들을 0..N-1로 재정렬"""
    old_to_new = {old_i: new_i for new_i, old_i in enumerate(keep_indices)}

    # 1) 값 복사 (새 인덱스로)
    for old_i, new_i in old_to_new.items():
        # 업로드 파일
        old_fu_key, new_fu_key = f"fu_{old_i}", f"fu_{new_i}"
        if old_fu_key in st.session_state:
            st.session_state[new_fu_key] = st.session_state[old_fu_key]
        # 선택값들
        old_sel_key, new_sel_key = f"sel_{old_i}", f"sel_{new_i}"
        if old_sel_key in st.session_state:
            st.session_state[new_sel_key] = st.session_state[old_sel_key]
        old_custom_key, new_custom_key = f"custom_{old_i}", f"custom_{new_i}"
        if old_custom_key in st.session_state:
            st.session_state[new_custom_key] = st.session_state[old_custom_key]
        # 삭제 체크박스는 새로 그릴 것이므로 복사 안함

    # 2) 오래된 키들 제거
    max_old = st.session_state.photo_count
    for old_i in range(max_old):
        if old_i not in keep_indices:
            for prefix in ("fu_", "sel_", "custom_", "del_"):
                k = f"{prefix}{old_i}"
                if k in st.session_state:
                    del st.session_state[k]

    # 3) 라벨 상태 재구성
    new_labels = {}
    for old_i, new_i in old_to_new.items():
        new_labels[new_i] = st.session_state.labels.get(old_i, {})
    st.session_state.labels = new_labels

    # 4) 개수 업데이트
    st.session_state.photo_count = len(keep_indices)

# ─────────────────────────────────────────
# 상단 UI
# ─────────────────────────────────────────
st.markdown("### 캐스케이드/환기 기성 청구 양식")
st.info("모바일에서 **사진 버튼**을 누르면 *사진보관함/사진찍기/파일선택*이 뜹니다. 모든 사진은 4:3 비율로 자동 보정됩니다.")

# 모드 선택
mode = st.radio("양식 종류 선택", options=["캐스케이드", "환기"], horizontal=True,
                index=0 if st.session_state.mode == "캐스케이드" else 1)
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
        head = st.columns([0.2, 1.2, 1.8, 2.0])
        # 삭제 체크박스
        with head[0]:
            st.checkbox("", key=f"del_{i}")
            st.caption(f"{i+1}")
        # 드롭다운 + 직접입력
        with head[1]:
            options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS
            current_choice = st.session_state.labels.get(i, {}).get("choice", options[0])
            choice = st.selectbox("항목", options=options, key=f"sel_{i}",
                                  index=(options.index(current_choice) if current_choice in options else 0))
            custom_default = st.session_state.labels.get(i, {}).get("custom", "")
            custom_label = ""
            if choice == "직접입력":
                custom_label = st.text_input("항목명 직접입력", value=custom_default,
                                             key=f"custom_{i}", placeholder="예: 배기후드 시공 전·후")
            st.session_state.labels[i] = {"choice": choice, "custom": custom_label}

        # 파일 업로더 (단일 컨트롤)
        with head[2]:
            st.write("")  # 줄맞춤
            st.file_uploader(
                "📷 사진 (촬영/보관함/파일)",
                type=["jpg", "jpeg", "png"],
                key=f"fu_{i}",
                accept_multiple_files=False
            )

        # 미리보기(선택 시)
        with head[3]:
            uploaded = st.session_state.get(f"fu_{i}")
            if uploaded is not None:
                try:
                    img = Image.open(uploaded)
                    st.image(img, caption="미리보기", use_container_width=True)
                except Exception:
                    st.caption("이미지 미리보기를 표시할 수 없습니다.")

# 하단 제어 버튼
cc1, cc2, cc3 = st.columns([1,1,6])
with cc1:
    if st.button("➕ 사진 추가", use_container_width=True):
        if st.session_state.photo_count < max_photos:
            st.session_state.photo_count += 1
        else:
            st.warning("최대 9장까지 추가할 수 있습니다.")
with cc2:
    if st.button("🗑 선택 삭제", use_container_width=True):
        to_delete = [i for i in range(st.session_state.photo_count) if st.session_state.get(f"del_{i}", False)]
        if not to_delete:
            st.warning("삭제할 사진을 체크해 주세요.")
        else:
            keep = [i for i in range(st.session_state.photo_count) if i not in to_delete]
            reindex_after_delete(keep)
            st.success("선택한 사진을 삭제했습니다.")

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
            label = custom.strip() if (choice == "직접입력" and custom.strip()) else choice

            pil_img = None
            uploaded = st.session_state.get(f"fu_{i}")
            if uploaded is not None:
                try:
                    pil_img = Image.open(uploaded).convert("RGB")
                except Exception:
                    pil_img = None

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
- **사진 버튼** 하나로 *사진보관함/사진찍기/파일선택* 선택 가능합니다(모바일 브라우저별 UI 상이).
- **선택 삭제**: 각 사진 카드 왼쪽 체크 → **🗑 선택 삭제**.
- **캐스케이드**: 드롭다운에서 항목 선택 또는 **직접입력** 사용.
- **환기**: **직접입력**만 제공.
- 모든 사진은 **4:3 비율(패딩)** 로 보정, PDF 내 자동 리사이즈/압축.
- 한글 폰트는 저장소 루트에 `NanumGothic.ttf`를 두면 깨지지 않습니다.
        """
    )
