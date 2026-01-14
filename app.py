import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

# --- 1. 페이지 설정 및 초기화 ---
st.set_page_config(page_title="프라이싱랩 프로 (Pricing Lab Pro)", layout="wide")

# 구글 시트 연결 설정 (secrets.toml 설정 필요)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("구글 시트 연결에 실패했습니다. 설정을 확인해주세요.")

# 세션 상태 초기화
if 'user_type' not in st.session_state:
    st.session_state.user_type = "업체 A"
if 'calc_mode' not in st.session_state:
    st.session_state.calc_mode = "판매가 기준"
if 'fee_presets' not in st.session_state:
    st.session_state.fee_presets = [0, 6, 13, 15, 20]

# [변경] 초기 데이터 로드: 구글 시트에서 먼저 읽어오고 실패시 기본값 사용
if 'data' not in st.session_state:
    try:
        # 'CurrentWork' 시트에서 데이터를 읽어옴 (없을 경우 에러 처리)
        existing_data = conn.read(worksheet="CurrentWork", ttl=0)
        if existing_data is not None and not existing_data.empty:
            st.session_state.data = existing_data
        else:
            raise Exception("No data")
    except:
        st.session_state.data = pd.DataFrame({
            '순서': [1, 2],
            '역산': [False, False],
            '품목': ['유기농 당근', '유기농 양파'],
            '규격': ['1kg', '500g'],
            '원가': [1000, 2000],
            '목표마진%': [20.0, 20.0],
            '마진%': [15.0, 15.0],
            '목표마진대비금액': [0.0, 0.0],
            '마진금액': [0.0, 0.0],
            '수수료%': [0, 0],
            '수수료금액': [0.0, 0.0],
            '판매가': [0.0, 0.0]
        })

# --- 2. 고성능 계산 엔진 함수 (기존 기능 100% 유지) ---
def run_calculation_engine(df, mode):
    temp_df = df.copy()
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
        except:
            continue
    return temp_df

# --- 3. 데이터 수정 및 핸들러 (기존 기능 100% 유지) ---
def on_data_change():
    state = st.session_state["main_editor"]
    df = st.session_state.data.copy()
    
    for row_idx, changes in state["edited_rows"].items():
        for col, val in changes.items():
            if col == "역산":
                current_name = str(df.iloc[row_idx]['품목'])
                if val == True:
                    if not current_name.startswith("[역산]"):
                        df.iloc[row_idx, df.columns.get_loc('품목')] = f"[역산] {current_name}"
                else:
                    df.iloc[row_idx, df.columns.get_loc('품목')] = current_name.replace("[역산] ", "")
                df.iloc[row_idx, df.columns.get_loc('역산')] = val
            elif col == "순서":
                new_order = int(val)
                old_order = df.iloc[row_idx]['순서']
                if new_order <= old_order:
                    df.loc[df['순서'] >= new_order, '순서'] += 1
                df.iloc[row_idx, df.columns.get_loc('순서')] = new_order
            elif col == "판매가":
                if df.iloc[row_idx]['역산']:
                    df.iloc[row_idx, df.columns.get_loc('판매가')] = val
                else:
                    cost = float(df.iloc[row_idx]['원가'])
                    fee_p = float(df.iloc[row_idx]['수수료%']) / 100
                    new_price = float(val)
                    if st.session_state.calc_mode == "판매가 기준":
                        new_m = (new_price - cost - (new_price * fee_p)) / new_price if new_price > 0 else 0
                    else:
                        new_m = (new_price * (1 - fee_p) - cost) / cost if cost > 0 else 0
                    df.iloc[row_idx, df.columns.get_loc('마진%')] = round(new_m * 100, 2)
                    df.iloc[row_idx, df.columns.get_loc('판매가')] = new_price
            else:
                df.iloc[row_idx, df.columns.get_loc(col)] = val

    for row in state["added_rows"]:
        new_row = pd.Series({'순서': len(df)+1, '역산': False, '품목': '', '수수료%': 0, '원가': 0, '마진%': 0, '목표마진%': 0})
        df = pd.concat([df, new_row.to_frame().T], ignore_index=True)

    df = df.sort_values(by=['순서', '품목']).reset_index(drop=True)
    df['순서'] = range(1, len(df) + 1)
    st.session_state.data = run_calculation_engine(df, st.session_state.calc_mode)

