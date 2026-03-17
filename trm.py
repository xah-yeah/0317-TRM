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

def get_jd_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.decompose()
        return soup.get_text()[:3000]
    except:
        return "URL을 읽어오는 데 실패했습니다."

def analyze_and_draft(text, db_data_json, jd_text=""):
    prompt = f"""당신은 전문 채용 담당자입니다. 이력서를 분석하여 JSON으로만 응답하세요.
    1. 후보자 정보: name, email, summary(경력/학력 요약)
    2. 중복 체크: 기존 DB({db_data_json})와 대조하여 similarity(0-100)와 matched_name 추출.
    3. 제안 메시지: JD를 참고하여 후보자 맞춤형 영입 제안서를 작성하세요.
    [우리 회사 JD]: {jd_text}
    [응답 양식]: {{"name":"", "email":"", "summary":"", "similarity":0, "matched_name":"", "draft_message":""}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt + "\n\n[이력서]\n" + text}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)

# --- 2. 데이터 실시간 로드 ---
try:
    df = conn.read(ttl=0)
except:
    df = pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

# --- 3. UI 구성 (사이드바) ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

st.sidebar.header("📌 Menu")
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("이동하기", menu)

st.sidebar.divider()
st.sidebar.header("🔍 포지션 필터")
all_pos = ["전체"] + sorted(df['position'].unique().tolist()) if not df.empty else ["전체"]
sidebar_pos = st.sidebar.radio("보고 싶은 포지션 선택", all_pos)

# --- 4. 메뉴별 기능 구현 ---

# [메뉴 1: 후보자 등록/분석]
if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석 및 JD 매칭")
    
    # UI가 사라지지 않도록 컬럼 구성 확인
    col_a, col_b = st.columns(2)
    with col_a:
        pos = st.text_input("채용 포지션 (예: SE, 기획자)")
        uploaded_file = st.file_uploader("PDF 이력서 업로드", type="pdf")
    with col_b:
        jd_source = st.radio("JD 입력 방식", ["URL 주소 넣기", "직접 텍스트 입력"])
        if jd_source == "URL 주소 넣기":
            jd_input = st.text_input("공고 URL 입력 (주소를 넣고 Enter를 누르세요)")
        else:
            jd_input = st.text_area("JD 내용 입력", height=150)
    
    # 분석 시작 버튼 (파일과 포지션, JD 정보가 다 있을 때만 실행)
    if uploaded_file and pos and jd_input:
        raw_text = extract_text_from_pdf(uploaded_file)
        db_subset = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False) if not df.empty else "[]"
        final_jd = get_jd_from_url(jd_input) if jd_source == "URL 주소 넣기" else jd_input
        
        with st.spinner('AI 분석 중...'):
            result = analyze_and_draft(raw_text, db_subset, final_jd)
        
        st.divider()
        if result['similarity'] > 70:
            st.error(f"🚨 중복 의심: [{result['matched_name']}]님과 유사도 {result['similarity']}%")
        else:
            st.success(f"✅ 신규 후보자 ({result['name']}님)")

        st.subheader("✉️ AI 제안 메시지 초안")
        st.info(result['draft_message'])
        
        if st.button("DB(구글 시트)에 최종 저장"):
            new_row = {
                "name": result['name'], "email": result['email'], "career_summary": result['summary'],
                "position": pos, "status": "컨택 중", "revisit_date": "", "added_date": datetime.now().strftime("%Y-%m-%d")
            }
            # 에러 방지를 위해 최신 데이터를 다시 읽고 합친 후 쓰기
            latest_df = conn.read(ttl=0)
            updated_df = pd.concat([latest_df, pd.DataFrame([new_row])], ignore_index=True)
            
            # 중요: UnsupportedOperationError를 피하기 위해 create 사용
            conn.create(data=updated_df)
            st.balloons()
            st.success("구글 시트에 성공적으로 저장되었습니다!")

# [메뉴 2: 파이프라인 관리]
elif choice == "파이프라인 관리":
    st.header(f"📊 {sidebar_pos} 파이프라인")
    
    display_df = df.copy()
    if sidebar_pos != "전체":
        display_df = display_df[display_df['position'] == sidebar_pos]
    
    search_q = st.text_input("🔍 통합 검색 (이름, 회사, 학교)")
    if search_q:
        display_df = display_df[display_df.apply(lambda row: search_q.lower() in str(row).lower(), axis=1)]

    st.write(f"조회된 후보자: {len(display_df)}명")
    edited_df = st.data_editor(display_df, num_rows="dynamic", use_container_width=True)
    
    if st.button("변경사항 저장"):
        # 수정 데이터 반영
        df.update(edited_df)
        final_save = pd.concat([df, edited_df[~edited_df.index.isin(df.index)]])
        conn.create(data=final_save)
        st.success("동기화 완료!")

# [메뉴 3: 리비짓 알림]
elif choice == "리비짓 알림":
    st.header("🔔 리비짓 대상자")
    if not df.empty:
        revisit_list = df[df['status'].str.contains('리비짓', na=False, case=False)]
        st.dataframe(revisit_list, use_container_width=True)
    else:
        st.write("데이터가 없습니다.")
