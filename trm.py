import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import json
from openai import OpenAI
import fitz
import requests
from bs4 import BeautifulSoup

# --- 1. 설정 및 API 연결 ---
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

def extract_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = "".join([page.get_text() for page in doc])
    return text

def get_jd_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(["script", "style"]): s.decompose()
        return soup.get_text()[:3000]
    except: return "JD 로드 실패"

# --- 2. 데이터 로드 및 전처리 ---
def load_data():
    try:
        df = conn.read(ttl=0)
        # 상태가 없는(None) 사람을 '미분류'로 채워줌 (1번 문제 해결)
        df['status'] = df['status'].fillna('미분류')
        return df
    except:
        return pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])

df = load_data()

# 채용 단계 설정 (2번 문제 해결: 스크리닝 추가)
STATUS_OPTIONS = ["스크리닝", "컨택 중", "면접 진행", "최종 합격", "처우 협의", "불합격", "리비짓", "미분류"]

# --- 3. UI 구성 ---
st.set_page_config(page_title="AI TRM Pro", layout="wide")

st.sidebar.title("🎯 AI 채용 센터")
menu = ["📊 대시보드 & 파이프라인", "➕ 신규 후보자 등록", "🔔 리비짓 대상자"]
choice = st.sidebar.selectbox("메뉴", menu)

if not df.empty:
    st.sidebar.divider()
    st.sidebar.subheader("📈 현재 파이프라인")
    counts = df['status'].value_counts()
    for s in STATUS_OPTIONS:
        if s in counts: st.sidebar.write(f"{s}: **{counts[s]}명**")

# --- 4. 메뉴별 기능 구현 ---

# [메뉴 1: 대시보드]
if choice == "📊 대시보드 & 파이프라인":
    st.header("📊 전체 채용 현황")
    
    # 상단 요약
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("전체", len(df))
    m2.metric("스크리닝/컨택", len(df[df['status'].isin(['스크리닝', '컨택 중'])]))
    m3.metric("면접 진행", len(df[df['status'] == '면접 진행']))
    m4.metric("리비짓", len(df[df['status'] == '리비짓']))

    st.divider()

    # 필터 영역
    c1, c2 = st.columns([1, 3])
    with c1:
        st.write("### ⚙️ 필터")
        pos_f = st.multiselect("포지션", options=df['position'].unique(), default=df['position'].unique())
        stat_f = st.multiselect("단계", options=STATUS_OPTIONS, default=["스크리닝", "컨택 중", "면접 진행"])
    
    with c2:
        st.write("### 📝 리스트 관리")
        view_df = df[(df['position'].isin(pos_f)) & (df['status'].isin(stat_f))]
        
        edited_df = st.data_editor(
            view_df,
            column_config={
                "status": st.column_config.SelectboxColumn("상태 변경", options=STATUS_OPTIONS, required=True)
            },
            use_container_width=True, num_rows="dynamic"
        )

    if st.button("💾 변경사항 구글 시트에 저장"):
        df.update(edited_df)
        final_df = pd.concat([df, edited_df[~edited_df.index.isin(df.index)]])
        conn.create(data=final_df)
        st.success("업데이트 완료!")
        st.rerun()

# [메뉴 2: 등록 - 3번 문제 해결: 업로드 UI 복구]
elif choice == "➕ 신규 후보자 등록":
    st.header("📄 신규 후보자 분석 및 등록")
    st.info("이력서를 업로드하면 AI가 요약한 뒤 기본적으로 '스크리닝' 단계로 등록합니다.")
    
    col_up1, col_up2 = st.columns(2)
    with col_up1:
        target_pos = st.text_input("채용 포지션 (예: SE, Backend)")
        uploaded_file = st.file_uploader("이력서 PDF 파일 업로드", type="pdf")
    with col_up2:
        jd_mode = st.radio("JD 입력 방식", ["주소(URL) 넣기", "내용 직접 쓰기"])
        jd_val = st.text_input("공고 URL") if jd_mode == "주소(URL) 넣기" else st.text_area("공고 내용")

    if uploaded_file and target_pos and jd_input := jd_val:
        if st.button("🔍 AI 분석 시작"):
            raw = extract_text_from_pdf(uploaded_file)
            db_json = df[['name', 'career_summary']].to_json(orient='records', force_ascii=False)
            final_jd = get_jd_from_url(jd_val) if jd_mode == "주소(URL) 넣기" else jd_val
            
            with st.spinner('AI 분석 중...'):
                prompt = f"후보자 정보 추출 및 JD 매칭 제안서 작성. JSON 응답: {{\"name\":\"\",\"email\":\"\",\"summary\":\"\",\"similarity\":0,\"matched_name\":\"\",\"draft_message\":\"\"}}"
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":prompt + f"\n\nJD: {final_jd}\n\n이력서: {raw}"}],
                    response_format={"type":"json_object"}
                )
                st.session_state['last_res'] = json.loads(response.choices[0].message.content)
                st.session_state['curr_pos'] = target_pos

    if 'last_res' in st.session_state:
        res = st.session_state['last_res']
        st.divider()
        if res['similarity'] > 70: st.error(f"🚨 중복 의심: {res['matched_name']} ({res['similarity']}%)")
        else: st.success(f"✅ 신규 후보자: {res['name']}님")
        
        st.subheader("✉️ AI 제안 메시지")
        st.info(res['draft_message'])
        
        if st.button("📥 DB에 '스크리닝' 단계로 저장"):
            new_data = {
                "name": res['name'], "email": res['email'], "career_summary": res['summary'],
                "position": st.session_state['curr_pos'], "status": "스크리닝", 
                "added_date": datetime.now().strftime("%Y-%m-%d")
            }
            # 최신화 후 저장
            latest_df = conn.read(ttl=0)
            updated_df = pd.concat([latest_df, pd.DataFrame([new_data])], ignore_index=True)
            conn.create(data=updated_df)
            st.balloons()
            st.success("저장 성공! '대시보드'에서 확인하세요.")
            del st.session_state['last_res'] # 저장 후 초기화

# [메뉴 3: 리비짓]
elif choice == "🔔 리비짓 대상자":
    st.header("🔔 다시 연락해볼 후보자들")
    st.dataframe(df[df['status'] == '리비짓'], use_container_width=True)
