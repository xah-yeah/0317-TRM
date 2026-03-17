import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz
import requests
from bs4 import BeautifulSoup

# --- 설정 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 데이터 로드 함수 ---
def load_data():
    try:
        return conn.read(ttl=0)
    except:
        return pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

df = load_data()

# --- UI 설정 ---
st.set_page_config(page_title="AI TRM Dashboard", layout="wide")

# --- 사이드바: 메뉴 및 대시보드 통계 ---
st.sidebar.title("🎯 AI 채용 센터")
menu = ["대시보드 & 파이프라인", "신규 후보자 등록", "리비짓 대상자"]
choice = st.sidebar.selectbox("메뉴", menu)

if not df.empty:
    st.sidebar.divider()
    st.sidebar.subheader("📊 실시간 현황")
    status_counts = df['status'].value_counts()
    for s_name, s_count in status_counts.items():
        st.sidebar.write(f"**{s_name}**: {s_count}명")

# --- 기능 구현 ---

# 1. 대시보드 & 파이프라인 (상태 관리 핵심)
if choice == "대시보드 & 파이프라인":
    st.header("📊 채용 파이프라인 현황")
    
    # 상단 요약 카드
    cols = st.columns(4)
    cols[0].metric("전체 후보자", len(df))
    cols[1].metric("컨택 중", len(df[df['status'] == '컨택 중']))
    cols[2].metric("면접 진행", len(df[df['status'] == '면접 진행']))
    cols[3].metric("리비짓 대상", len(df[df['status'].str.contains('리비짓', na=False)]))

    st.divider()

    # 필터 및 편집
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("⚙️ 리스트 필터")
        pos_filter = st.multiselect("포지션 선택", options=df['position'].unique(), default=df['position'].unique())
        status_filter = st.multiselect("상태 선택", options=["컨택 중", "면접 진행", "최종 합격", "처우 협의", "불합격", "리비짓"], default=["컨택 중", "면접 진행", "최종 합격"])
    
    with col2:
        st.subheader("📝 상태 변경 및 정보 수정")
        view_df = df[(df['position'].isin(pos_filter)) & (df['status'].isin(status_filter))]
        
        # 데이터 에디터 (여기서 Status 열을 드롭다운처럼 수정 가능)
        edited_df = st.data_editor(
            view_df,
            column_config={
                "status": st.column_config.SelectboxColumn(
                    "채용 상태",
                    options=["컨택 중", "면접 진행", "최종 합격", "처우 협의", "불합격", "리비짓"],
                    required=True,
                )
            },
            use_container_width=True,
            num_rows="dynamic"
        )

    if st.button("💾 변경사항 구글 시트에 최종 반영"):
        # 수정된 내용 합치기 로직
        df.update(edited_df)
        final_df = pd.concat([df, edited_df[~edited_df.index.isin(df.index)]])
        conn.create(data=final_df)
        st.success("데이터가 성공적으로 업데이트되었습니다!")
        st.rerun()

# 2. 신규 후보자 등록 (기존 로직 유지)
elif choice == "신규 후보자 등록":
    st.header("📄 신규 이력서 분석")
    # ... (기존 이력서 업로드 및 분석 코드 동일)
    st.info("이력서를 업로드하면 AI가 자동으로 요약하고 '컨택 중' 상태로 등록합니다.")

# 3. 리비짓 알림
elif choice == "리비짓 대상자":
    st.header("🔔 리비짓 관리")
    revisit_df = df[df['status'] == '리비짓']
    st.dataframe(revisit_df, use_container_width=True)
