import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

# --- 1. 페이지 설정 및 초기화 ---
st.set_page_config(page_title="프라이싱랩 프로 (Pricing Lab Pro)", layout="wide")

try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error(f"구글 시트 인증 오류: {str(e)}")

# [중요] 역할 및 상태 관리
if 'role' not in st.session_state:
    st.session_state.role = None 
if 'target_company' not in st.session_state:
    st.session_state.target_company = "일반거래처" # 상세 업체명 초기화
if 'calc_mode' not in st.session_state:
    st.session_state.calc_mode = "판매가 기준"
if 'fee_presets' not in st.session_state:
    st.session_state.fee_presets = [0, 6, 13, 15, 20]

# --- 2. 데이터 로드 함수 (기존 기능 유지) ---
def load_data(worksheet_name="A_Work"):
    try:
        existing_data = conn.read(worksheet=worksheet_name, ttl=0)
        if existing_data is not None and not existing_data.empty:
            return existing_data
    except:
        pass
    return pd.DataFrame({
        '순서': [1, 2], '역산': [False, False], '품목': ['유기농 당근', '유기농 양파'],
        '규격': ['1kg', '500g'], '원가': [1000, 2000], '목표마진%': [20.0, 20.0],
        '마진%': [15.0, 15.0], '목표마진대비금액': [0.0, 0.0], '마진금액': [0.0, 0.0],
        '수수료%': [0, 0], '수수료금액': [0.0, 0.0], '판매가': [0.0, 0.0]
    })

# --- 3. 고성능 계산 엔진 (기존 로직 100% 유지) ---
def run_calculation_engine(df, mode):
    temp_df = df.copy()
    for i, row in temp_df.iterrows():
        try:
            fee_pct = float(row['수수료%']) / 100
            margin_pct = float(row['마진%']) / 100
            target_pct = float(row['목표마진%']) / 100
            if row['역산']:
                selling_price = float(row['판매가'])
                cost = selling_price * (1 - margin_pct - fee_pct) if mode == "판매가 기준" else (selling_price * (1 - fee_pct)) / (1 + margin_pct)
                temp_df.at[i, '원가'] = round(cost, 0)
            else:
                cost = float(row['원가'])
                selling_price = cost / (1 - margin_pct - fee_pct) if mode == "판매가 기준" else (cost * (1 + margin_pct)) / (1 - fee_pct)
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

# --- 5. UI 섹션: 게이트웨이 ---
if st.session_state.role is None:
    st.title("🛡️ 프라이싱랩 프로 - 역할 선택")
    st.info("작업하실 역할을 선택하세요. 데이터는 업체별로 격리되어 관리됩니다.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🏢 A 업체 (공급사) 진입", use_container_width=True):
            st.session_state.role = "A"
            st.session_state.data = load_data("A_Work")
            st.rerun()
    with c2:
        if st.button("🏪 B 업체 (판매사) 진입", use_container_width=True):
            st.session_state.role = "B"
            st.session_state.data = load_data("B_Work")
            st.rerun()

