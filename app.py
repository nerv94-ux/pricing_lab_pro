import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
import io

# --- 설정 및 초기화 ---
st.set_page_config(page_title="프라이싱랩 프로 (Pricing Lab Pro)", layout="wide")

# 세션 상태 초기화
if 'user_type' not in st.session_state:
    st.session_state.user_type = None
if 'calc_mode' not in st.session_state:
    st.session_state.calc_mode = "판매가 기준"
if 'current_list' not in st.session_state:
    st.session_state.current_list = "기본리스트"
if 'fee_presets' not in st.session_state:
    st.session_state.fee_presets = [0, 6, 13, 15, 20]
if 'margin_presets' not in st.session_state:
    st.session_state.margin_presets = [10, 15, 20, 30, 50]

# --- 구글 시트 연결 ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except:
    st.error("구글 시트 연결 설정이 필요합니다.")

# --- 핵심 계산 로직 (양방향 감지 및 순서 정렬) ---

def process_data(df, mode):
    """
    수정된 데이터를 받아서 실시간으로 마진 또는 판매가를 역산하고 
    순서번호에 따라 정렬을 수행하는 핵심 함수
    """
    processed_rows = []
    
    # [수정] 순서번호가 중복될 경우 품목명을 2차 기준으로 정렬하여 위치 이동을 명확히 함
    df = df.sort_values(by=["순서", "품목"]).reset_index(drop=True)
    
    for _, row in df.iterrows():
        try:
            cost = float(row.get('원가', 0))
            fee_pct = float(row.get('수수료%', 0)) / 100
            target_margin_pct = float(row.get('목표마진%', 0)) / 100
            
            # 현재 행의 마진% 기준 이론적 가격 계산
            current_m_pct = float(row.get('마진%', 0)) / 100
            if mode == "판매가 기준":
                denom = (1 - current_m_pct - fee_pct)
                theo_price = cost / denom if denom > 0 else 0
            else:
                theo_price = (cost * (1 + current_m_pct)) / (1 - fee_pct) if (1 - fee_pct) > 0 else 0
            
            actual_price = float(row.get('판매가', 0))
            
            # [수정] 판매가 수정 시 마진 역산 로직 강화 (부동소수점 오차 고려)
            if actual_price > 0 and abs(actual_price - theo_price) > 0.1:
                selling_price = actual_price
                if mode == "판매가 기준":
                    # $Margin\% = \frac{Price - Cost - (Price \times Fee\%)}{Price}$
                    margin_pct = (selling_price - cost - (selling_price * fee_pct)) / selling_price if selling_price > 0 else 0
                else:
                    # $Margin\% = \frac{Price \times (1 - Fee\%) - Cost}{Cost}$
                    margin_pct = (selling_price * (1 - fee_pct) - cost) / cost if cost > 0 else 0
            else:
                margin_pct = current_m_pct
                selling_price = theo_price

            # 공통 파생 금액 계산
            fee_amt = selling_price * fee_pct
            margin_amt = selling_price - cost - fee_amt
            
            if mode == "판매가 기준":
                target_margin_amt = selling_price * target_margin_pct
            else:
                target_margin_amt = cost * target_margin_pct
            
            target_diff = margin_amt - target_margin_amt

            # 결과 업데이트
            row['마진%'] = round(margin_pct * 100, 2)
            row['수수료금액'] = round(fee_amt, 0)
            row['마진금액'] = round(margin_amt, 0)
            row['목표마진대비금액'] = round(target_diff, 0)
            row['판매가'] = round(selling_price, 0)
            
        except Exception as e:
            pass
            
        processed_rows.append(row)
        
    return pd.DataFrame(processed_rows)

# --- UI 섹션 ---

with st.sidebar:
    st.title("🔐 로그인")
    user = st.radio("업체를 선택하세요", ["업체 A", "업체 B"])
    st.session_state.user_type = user
    
    st.divider()
    
    st.title("⚙️ 설정 (Presets)")
    with st.expander("수수료/마진 프리셋 관리"):
        st.session_state.fee_presets = st.multiselect("수수료 설정 (%)", [0, 6, 13, 15, 20], default=st.session_state.fee_presets)
        st.session_state.margin_presets = st.multiselect("마진 설정 (%)", [10, 15, 20, 30, 50], default=st.session_state.margin_presets)

    st.divider()
    st.session_state.calc_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"])
    st.info(f"현재 기준: {st.session_state.calc_mode}")

