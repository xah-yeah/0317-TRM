import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup

# --- 1. 설정 및 API 연결 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# URL에서 JD 텍스트를 긁어오는 함수
def get_jd_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        # 불필요한 태그 제거 후 텍스트만 추출
        for script in soup(["script", "style"]):
            script.decompose()
        return soup.get_text()[:3000] # 너무 길면 잘라서 전달
    except:
        return "URL을 읽어오는 데 실패했습니다."

def analyze_and_draft(text, db_data_json, jd_text=""):
    prompt = f"""당신은 전문 채용 담당자입니다. 아래 지침에 따라 JSON으로만 응답하세요.
    1. 후보자 정보 추출: name, email, summary(경력/학력)
    2. 중복 체크: 기존 DB({db_data_json})와 대조하여 similarity(0-100)와 matched_name 추출.
    3. 개인화 메시지 작성: 제공된 JD 내용을 바탕으로 후보자의 강점을 언급하며 영입 메시지를 작성하세요.
    [우리 회사 JD]: {jd_text}
    [응답 양식]: {{"name":"", "email":"", "summary":"", "similarity":0, "matched_name":"", "draft_message":""}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n[이력서]\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. 데이터 로드 ---
try:
    df = conn.read(ttl=0)
except:
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

# --- 3. UI 구성 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("📌 Menu", menu)

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석 및 JD 매칭")
    col_a, col_b = st.columns(2)
    with col_a:
        pos = st.text_input("채용 포지션")
        uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    with col_b:
        # JD를 직접 입력하거나 URL을 넣을 수 있게 선택권 부여
        jd_source = st.radio("JD 입력 방식", ["URL 주소 넣기", "직접 텍스트 입력"])
        if jd_source == "URL 주소 넣기":
            jd_input = st.text_input("공고 URL (예: https://company.com/jobs/1)")
        else:
            jd_input = st.text_area("JD 텍스트 직접 입력", height=150)
    
    if uploaded_file and pos and jd_input:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        
        # URL 방식일 경우 텍스트 크롤링 수행
        final_jd = get_jd_from_url(jd_input) if jd_source == "URL 주소 넣기" else jd_input
        
        with st.spinner('AI가 JD를 읽고 맞춤형 메시지를 작성 중입니다...'):
            result = analyze_and_draft(raw_text, db_subset, final_jd)
        
        st.divider()
        if result['similarity'] > 70:
            st.error(f"🚨 중복 의심: [{result['matched_name']}]님과 유사도 {result['similarity']}%")
        else:
            st.success(f"✅ 신규 후보자 ({result['name']}님)")

        st.subheader("✉️ AI 제안 메시지 초안")
        st.info(result['draft_message'])
        
        if st.button("DB(구글 시트)에 최종 저장"):
            new_row = pd.DataFrame([{
                "name": result['name'], "email": result['email'], "career_summary": result['summary'],
                "position": pos, "status": "컨택 중", "revisit_date": "", "added_date": datetime.now().strftime("%Y-%m-%d")
            }])
            final_df = pd.concat([df, new_row], ignore_index=True)
            conn.create(data=final_df)
            st.balloons()
            st.success("성공적으로 저장되었습니다!")

# (파이프라인 관리 및 리비짓 알림 코드는 이전과 동일)
elif choice == "파이프라인 관리":
    # ... 이전 코드와 동일 ...
    st.write("파이프라인 관리 화면")
    # (생략: 이전 답변의 파이프라인 관리 코드를 그대로 사용하세요)