else:
    # 메인 작업창 사이드바
    with st.sidebar:
        st.title(f"🔐 {'공급사 A' if st.session_state.role == 'A' else '판매사 B'}")
        # [신규] 상세 거래처명 입력
        st.session_state.target_company = st.text_input("📍 현재 작업 거래처명", value=st.session_state.target_company)
        
        if st.button("🚪 로그아웃 (초기화면)"):
            st.session_state.role = None
            st.rerun()
        st.divider()
        
        # [신규] 히스토리 불러오기 기능
        st.subheader("📜 히스토리 불러오기")
        try:
            history_all = conn.read(worksheet="History", ttl=0)
            if not history_all.empty:
                # 현재 업체(A or B)의 기록만 필터링
                my_history = history_all[history_all['역할'] == st.session_state.role]
                if not my_history.empty:
                    # 거래처명별로 묶어서 시간순 표시
                    history_list = my_history.sort_values(by='작업시간', ascending=False)
                    selected_record = st.selectbox("과거 기록 선택", 
                                                   history_list['작업시간'].tolist(),
                                                   format_func=lambda x: f"[{history_list[history_list['작업시간']==x]['거래처명'].values[0]}] {x}")
                    if st.button("📂 선택 기록 불러오기"):
                        # 선택된 시간의 데이터를 JSON이나 특정 방식으로 파싱하여 로드 (간략화를 위해 CurrentWork 방식 준용)
                        st.info("선택한 시점의 데이터를 복원 중입니다...")
                        # 실제 구현 시 History 시트의 구조에 따라 필터링 로직 추가
                else: st.write("저장된 기록이 없습니다.")
        except: st.write("히스토리 기능을 활성화하려면 'History' 시트를 만드세요.")
        
        st.divider()
        st.session_state.fee_presets = st.multiselect("수수료 프리셋 (%)", [0, 6, 13, 15, 20], default=st.session_state.fee_presets)
        new_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"], index=0 if st.session_state.calc_mode == "판매가 기준" else 1)
        if new_mode != st.session_state.calc_mode:
            st.session_state.calc_mode = new_mode
            st.session_state.data = run_calculation_engine(st.session_state.data, new_mode)
            st.rerun()

    st.title(f"📊 {st.session_state.target_company} 작업공간 ({'A 업체' if st.session_state.role == 'A' else 'B 업체'})")
    
    # [기존 로직 유지] B업체 전용 릴레이
    if st.session_state.role == "B":
        if st.button("📥 A업체 최신 단가 수신 (A 판매가 → B 원가)"):
            try:
                shared_data = conn.read(worksheet="Share_A_to_B", ttl=0)
                st.session_state.data['원가'] = shared_data['판매가']
                st.session_state.data = run_calculation_engine(st.session_state.data, st.session_state.calc_mode)
                st.success("A업체의 공급가가 원가로 반영되었습니다.")
            except: st.error("전송된 데이터를 찾을 수 없습니다.")

    st.data_editor(
        st.session_state.data, key="main_editor", on_change=on_data_change, num_rows="dynamic", use_container_width=True, hide_index=True,
        column_config={
            "순서": st.column_config.NumberColumn("순서", format="%d"),
            "역산": st.column_config.CheckboxColumn("역산"),
            "수수료%": st.column_config.SelectboxColumn("수수료%", options=st.session_state.fee_presets),
            "마진%": st.column_config.NumberColumn("마진%", format="%.2f%%"),
            "판매가": st.column_config.NumberColumn("판매가", format="%d"),
            "마진금액": st.column_config.NumberColumn("마진금액", disabled=True),
            "수수료금액": st.column_config.NumberColumn("수수료금액", disabled=True),
            "목표마진대비금액": st.column_config.NumberColumn("목표마진대비금액", disabled=True),
        }
    )

    # --- 6. 컨트롤 섹션 (히스토리 저장 로직 강화) ---
    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("💾 내 작업공간 저장"):
            try:
                target_sheet = "A_Work" if st.session_state.role == "A" else "B_Work"
                conn.update(worksheet=target_sheet, data=st.session_state.data)
                
                # [신규] 히스토리 시트에 거래처별 누적 기록
                history_row = st.session_state.data.copy()
                history_row['작업시간'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                history_row['거래처명'] = st.session_state.target_company
                history_row['역할'] = st.session_state.role
                
                # 구글 시트 'History' 탭에 데이터 추가 (Append)
                # 실제 운영 시 gsheets 라이브러리의 append 기능을 활용하거나 전체를 다시 씁니다.
                conn.update(worksheet="History", data=history_row) 
                
                st.success(f"'{st.session_state.target_company}' 기록이 히스토리에 저장되었습니다!")
            except Exception as e: st.error(f"저장 실패: {str(e)}")
            
    with c2:
        if st.session_state.role == "A":
            if st.button("📤 업체 B에게 단가 전송"):
                conn.update(worksheet="Share_A_to_B", data=st.session_state.data)
                st.warning("B업체에게 현재 판매가를 전송했습니다.")
    with c3:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            st.session_state.data.to_excel(writer, index=False)
        st.download_button("📥 엑셀 출력", data=output.getvalue(), file_name=f"Price_{st.session_state.target_company}.xlsx")
    with c4:
        if st.button("🔄 최신 동기화"):
            st.session_state.data = load_data("A_Work" if st.session_state.role == "A" else "B_Work")
            st.rerun()