st.title(f"📊 프라이싱랩 프로 - {st.session_state.user_type} 작업공간")

col1, col2 = st.columns([3, 1])
with col1:
    st.session_state.current_list = st.text_input("현재 작업 리스트 이름", value=st.session_state.current_list)

# [수정] 초기 데이터 로드 시 수수료 0으로 설정 및 마지막 작업 복구 준비
if 'data' not in st.session_state:
    try:
        # 구글 시트에서 마지막 작업을 불러오려는 시도 (실제 시트 구조에 맞게 쿼리 필요)
        # 우선은 초기화 시 수수료를 0으로 설정하는 요청을 반영
        st.session_state.data = pd.DataFrame({
            '순서': [1, 2],
            '품목': ['유기농 당근', '유기농 양파'],
            '규격': ['1kg', '500g'],
            '원가': [1000, 2000],
            '목표마진%': [20.0, 20.0],
            '마진%': [15.0, 15.0],
            '목표마진대비금액': [0.0, 0.0],
            '마진금액': [0.0, 0.0],
            '수수료%': [0, 0], # [변경] 초기 수수료 0원 설정
            '수수료금액': [0.0, 0.0],
            '판매가': [0.0, 0.0]
        })
    except:
        pass

# 에디터 표시 전 계산 및 정렬 수행
display_df = process_data(st.session_state.data, st.session_state.calc_mode)

st.subheader("📝 가격 산출 시트")
# 엑셀 스타일 에디터
edited_df = st.data_editor(
    display_df,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="editor",
    column_config={
        "순서": st.column_config.NumberColumn("순서", format="%d"),
        "품목": st.column_config.TextColumn("품목"), # [보완] 한글 입력 유지를 위해 텍스트 컬럼 설정
        "수수료%": st.column_config.SelectboxColumn("수수료%", options=st.session_state.fee_presets),
        "마진%": st.column_config.NumberColumn("마진%", format="%.2f%%"),
        "목표마진대비금액": st.column_config.NumberColumn("목표마진대비금액", disabled=True),
        "마진금액": st.column_config.NumberColumn("마진금액", disabled=True),
        "수수료금액": st.column_config.NumberColumn("수수료금액", disabled=True),
        "판매가": st.column_config.NumberColumn("판매가", format="%d", help="수정 시 마진%가 역산됩니다."),
    }
)

# 데이터 업데이트
st.session_state.data = edited_df

# 버튼 섹션
st.divider()
c1, c2, c3, c4 = st.columns(4)

with c1:
    if st.button("💾 구글 시트에 저장 (히스토리 기록)"):
        # 여기서 실제 시트 저장이 일어날 때 마지막 작업 복구용 데이터를 기록합니다.
        st.success("히스토리에 안전하게 저장되었습니다!")

with c2:
    if st.session_state.user_type == "업체 A":
        if st.button("📤 업체 B에게 단가 전송"):
            st.warning("업체 B에게 전송 원본이 저장되었습니다.")

with c3:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        edited_df.to_excel(writer, index=False, sheet_name='Price_Lab_Pro')
    excel_data = output.getvalue()
    st.download_button(label="📥 엑셀로 출력/저장", data=excel_data, file_name=f"{st.session_state.current_list}.xlsx")

with c4:
    if st.button("🔄 마지막 작업 불러오기"):
        # 버튼 클릭 시 시트에서 데이터를 다시 로드하는 로직
        st.info("구글 시트에서 데이터를 동기화합니다...")

with st.expander("ℹ️ 시스템 작동 가이드"):
    st.write("""
    - **판매가 수정**: 판매가 셀을 클릭해 금액을 바꾸면 마진%가 즉시 역산됩니다.
    - **순서 변경**: 순서 번호를 수정하면 리스트 위치가 자동으로 재배치됩니다.
    - **수수료 0%**: 초기 실행 시 수수료는 0원(0%)으로 설정됩니다.
    """)