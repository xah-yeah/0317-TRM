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
        return "URL을 읽어오는 데 실패했습니다. 직접 입력 방식을 사용해 주세요."

def analyze_and_draft(text, db_data_json, jd_text=""):
    prompt = f"""당신은 전문 채용 담당자입니다. 아래 지침에 따라 JSON으로만 응답하세요.
    1. 후보자 정보 추출: name, email, summary(경력/학력 요약)
    2. 중복 체크: 기존 DB({db_data_json})와 대조하여 similarity(0-100)와 matched_name 추출.
    3. 개인화 메시지: 아래 JD를 바탕으로 후보자의 강점을 언급한 영입 메시지 작성.
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

# --- 3. UI 구성 ---
st.set_page_config(page_title="AI TRM System", layout="wide")
st.title("🎯 AI 채용 관리 시스템 (TRM)")

# 사이드바 구성
st.sidebar.header("📌 Menu")
menu = ["후보자 등록/분석", "파이프라인 관리", "리비짓 알림"]
choice = st.sidebar.selectbox("이동하기", menu)

st.sidebar.divider()
st.sidebar.header("🔍 포지션 필터")
all_pos = ["전체"] + sorted(df['position'].unique().tolist()) if not df.empty else ["전체"]
sidebar_pos = st.sidebar.radio("보고 싶은 포지션 선택", all_pos)

# --- 4. 기능 구현 ---

if choice == "후보자 등록/분석":
    st.header("📄 신규 이력서 분석 및 JD 매칭")
