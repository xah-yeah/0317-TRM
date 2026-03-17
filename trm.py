import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz  # PyMuPDF

# --- 1. 설정 및 API 연결 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
# 구글 시트 연결 설정
conn = st.connection("gsheets", type=GSheetsConnection)

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def analyze_and_draft(text, db_data_json, job_description=""):
    prompt = f"""당신은 전문 채용 담당자입니다. 아래 지침에 따라 JSON으로만 응답하세요.
    1. 후보자 정보 추출: name, email, summary(경력/학력)
    2. 중복 체크: 기존 DB({db_data_json})와 대조하여 similarity(0-100)와 matched_name 추출.
    3. 개인화 메시지 작성: 제공된 JD를 바탕으로 따뜻한 영입 메시지 작성.
    [우리 회사 JD]: {job_description}
    [응답 양식]: {{"name":"", "email":"", "summary":"", "similarity":0, "matched_name":"", "draft_message":""}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n[이력서]\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. 데이터 로드 ---
try:
    # 실시간 데이터 로드 (캐시 0초)
    df = conn.read(ttl=0)
except Exception as e:
    st.error(f"데이터를 불러오지 못했습니다: {e}")
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

# --- 3. UI 구성 (사이드바 필터 포함) ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

# 메뉴 및 사이드바 포지션 필터
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("📌 Menu", menu)

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
        jd_input = st.text_area("우리 회사 JD (개인화 메시지용)", height=150)
    
    if uploaded_file and pos:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        
        with st.spinner('AI 분석 중...'):
            result = analyze_and_draft(raw_text, db_subset, jd_input)
        
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
            # 기존 데이터에 새 데이터 합치기
            final_df = pd.concat([df, new_row], ignore_index=True)
            # 구글 시트에 다시 쓰기 (create가 가장 확실함)
            conn.create(data=final_df)
            st.balloons()
            st.success("구글 시트에 성공적으로 저장되었습니다!")

elif choice == "파이프라인 관리":
    st.header(f"📊 {sidebar_pos} 파이프라인")
    
    # 필터링 적용
    display_df = df.copy()
    if sidebar_pos != "전체":
        display_df = display_df[display_df['position'] == sidebar_pos]
    
    search_q = st.text_input("🔍 키워드 검색 (이름/회사/학교)")
    if search_q:
        display_df = display_df[display_df.apply(lambda row: search_q.lower() in str(row).lower(), axis=1)]

    st.write(f"현재 결과: {len(display_df)}명")
    # 인덱스 숨기기 및 에디터 출력
    edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True)
    
    if st.button("변경사항 저장"):
        # 수정된 내용 반영하여 전체 저장
        df.update(edited_df)
        final_save = pd.concat([df, edited_df[~edited_df.index.isin(df.index)]])
        conn.create(data=final_save)
        st.success("구글 시트 동기화 완료!")
