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
        if df.empty:
            return pd.DataFrame(columns=["name", "email", "career_summary", "position", "status", "revisit_date", "added_date"])
        # 상태가 없는 사람을 '미분류'로 채움 (1번 문제 해결)
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
        if s in counts: st.sidebar.write(f"{s}: **{counts
