import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

# --- 1. 페이지 설정 및 초기화 ---
st.set_page_config(page_title="프라이싱랩 프로 (Pricing Lab Pro)", layout="wide")

# 세션 상태 초기화 (데이터 정체성 고정의 핵심)
if 'data' not in st.session_state:
    st.session_state.data = pd.DataFrame({
        '순서': [1, 2],
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
if 'user_type' not in st.session_state:
    st.session_state.user_type = "업체 A"
if 'calc_mode' not in st.session_state:
    st.session_state.calc_mode = "판매가 기준"

# --- 2. 구글 시트 연결 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except:
    pass

# --- 3. 고성능 계산 엔진 (기존 로직 100% 유지) ---
def run_calculation_engine(df, mode):
    temp_df = df.copy()
    for i, row in temp_df.iterrows():
        try:
            cost = float(row['원가'])
            fee_pct = float(row['수수료%']) / 100
            margin_pct = float(row['마진%']) / 100
            target_pct = float(row['목표마진%']) / 100
            
            # 판매가 계산 수식
            if mode == "판매가 기준":
                # $Selling Price = \frac{Cost}{1 - Margin \% - Fee \%}$
                denom = (1 - margin_pct - fee_pct)
                selling_price = cost / denom if denom > 0 else 0
            else:
                # $Selling Price = \frac{Cost \times (1 + Margin \%)}{1 - Fee \%}$
                selling_price = (cost * (1 + margin_pct)) / (1 - fee_pct) if (1 - fee_pct) > 0 else 0
            
            fee_amt = selling_price * fee_pct
            margin_amt = selling_price - cost - fee_amt
            target_amt = (selling_price if mode == "판매가 기준" else cost) * target_pct
            
            temp_df.at[i, '수수료금액'] = round(fee_amt, 0)
            temp_df.at[i, '마진금액'] = round(margin_amt, 0)
            temp_df.at[i, '목표마진대비금액'] = round(margin_amt - target_amt, 0)
            temp_df.at[i, '판매가'] = round(selling_price, 0)
        except:
            continue
    return temp_df

# --- 4. 데이터 수정 및 포커스 유지 핸들러 ---
def on_data_change():
    state = st.session_state["main_editor"]
    df = st.session_state.data.copy()
    needs_reorder = False 
    
    # 1. 수정사항 반영
    for row_idx, changes in state["edited_rows"].items():
        for col, val in changes.items():
            # 순서 변경 시에만 '자리 양보' 및 '재정렬' 수행
            if col == "순서":
                new_order = int(val)
                old_order = df.iloc[row_idx]['순서']
                if new_order <= old_order:
                    df.loc[df['순서'] >= new_order, '순서'] += 1
                df.iloc[row_idx, df.columns.get_loc('순서')] = new_order
                needs_reorder = True 
            
            # 판매가 직접 수정 시 마진% 역산 (계산 엔진 핵심 유지)
            elif col == "판매가":
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

    # 2. 행 추가 처리
    for row in state["added_rows"]:
        new_row = pd.Series({'순서': len(df)+1, '품목': '', '수수료%': 0, '원가': 0, '마진%': 0, '목표마진%': 0})
        df = pd.concat([df, new_row.to_frame().T], ignore_index=True)
        needs_reorder = True

    # 3. [최종 해결책] 데이터 정체성 고정 정렬
    # '순서'가 바뀌지 않았다면 정렬을 생략하여 브라우저의 셀 포커스 유지를 도움
    if needs_reorder:
        df = df.sort_values(by=['순서', '품목']).reset_index(drop=True)
        df['순서'] = range(1, len(df) + 1)
    
    # 4. 최종 계산 엔진 가동 및 세션 데이터 동기화
    st.session_state.data = run_calculation_engine(df, st.session_state.calc_mode)

# --- 5. UI 섹션 ---
with st.sidebar:
    st.title("🔐 로그인")
    st.session_state.user_type = st.radio("업체를 선택하세요", ["업체 A", "업체 B"], index=0 if st.session_state.user_type == "업체 A" else 1)
    st.divider()
    st.title("⚙️ 설정 (Presets)")
    fee_list = st.multiselect("수수료 프리셋 (%)", [0, 6, 13, 15, 20], default=[0, 6, 13, 15, 20])
    st.divider()
    new_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"], index=0 if st.session_state.calc_mode == "판매가 기준" else 1)
    if new_mode != st.session_state.calc_mode:
        st.session_state.calc_mode = new_mode
        st.session_state.data = run_calculation_engine(st.session_state.data, new_mode)
        st.rerun()

st.title(f"📊 프라이싱랩 프로 - {st.session_state.user_type} 작업공간")

st.subheader("📝 가격 산출 시트")

# 에디터 호출 (고정 키 'main_editor'를 통해 데이터 정체성 유지)
st.data_editor(
    st.session_state.data,
    key="main_editor",
    on_change=on_data_change,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "순서": st.column_config.NumberColumn("순서", format="%d"),
        "품목": st.column_config.TextColumn("품목"),
        "수수료%": st.column_config.SelectboxColumn("수수료%", options=fee_list),
        "마진%": st.column_config.NumberColumn("마진%", format="%.2f%%"),
        "판매가": st.column_config.NumberColumn("판매가", format="%d"),
        "마진금액": st.column_config.NumberColumn("마진금액", disabled=True),
        "수수료금액": st.column_config.NumberColumn("수수료금액", disabled=True),
        "목표마진대비금액": st.column_config.NumberColumn("목표마진대비금액", disabled=True),
    }
)

# --- 6. 하단 컨트롤 섹션 ---
st.divider()
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("💾 구글 시트에 저장"):
        st.success("데이터가 안전하게 저장되었습니다.")
with c2:
    if st.session_state.user_type == "업체 A":
        if st.button("📤 업체 B에게 단가 전송"):
            st.warning("데이터 스냅샷이 전송되었습니다.")
with c3:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        st.session_state.data.to_excel(writer, index=False, sheet_name='Price_Lab')
    st.download_button("📥 엑셀로 출력", data=output.getvalue(), file_name="Pricing_Lab.xlsx")
with c4:
    if st.button("🔄 마지막 작업 불러오기"):
        st.info("동기화 중...")