# --- 4. UI 및 레이아웃 ---
with st.sidebar:
    st.title("🔐 로그인")
    st.session_state.user_type = st.radio("업체를 선택하세요", ["업체 A", "업체 B"], index=0 if st.session_state.user_type == "업체 A" else 1)
    st.divider()
    st.title("⚙️ 설정 (Presets)")
    st.session_state.fee_presets = st.multiselect("수수료 프리셋 (%)", [0, 6, 13, 15, 20], default=st.session_state.fee_presets)
    st.divider()
    new_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"], index=0 if st.session_state.calc_mode == "판매가 기준" else 1)
    if new_mode != st.session_state.calc_mode:
        st.session_state.calc_mode = new_mode
        st.session_state.data = run_calculation_engine(st.session_state.data, new_mode)
        st.rerun()

st.title(f"📊 프라이싱랩 프로 - {st.session_state.user_type} 작업공간")
st.subheader("📝 가격 산출 시트")

st.data_editor(
    st.session_state.data,
    key="main_editor",
    on_change=on_data_change,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "순서": st.column_config.NumberColumn("순서", format="%d"),
        "역산": st.column_config.CheckboxColumn("역산"),
        "품목": st.column_config.TextColumn("품목"),
        "수수료%": st.column_config.SelectboxColumn("수수료%", options=st.session_state.fee_presets),
        "마진%": st.column_config.NumberColumn("마진%", format="%.2f%%"),
        "판매가": st.column_config.NumberColumn("판매가", format="%d"),
        "마진금액": st.column_config.NumberColumn("마진금액", disabled=True),
        "수수료금액": st.column_config.NumberColumn("수수료금액", disabled=True),
        "목표마진대비금액": st.column_config.NumberColumn("목표마진대비금액", disabled=True),
    }
)

# --- 5. 컨트롤 섹션 (구글 시트 연동 로직 이식) ---
st.divider()
c1, c2, c3, c4 = st.columns(4)

with c1:
    if st.button("💾 구글 시트에 저장"):
        try:
            # 현재 시트 업데이트
            conn.update(worksheet="CurrentWork", data=st.session_state.data)
            
            # 히스토리 기록 (로그용)
            history_df = st.session_state.data.copy()
            history_df['작업시간'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            history_df['업체'] = st.session_state.user_type
            
            # 히스토리 시트에 추가 (별도 시트 존재 시)
            # conn.update(worksheet="History", data=history_df) 
            
            st.success("구글 클라우드에 실시간 동기화되었습니다!")
        except Exception as e:
            st.error(f"저장 실패: {str(e)}")

with c2:
    if st.session_state.user_type == "업체 A":
        if st.button("📤 업체 B에게 단가 전송"):
            try:
                # 업체 B가 사용하는 시트 영역이나 별도 시트에 업데이트
                conn.update(worksheet="For_Vendor_B", data=st.session_state.data)
                st.warning("업체 B의 작업 공간으로 데이터가 전송되었습니다.")
            except:
                st.error("전송 실패")

with c3:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        st.session_state.data.to_excel(writer, index=False, sheet_name='Price_Lab')
    st.download_button("📥 엑셀로 출력", data=output.getvalue(), file_name=f"Pricing_{datetime.now().strftime('%m%d')}.xlsx")

with c4:
    if st.button("🔄 마지막 작업 불러오기"):
        try:
            # 강제로 다시 읽어오기
            st.session_state.data = conn.read(worksheet="CurrentWork", ttl=0)
            st.rerun()
        except:
            st.info("불러올 수 있는 히스토리가 없습니다.")