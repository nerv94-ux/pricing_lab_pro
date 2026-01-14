import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

# --- 1. 페이지 설정 및 프리미엄 디자인 (CSS) ---
st.set_page_config(page_title="프라이싱랩 프로 (Pricing Lab Pro)", layout="wide")

# 전문적인 디자인을 위한 CSS 주입
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; border-left: 5px solid #1E5631; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .stButton>button { border-radius: 5px; font-weight: 600; }
    .stDataFrame { border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    h1 { color: #1E5631; font-weight: 800; }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"구글 시트 인증 오류: {str(e)}")

# 세션 상태 초기화 (기존 유지)
if 'role' not in st.session_state: st.session_state.role = None 
if 'target_company' not in st.session_state: st.session_state.target_company = "일반거래처"
if 'calc_mode' not in st.session_state: st.session_state.calc_mode = "판매가 기준"
if 'fee_presets' not in st.session_state: st.session_state.fee_presets = [0, 6, 13, 15, 20]

# --- 2. 데이터 로드 및 자동 세척 함수 (기존 로직 100% 유지) ---
def load_data(worksheet_name="A_Work"):
    try:
        existing_data = conn.read(worksheet=worksheet_name, ttl=0)
        if existing_data is not None and not existing_data.empty:
            df = existing_data.copy()
            if '역산' not in df.columns: df['역산'] = False
            df['역산'] = df['역산'].fillna(False).astype(bool)
            num_cols = ['순서', '원가', '판매가', '마진%', '목표마진%', '수수료%']
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            return df
    except: pass
    return pd.DataFrame({
        '순서': [1, 2], '역산': [False, False], '품목': ['유기농 당근', '유기농 양파'],
        '규격': ['1kg', '500g'], '원가': [1000, 2000], '목표마진%': [20.0, 20.0],
        '마진%': [15.0, 15.0], '목표마진대비금액': [0.0, 0.0], '마진금액': [0.0, 0.0],
        '수수료%': [0, 0], '수수료금액': [0.0, 0.0], '판매가': [0.0, 0.0]
    })

# --- 3. [수정] 고성능 계산 엔진 (빈 칸 자동 0 처리 및 무한 행 지원) ---
def run_calculation_engine(df, mode):
    temp_df = df.copy()
    # 계산 전 숫자형 컬럼 보정 (3행 이후 빈 칸 에러 해결 핵심)
    num_cols = ['원가', '판매가', '마진%', '목표마진%', '수수료%']
    for col in num_cols:
        if col in temp_df.columns:
            temp_df[col] = pd.to_numeric(temp_df[col], errors='coerce').fillna(0)

    for i, row in temp_df.iterrows():
        try:
            fee_pct = float(row['수수료%']) / 100
            margin_pct = float(row['마진%']) / 100
            target_pct = float(row['목표마진%']) / 100
            
            if row['역산']:
                selling_price = float(row['판매가'])
                if mode == "판매가 기준":
                    cost = selling_price * (1 - margin_pct - fee_pct)
                else:
                    cost = (selling_price * (1 - fee_pct)) / (1 + margin_pct)
                temp_df.at[i, '원가'] = round(cost, 0)
            else:
                cost = float(row['원가'])
                if mode == "판매가 기준":
                    denom = (1 - margin_pct - fee_pct)
                    selling_price = cost / denom if denom > 0 else 0
                else:
                    selling_price = (cost * (1 + margin_pct)) / (1 - fee_pct) if (1 - fee_pct) > 0 else 0
                temp_df.at[i, '판매가'] = round(selling_price, 0)
            
            selling_price = temp_df.at[i, '판매가']
            cost = temp_df.at[i, '원가']
            fee_amt = selling_price * fee_pct
            margin_amt = selling_price - cost - fee_amt
            target_amt = (selling_price if mode == "판매가 기준" else cost) * target_pct
            
            temp_df.at[i, '수수료금액'] = round(fee_amt, 0)
            temp_df.at[i, '마진금액'] = round(margin_amt, 0)
            temp_df.at[i, '목표마진대비금액'] = round(margin_amt - target_amt, 0)
        except: continue
    return temp_df

# --- 4. 데이터 수정 핸들러 (기존 로직 100% 유지) ---
def on_data_change():
    state = st.session_state["main_editor"]
    df = st.session_state.data.copy()
    for row_idx, changes in state["edited_rows"].items():
        for col, val in changes.items():
            if col == "역산":
                name = str(df.iloc[row_idx]['품목'])
                df.iloc[row_idx, df.columns.get_loc('품목')] = f"[역산] {name}" if val else name.replace("[역산] ", "")
                df.iloc[row_idx, df.columns.get_loc('역산')] = val
            elif col == "순서":
                new_order = int(val)
                old_order = df.iloc[row_idx]['순서']
                if new_order <= old_order: df.loc[df['순서'] >= new_order, '순서'] += 1
                df.iloc[row_idx, df.columns.get_loc('순서')] = new_order
            elif col == "판매가" and not df.iloc[row_idx]['역산']:
                cost, fee_p = float(df.iloc[row_idx]['원가']), float(df.iloc[row_idx]['수수료%']) / 100
                new_price = float(val)
                new_m = (new_price - cost - (new_price * fee_p)) / new_price if st.session_state.calc_mode == "판매가 기준" else (new_price * (1 - fee_p) - cost) / cost
                df.iloc[row_idx, df.columns.get_loc('마진%')] = round(new_m * 100, 2)
                df.iloc[row_idx, df.columns.get_loc('판매가')] = new_price
            else: df.iloc[row_idx, df.columns.get_loc(col)] = val
    for row in state["added_rows"]:
        new_row = pd.Series({'순서': len(df)+1, '역산': False, '품목': '', '수수료%': 0, '원가': 0, '마진%': 0, '목표마진%': 0})
        df = pd.concat([df, new_row.to_frame().T], ignore_index=True)
    df = df.sort_values(by=['순서', '품목']).reset_index(drop=True)
    df['순서'] = range(1, len(df) + 1)
    st.session_state.data = run_calculation_engine(df, st.session_state.calc_mode)

# --- 5. 히스토리 로깅 및 자동 엔진 ---
def log_history(action, target_company):
    try:
        history_df = st.session_state.data.copy()
        history_df['작업시간'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_df['거래처명'] = target_company
        history_df['역할'] = st.session_state.role
        history_df['구분'] = action
        try:
            current_history = conn.read(worksheet="History", ttl=0)
            new_history = pd.concat([current_history, history_df], ignore_index=True)
        except: new_history = history_df
        conn.update(worksheet="History", data=new_history)
    except Exception as e: st.error(f"기록 실패: {str(e)}")

# --- 6. UI 섹션 ---
if st.session_state.role is None:
    st.title("🛡️ 프라이싱랩 프로 2.0")
    st.subheader("업무 시스템 진입을 위해 역할을 선택해 주세요.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🏢 A 업체 (공급사) 진입", use_container_width=True, type="primary"):
            st.session_state.role = "A"; st.session_state.data = load_data("A_Work"); st.rerun()
    with c2:
        if st.button("🏪 B 업체 (판매사) 진입", use_container_width=True, type="primary"):
            st.session_state.role = "B"; st.session_state.data = load_data("B_Work"); st.rerun()

else:
    with st.sidebar:
        st.title(f"🔐 {'공급사 A' if st.session_state.role == 'A' else '판매사 B'}")
        st.session_state.target_company = st.text_input("📍 현재 작업 거래처", value=st.session_state.target_company)
        if st.button("🚪 시스템 로그아웃", use_container_width=True): st.session_state.role = None; st.rerun()
        st.divider()
        st.subheader("📜 히스토리 자율 관리")
        try:
            history_all = conn.read(worksheet="History", ttl=0)
            if history_all is not None and not history_all.empty and '역할' in history_all.columns:
                my_history = history_all[history_all['역할'] == st.session_state.role]
                if not my_history.empty:
                    summary = my_history[['작업시간', '거래처명', '구분']].drop_duplicates().sort_values(by='작업시간', ascending=False)
                    for _, row in summary.head(5).iterrows():
                        with st.expander(f"🕒 {row['작업시간'][:16]} | {row['구분']}"):
                            st.caption(f"거래처: {row['거래처명']}")
                            if st.button("🗑️ 기록 삭제", key=f"del_{row['작업시간']}"):
                                new_hist = history_all[history_all['작업시간'] != row['작업시간']]
                                conn.update(worksheet="History", data=new_hist)
                                st.rerun()
                else: st.write("기록이 없습니다.")
        except: st.write("History 시트를 확인하세요.")
        st.divider()
        st.session_state.fee_presets = st.multiselect("수수료 프리셋 (%)", [0, 6, 13, 15, 20], default=st.session_state.fee_presets)
        new_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"], index=0 if st.session_state.calc_mode == "판매가 기준" else 1)
        if new_mode != st.session_state.calc_mode:
            st.session_state.calc_mode = new_mode
            st.session_state.data = run_calculation_engine(st.session_state.data, new_mode); st.rerun()

    # --- 메인 작업공간 대시보드 디자인 ---
    st.title(f"📊 {st.session_state.target_company} 비즈니스 대시보드")
    
    # 상단 요약 지표 (KPI Cards)
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("총 등록 품목", f"{len(st.session_state.data)}건")
    with kpi2:
        avg_margin = st.session_state.data['마진%'].mean()
        st.metric("평균 마진율", f"{avg_margin:.2f}%")
    with kpi3:
        total_profit = st.session_state.data['마진금액'].sum()
        st.metric("예상 총 마진", f"{int(total_profit):,}원")
    with kpi4:
        st.metric("계산 기준", st.session_state.calc_mode)

    st.divider()

    if st.session_state.role == "B":
        if st.button("📥 A업체 최신 단가 수신 (공급가 반영)", type="primary"):
            try:
                shared_data = conn.read(worksheet="Share_A_to_B", ttl=0)
                st.session_state.data['원가'] = pd.to_numeric(shared_data['판매가'], errors='coerce').fillna(0)
                st.session_state.data = run_calculation_engine(st.session_state.data, st.session_state.calc_mode)
                log_history("수신: 업체 A로부터 반영", st.session_state.target_company)
                st.success("A업체의 단가가 성공적으로 반영되었습니다.")
            except: st.error("데이터를 찾을 수 없습니다.")

    # 메인 데이터 에디터 (디자인 강화)
    st.data_editor(
        st.session_state.data, key="main_editor", on_change=on_data_change, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "순서": st.column_config.NumberColumn("No", format="%d", width="small"),
            "역산": st.column_config.CheckboxColumn("🔄역산"),
            "품목": st.column_config.TextColumn("📦 품목명", width="large"),
            "수수료%": st.column_config.SelectboxColumn("💳 수수료", options=st.session_state.fee_presets),
            "마진%": st.column_config.NumberColumn("📈 마진%", format="%.2f%%"),
            "판매가": st.column_config.NumberColumn("💰 판매가", format="₩%d"),
            "마진금액": st.column_config.NumberColumn("Profit", disabled=True, format="%d"),
            "수수료금액": st.column_config.NumberColumn("Fee", disabled=True, format="%d"),
            "목표마진대비금액": st.column_config.NumberColumn("Gap", disabled=True, format="%d"),
        }
    )

    # 하단 컨트롤 바
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("💾 현재 작업공간 저장", use_container_width=True, type="primary"):
            try:
                target_sheet = "A_Work" if st.session_state.role == "A" else "B_Work"
                conn.update(worksheet=target_sheet, data=st.session_state.data)
                log_history("자체 저장", st.session_state.target_company)
                st.success("안전하게 저장되었습니다!")
            except Exception as e: st.error(f"저장 실패: {str(e)}")
    with c2:
        if st.session_state.role == "A":
            if st.button("📤 업체 B에게 단가 전송", use_container_width=True):
                conn.update(worksheet="Share_A_to_B", data=st.session_state.data)
                log_history("송신: 업체 B향 단가 전송", st.session_state.target_company)
                st.warning("업체 B에게 단가가 전송되었습니다.")
    with c3:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            st.session_state.data.to_excel(writer, index=False)
        st.download_button("📥 엑셀 보고서 출력", data=output.getvalue(), file_name=f"Price_Report_{st.session_state.target_company}.xlsx", use_container_width=True)
    with c4:
        if st.button("🔄 최신 동기화", use_container_width=True):
            st.session_state.data = load_data("A_Work" if st.session_state.role == "A" else "B_Work"); st.rerun()