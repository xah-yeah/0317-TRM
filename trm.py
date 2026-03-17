import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF

# --- 1. 설정 및 API 연결 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

# PDF 텍스트 추출
def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

# AI 분석 및 메시지 생성 함수
def analyze_and_draft(text, db_data_json, job_description=""):
    prompt = f"""당신은 전문 채용 담당자입니다. 아래 지침에 따라 JSON으로만 응답하세요.
    
    [미션]
    1. 후보자 정보 추출: name, email, summary(경력/학력)
    2. 중복 체크: 기존 DB({db_data_json})와 대조하여 similarity(0-100)와 matched_name 추출.
    3. 개인화 메시지: 아래 제공된 JD를 바탕으로 후보자의 강점을 언급하며 우리 회사에 입사 제안을 하는 따뜻한 메시지를 작성하세요.
    
    [우리 회사 JD]
    {job_description}
    
    [응답 양식]
    {{
        "name": "이름",
        "email": "이메일",
        "summary": "요약",
        "similarity": 85,
        "matched_name": "유사 인물",
        "draft_message": "안녕하세요 OOO님, 이력서를 검토하며 ... (메시지 내용)"
    }}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n[이력서]\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. 데이터 로드 ---
try:
    # 실시간 데이터 강제 로드
    df = conn.read(ttl="0")
except:
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

# --- 3. UI 구성 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

# 사이드바 메뉴 및 필터
st.sidebar.header("📌 Menu")
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("이동하기", menu)

# 추가 기능: 사이드바 포지션 필터
st.sidebar.divider()
st.sidebar.header("🔍 포지션 필터")
all_pos = ["전체"] + sorted(df['position'].unique().tolist()) if not df.empty else ["전체"]
sidebar_pos = st.sidebar.radio("보고 싶은 포지션 선택", all_pos)

# --- 4. 기능 구현 ---

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석")
    
    col_a, col_b = st.columns(2)
    with col_a:
        pos = st.text_input("채용 포지션")
        uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    with col_b:
        jd_input = st.text_area("우리 회사 JD (여기에 붙여넣으면 개인화 메시지가 생성됩니다)", height=150)
    
    if uploaded_file and pos:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        
        with st.spinner('AI가 분석 및 메시지를 작성 중입니다...'):
            result = analyze_and_draft(raw_text, db_subset, jd_input)
        
        st.divider()
        if result['similarity'] > 70:
            st.error(f"🚨 중복 의심: [{result['matched_name']}]님과 유사도 {result['similarity']}%")
        else:
            st.success(f"✅ 신규 후보자 ({result['name']}님)")

        # 개인화 메시지 표시
        st.subheader("✉️ AI 제안 메시지 초안")
        st.info(result['draft_message'])
        
        if st.button("DB(구글 시트)에 최종 저장"):
            new_row = {
                "name": result['name'], "email": result['email'], "career_summary": result['summary'],
                "position": pos, "status": "컨택 중", "revisit_date": "", "added_date": datetime.now().strftime("%Y-%m-%d")
            }
            # 저장 로직 보강
            updated_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            conn.update(data=updated_df)
            st.balloons()
            st.success("구글 시트에 성공적으로 저장되었습니다!")

elif choice == "파이프라인 관리":
    st.header(f"📊 {sidebar_pos} 파이프라인")
    
    # 사이드바 필터 적용
    display_df = df.copy()
    if sidebar_pos != "전체":
        display_df = display_df[display_df['position'] == sidebar_pos]
    
    search_q = st.text_input("🔍 키워드 검색 (이름/회사/학교)")
    if search_q:
        display_df = display_df[display_df.apply(lambda row: search_q.lower() in str(row).lower(), axis=1)]

    edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True)
    
    if st.button("변경사항 저장"):
        # 수정된 내용 병합 후 저장
        df.update(edited_df)
        final_save = pd.concat([df, edited_df[~edited_df.index.isin(df.index)]])
        conn.update(data=final_save)
        st.success("동기화 완료!")
