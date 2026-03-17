import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF

# --- 설정 및 연결 ---
# Streamlit Cloud의 Secrets에 입력한 키를 사용합니다.
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 구글 시트 연결
conn = st.connection("gsheets", type=GSheetsConnection)

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def analyze_resume(text, db_summaries):
    prompt = f"""당신은 전문 채용 담당자입니다. 이력서를 분석하여 JSON으로만 응답하세요.
    1. 성함(name), 이메일(email), 경력요약(summary)을 추출하세요.
    2. 기존 경력 리스트({db_summaries})와 비교하여 동일인 확률(similarity, 0-100)을 계산하세요.
    형식: {{"name": "이름", "email": "이메일", "summary": "경력요약", "similarity": 80}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- UI 화면 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

try:
    df = conn.read(ttl="0")
except:
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("Menu", menu)

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석")
    pos = st.text_input("채용 포지션")
    uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    
    if uploaded_file and pos:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_summaries = df['career_summary'].tolist() if not df.empty else []
        
        with st.spinner('AI가 이력서 정보를 정제하고 중복을 확인 중입니다...'):
            result = analyze_resume(raw_text, db_summaries)
        
        st.divider()
        st.subheader(f"분석된 후보자: {result['name']}님")
        
        if result['similarity'] > 70:
            st.warning(f"⚠️ 중복 가능성 높음: {result['similarity']}% (기존 DB와 경력이 유사합니다)")
        else:
            st.success(f"✅ 신규 후보자 가능성 높음 (유사도 {result['similarity']}%)")
            
        st.info(f"**경력 요약:** {result['summary']}")
        
        if st.button("DB(구글 시트)에 저장"):
            new_data = pd.DataFrame([{
                "name": result['name'], "email": result['email'], "career_summary": result['summary'],
                "position": pos, "status": "컨택 중", "revisit_date": "", "added_date": datetime.now().strftime("%Y-%m-%d")
            }])
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(data=updated_df)
            st.balloons()
            st.success("성공적으로 저장되었습니다!")

elif choice == "파이프라인 관리":
    st.header("📊 채용 파이프라인")
    edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    if st.button("변경사항 저장"):
        conn.update(data=edited_df)
        st.success("구글 시트에 동기화되었습니다.")

elif choice == "리비짓 알림":
    st.header("🔔 리비짓(재컨택) 대상자")
    revisit_list = df[df['status'].str.contains('리비짓', na=False)]
    st.dataframe(revisit_list)
