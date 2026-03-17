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

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    return text

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

try:
    df = conn.read(ttl="0")
except:
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("Menu", menu)

# --- 3. 메뉴별 기능 구현 ---

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석")
    pos = st.text_input("채용 포지션 (예: SE, 마케터, 개발자)")
    uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    
    if uploaded_file and pos:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        
        with st.spinner('AI 분석 중...'):
            result = analyze_resume(raw_text, db_subset)
        
        st.divider()
        if result['similarity'] > 70:
            st.error(f"🚨 중복 의심: 기존 DB의 **[{result['matched_name']}]**님과 유사도 {result['similarity']}%")
        else:
            st.success(f"✅ 신규 후보자입니다! (유사도 {result['similarity']}%)")
            st.info(f"**분석된 정보:** {result['name']} / {result['email']}")
            st.write(f"**요약:** {result['summary']}")
        
        if st.button("DB(구글 시트)에 저장하기"):
            new_data = pd.DataFrame([{
                "name": result['name'], 
                "email": result['email'], 
                "career_summary": result['summary'],
                "position": pos, 
                "status": "컨택 중", 
                "revisit_date": "", 
                "added_date": datetime.now().strftime("%Y-%m-%d")
            }])
            updated_df = pd.concat([df, new_data], ignore_index=True)
            conn.update(data=updated_df)
            st.balloons()
            st.success(f"{result['name']}님의 정보가 저장되었습니다!")

elif choice == "파이프라인 관리":
    st.header("📊 채용 파이프라인 관리")
    col1, col2 = st.columns(2)
    with col1:
        available_positions = ["전체"] + sorted(df['position'].unique().tolist()) if not df.empty else ["전체"]
        selected_pos = st.selectbox("🎯 직무/포지션별 필터", available_positions)
    with col2:
        search_q = st.text_input("🔍 통합 검색 (이름, 회사명, 학교명 등)", placeholder="예: 삼성전자, 서울대")

    filtered_df = df.copy()
    if selected_pos != "전체":
        filtered_df = filtered_df[filtered_df['position'] == selected_pos]
    if search_q:
        filtered_df = filtered_df[
            filtered_df['name'].str.contains(search_q, na=False, case=False) | 
            filtered_df['career_summary'].str.contains(search_q, na=False, case=False)
        ]

    st.write(f"검색 결과: **{len(filtered_df)}** 명")
    edited_df = st.data_editor(filtered_df, num_rows="dynamic", use_container_width=True)
    
    if st.button("변경사항 저장 (구글 시트 동기화)"):
        # 인덱스를 기준으로 원본 데이터 업데이트
        for idx, row in edited_df.iterrows():
            df.loc[idx] = row
        # 새로운 행 추가 (인덱스가 기존 df에 없는 경우)
        new_rows = edited_df[~edited_df.index.isin(df.index)]
        final_df = pd.concat([df, new_rows])
        conn.update(data=final_df)
        st.success("데이터가 성공적으로 업데이트되었습니다!")

elif choice == "리비짓 알림":
    st.header("🔔 리비짓(재컨택) 대상자")
    if not df.empty:
        revisit_list = df[df['status'].str.contains('리비짓', na=False, case=False)]
        if not revisit_list.empty:
            st.dataframe(revisit_list, use_container_width=True)
        else:
            st.info("현재 리비짓 상태인 후보자가 없습니다.")
