import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF

# --- 1. 설정 및 API 연결 ---
# Streamlit Cloud의 Secrets에서 키를 가져옵니다.
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

# PDF 텍스트 추출 함수
def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# AI 분석 함수 (중복 대상 추적 포함)
def analyze_resume(text, db_data_json):
    prompt = f"""당신은 전문 채용 담당자입니다. 이력서를 분석하여 JSON으로만 응답하세요.
    
    [미션]
    1. 후보자의 성함(name), 이메일(email), 경력 및 학력 요약(summary)을 추출하세요.
    2. 아래 제공된 기존 DB 데이터와 비교하여 동일인일 확률이 가장 높은 사람을 찾으세요.
    3. 동일인 확률(similarity, 0-100)과 해당 인물의 이름(matched_name)을 결과에 포함하세요.
    4. 만약 기존 DB가 비어있다면 similarity는 0으로 응답하세요.
    
    [기존 DB 데이터]
    {db_data_json}
    
    [응답 양식]
    {{
        "name": "후보자 이름",
        "email": "이메일",
        "summary": "경력 및 학력 요약(회사명, 학교명 포함)",
        "similarity": 85,
        "matched_name": "DB 내 유사 인물 이름 (없으면 빈칸)"
    }}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n[분석할 이력서 텍스트]\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. UI 화면 구성 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

# 실시간 데이터 불러오기
try:
    df = conn.read(ttl="0")
except:
    # 시트가 비어있을 경우 초기 스키마 설정
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

# 사이드바 메뉴
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("Menu", menu)

# --- 3. 메뉴별 기능 구현 ---

# 메뉴 A: 후보자 등록 및 AI 분석
if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석")
    pos = st.text_input("채용 포지션 (예: SE, 마케터, 개발자)")
    uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    
    if uploaded_file and pos:
        raw_text = extract_text_from_pdf(uploaded_file)
        
        # AI에게 전달할 기존 DB 요약 (이름과 경력만)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        
        with st.spinner('AI가 기존 DB와 대조하며 정밀 분석 중입니다...'):
            result = analyze_resume(raw_text, db_subset)
        
        st.divider()
        
        # 중복 의심 시 시각적 경고
        if result['similarity'] > 70:
            st.error(f"🚨 중복 의심: 기존 DB의 **[{result['matched_name']}]**님과 유사도 {result['similarity']}%")
            with st.expander("상세 대조 결과 확인"):
                st.write(f"**현재 후보자:** {result['name']}")
                st.write(f"**매칭된 인물:** {result['matched_name']}")
                st.write(f"**경력 요약:** {result['summary']}")
        else:
            st.success(f"✅ 신규 후보자입니다! (유사도 {result['similarity']}%)")
            st.info(f"**분
