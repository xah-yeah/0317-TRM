import streamlit as st
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

# --- 1. 설정 및 API 연결 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 구글 시트 CSV 내보내기 URL로 변환 (권한 에러 방지용)
SHEET_URL = st.secrets["connections"]["gsheets"]["spreadsheet"]
CSV_URL = SHEET_URL.replace("/edit?gid=", "/export?format=csv&gid=").replace("/edit#gid=", "/export?format=csv&gid=")

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def get_jd_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.decompose()
        return soup.get_text()[:3000]
    except:
        return "URL 읽기 실패"

def analyze_and_draft(text, db_data_json, jd_text=""):
    prompt = f"""당신은 전문 채용 담당자입니다. JSON으로만 응답하세요.
    1. 후보자 정보: name, email, summary
    2. 중복 체크: 기존 DB({db_data_json}) 대조 similarity(0-100), matched_name
    3. 제안 메시지 작성: {jd_text} 참고
    양식: {{"name":"", "email":"", "summary":"", "similarity":0, "matched_name":"", "draft_message":""}}"""
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n 이력서:\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. 데이터 로드 (에러 방지용) ---
@st.cache_data(ttl=0)
def load_data():
    try:
        return pd.read_csv(CSV_URL)
    except:
        return pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

df = load_data()

# --- 3. UI 구성 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

# 메뉴 구성
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("📌 메뉴 선택", menu)

# 사이드바 필터
st.sidebar.divider()
st.sidebar.header("🔍 포지션 필터")
all_pos = ["전체"] + sorted(df['position'].unique().tolist()) if not df.empty else ["전체"]
sidebar_pos = st.sidebar.radio("보고 싶은 포지션", all_pos)

# --- 4. 메뉴별 기능 구현 ---

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석 및 JD 매칭")
    
    # UI 복구: 입력창을 변수에 확실히 할당
    col1, col2 = st.columns(2)
    with col1:
        target_pos = st.text_input("채용 포지션 (필수)", placeholder="예: SE, 기획자")
        up_file = st.file_uploader("이력서 PDF (필수)", type="pdf")
    with col2:
        jd_type = st.radio("JD 입력 방식", ["URL", "텍스트"])
        jd_val = st.text_input("URL 주소") if jd_type == "URL" else st.text_area("JD 내용")

    # 모든 값이 입력되었을 때만 분석 버튼 활성화
    if up_file and target_pos and jd_val:
        if st.button("AI 분석 시작"):
            raw_txt = extract_text_from_pdf(up_file)
            db_json = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False)
            jd_txt = get_jd_from_url(jd_val) if jd_type == "URL" else jd_val
            
            with st.spinner('분석 중...'):
                res = analyze_and_draft(raw_txt, db_json, jd_txt)
            
            st.session_state['last_res'] = res
            st.session_state['target_pos'] = target_pos

        if 'last_res' in st.session_state:
            res = st.session_state['last_res']
            st.divider()
            if res['similarity'] > 70:
                st.error(f"🚨 중복 의심: {res['matched_name']} (유사도 {res['similarity']}%)")
            else:
                st.success(f"✅ 신규 후보자: {res['name']}님")
            
            st.subheader("✉️ AI 제안 메시지")
            st.info(res['draft_message'])
            
            st.warning("⚠️ 현재 구글 시트 직접 쓰기 권한 에러가 발생하고 있습니다. [공유] 설정에서 '편집자' 권한을 다시 확인하거나, 아래 데이터를 복사해 시트에 직접 붙여넣으세요.")
            st.code(f"{res['name']}, {res['email']}, {st.session_state['target_pos']}, 컨택 중")

elif choice == "파이프라인 관리":
    st.header(f"📊 {sidebar_pos} 현황")
    view_df = df.copy()
    if sidebar_pos != "전체": view_df = view_df[view_df['position'] == sidebar_pos]
    
    q = st.text_input("검색 (이름/회사/학교)")
    if q: view_df = view_df[view_df.apply(lambda r: q.lower() in str(r).lower(), axis=1)]
    
    st.dataframe(view_df, use_container_width=True)
