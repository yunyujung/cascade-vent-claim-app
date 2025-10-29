import os
os.system("pip install streamlit reportlab pillow")

# -*- coding: utf-8 -*-
# 캐스케이드/환기 기성 청구 양식 - 동적 사진(최대 9컷), 3xN 그리드 PDF (ID기반 관리)

import io
import re
import unicodedata
import uuid
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
# 세션 상태 (ID 기반 아이템 리스트)
# ─────────────────────────────────────────
if "items" not in st.session_state:
    # 각 항목: {"id": str, "choice": "장비납품" 등, "custom": ""}
    st.session_state.items = [{"id": str(uuid.uuid4()), "choice": "장비납품", "custom": ""}]

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
# 상단 UI
# ─────────────────────────────────────────
st.markdown("### 캐스케이드/환기 기성 청구 양식")
st.info("모바일에서 **사진 버튼**을 누르면 *사진보관함/사진찍기/파일선택*이 뜹니다. 모든 사진은 4:3 비율로 자동 보정됩니다.")

# 모드 선택
mode = st.radio("양식 종류 선택", options=["캐스케이드", "환기"], horizontal=True,
                index=0 if st.session_state.mode == "캐스케이드" else 1)
st.session_state.mode = mode
options = CASCADE_OPTIONS if mode == "캐스케이드" else VENT_OPTIONS

# 현장 주소
site_addr = st.text_input("현장 주소", value=st.session_state.get("site_addr", ""),
                          placeholder="예: 서울특별시 ○○구 ○○로 12, 101동 101호")
st.session_state.site_addr = site_addr

# 입력 요약 표시
st.caption(f"🧭 현재 현장 주소: {site_addr or '-'}")

# ─────────────────────────────────────────
# 사진 카드 렌더링 (가로 한 줄: [삭제][번호][사진버튼][드롭다운][직접입력])
# ─────────────────────────────────────────
to_delete_ids = []

for idx, item in enumerate(st.session_state.items):
    item_id = item["id"]
    col_del, col_no, col_btn, col_sel, col_custom = st.columns([0.5, 0.6, 2.0, 2.0, 2.2])

    with col_del:
        del_ck = st.checkbox(" ", key=f"del_{item_id}", help="삭제 선택")
        if del_ck:
            to_delete_ids.append(item_id)

    with col_no:
        st.markdown(f"**{idx+1}.**")  # 순번 표시(자동 재부여)

    with col_btn:
        up = st.file_uploader("📷 사진 (촬영/보관함/파일)", type=["jpg", "jpeg", "png"], key=f"fu_{item_id}")
        # 미리보기
        if up is not None:
            try:
                img = Image.open(up)
                st.image(img, use_container_width=True)
            except Exception:
                st.caption("미리보기를 표시할 수 없습니다.")

    with col_sel:
        default_choice = item.get("choice", options[0])
        choice = st.selectbox("항목", options=options, key=f"sel_{item_id}",
                              index=(options.index(default_choice) if default_choice in options else 0))
        item["choice"] = choice  # 상태 갱신

    with col_custom:
        custom_val = item.get("custom", "")
        if item["choice"] == "직접입력":
            custom_val = st.text_input("항목명 직접입력", value=custom_val, key=f"custom_{item_id}", placeholder="예: 배기후드 시공 전·후")
            item["custom"] = custom_val
        else:
            # 다른 항목 선택 시 커스텀은 숨기되 값은 유지
            st.caption("—")

# 하단 제어 버튼
cc1, cc2, cc3 = st.columns([1,1,6])
with cc1:
    if st.button("➕ 사진 추가", use_container_width=True):
        if len(st.session_state.items) < MAX_PHOTOS:
            st.session_state.items.append({"id": str(uuid.uuid4()),
                                           "choice": options[0],
                                           "custom": ""})
        else:
            st.warning("최대 9장까지 추가할 수 있습니다.")
with cc2:
    if st.button("🗑 선택 삭제", use_container_width=True):
        if not to_delete_ids:
            st.warning("삭제할 사진을 체크해 주세요.")
        else:
            st.session_state.items = [it for it in st.session_state.items if it["id"] not in to_delete_ids]
            # 체크박스/업로드 키는 ID기반이므로 남은 항목은 그대로, 번호는 자동 재부여됨
            st.success("선택한 사진을 삭제했습니다.")

# 제출 버튼
submitted = st.button("📄 PDF 생성")

if submitted:
    try:
        titled_images: List[Tuple[str, Optional[Image.Image]]] = []

        for item in st.session_state.items:
            item_id = item["id"]
            choice = item.get("choice", "직접입력")
            custom = item.get("custom", "")
            label = custom.strip() if (choice == "직접입력" and custom.strip()) else choice

            pil_img = None
            up = st.session_state.get(f"fu_{item_id}")
            if up is not None:
                try:
                    pil_img = Image.open(up).convert("RGB")
                    pil_img = enforce_aspect_pad(pil_img, 4/3)
                except Exception:
                    pil_img = None

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
- **가로 배치**: [삭제체크] [번호] [사진 버튼] [항목 드롭다운] [직접입력].
- **선택 삭제**: 삭제할 항목에 체크 → **🗑 선택 삭제** (중간 번호가 비지 않고 자동 재번호).
- **현장 주소**: 화면 상단에 입력하고, PDF 상단 메타에도 반영됩니다.
- **사진 업로드**: 하나의 사진 버튼으로 *사진보관함/사진찍기/파일선택* 제공(모바일 브라우저 UI에 따라 다소 차이).
- **비율 보정**: 모든 사진은 **4:3 비율(패딩)** 로 보정, PDF 내 자동 리사이즈/압축.
- **한글 폰트**: 저장소 루트에 `NanumGothic.ttf`를 두면 PDF 내 한글 깨짐 방지.
        """
    )
