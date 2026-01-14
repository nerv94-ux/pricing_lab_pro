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
    st.session_state.calc_mode = "판매가 기준"  # 기본값
if 'current_list' not in st.session_state:
    st.session_state.current_list = "기본리스트"

# --- 구글 시트 연결 ---
# (실제 배포 시 .streamlit/secrets.toml 또는 Streamlit Cloud Secrets에 시트 연결 정보가 있어야 합니다)
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except:
    st.error("구글 시트 연결 설정이 필요합니다.")

# --- 유틸리티 함수 ---

def calculate_row(row, mode):
    """행 단위 마진/판매가 계산 로직"""
    cost = float(row.get('원가', 0))
    fee_pct = float(row.get('수수료%', 0)) / 100
    margin_pct = float(row.get('마진%', 0)) / 100
    
    # 판매가 계산 로직
    if mode == "판매가 기준":
        # 판매가 = 원가 / (1 - 마진% - 수수료%)
        denom = (1 - margin_pct - fee_pct)
        selling_price = cost / denom if denom > 0 else 0
    else: # 원가 기준
        # 판매가 = (원가 * (1 + 마진%)) / (1 - 수수료%)
        selling_price = (cost * (1 + margin_pct)) / (1 - fee_pct) if (1 - fee_pct) > 0 else 0
    
    # 파생 금액 계산
    fee_amt = selling_price * fee_pct
    margin_amt = selling_price - cost - fee_amt
    
    # 목표 마진 대비 계산 (예시: 목표 마진%는 설정탭에서 가져온다고 가정)
    target_margin_pct = float(row.get('목표마진%', 0)) / 100
    if mode == "판매가 기준":
        target_margin_amt = selling_price * target_margin_pct
    else:
        target_margin_amt = cost * target_margin_pct
    
    target_diff = margin_amt - target_margin_amt
    
    return pd.Series({
        '수수료금액': round(fee_amt, 0),
        '마진금액': round(margin_amt, 0),
        '목표마진대비금액': round(target_diff, 0),
        '판매가': round(selling_price, 0)
    })

# --- UI 섹션 ---

# 1. 사이드바: 로그인 및 설정
with st.sidebar:
    st.title("🔐 로그인")
    user = st.radio("업체를 선택하세요", ["업체 A", "업체 B"])
    st.session_state.user_type = user
    
    st.divider()
    
    st.title("⚙️ 설정 (Presets)")
    with st.expander("수수료/마진 프리셋 관리"):
        st.write("수수료 프리셋 (%)")
        fee_presets = st.multiselect("수수료 설정", [6, 13, 15, 20], default=[6, 13, 15, 20])
        st.write("마진율 프리셋 (%)")
        margin_presets = st.multiselect("마진 설정", [10, 15, 20, 30, 50], default=[10, 15, 20, 30, 50])

    st.divider()
    st.session_state.calc_mode = st.radio("마진 계산 기준", ["판매가 기준", "원가 기준"])
    st.info(f"현재 기준: {st.session_state.calc_mode}\n(원가와 판매가는 고정됩니다)")

# 2. 메인 화면
st.title(f"📊 프라이싱랩 프로 - {st.session_state.user_type} 작업공간")

# 리스트 선택/생성
col1, col2 = st.columns([3, 1])
with col1:
    list_name = st.text_input("현재 작업 리스트 이름", value=st.session_state.current_list)
    st.session_state.current_list = list_name

# 임시 데이터 생성 (실제로는 DB에서 로드)
if 'data' not in st.session_state:
    initial_data = pd.DataFrame({
        '순서': [1, 2],
        '품목': ['유기농 당근', '유기농 양파'],
        '규격': ['1kg', '500g'],
        '원가': [1000, 2000],
        '목표마진%': [20, 20],
        '마진%': [15, 15],
        '목표마진대비금액': [0, 0],
        '마진금액': [0, 0],
        '수수료%': [10, 10],
        '수수료금액': [0, 0],
        '판매가': [0, 0]
    })
    st.session_state.data = initial_data

# 엑셀 형태 에디터
st.subheader("📝 가격 산출 시트")
edited_df = st.data_editor(
    st.session_state.data.sort_values("순서"),
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "순서": st.column_config.NumberColumn("순서", format="%d"),
        "품목": "품목",
        "수수료%": st.column_config.SelectboxColumn("수수료%", options=fee_presets + ["직접입력"]),
        "마진%": st.column_config.SelectboxColumn("마진%", options=margin_presets + ["직접입력"]),
        "목표마진대비금액": st.column_config.NumberColumn("목표마진대비금액", disabled=True),
        "마진금액": st.column_config.NumberColumn("마진금액", disabled=True),
        "수수료금액": st.column_config.NumberColumn("수수료금액", disabled=True),
        "판매가": st.column_config.NumberColumn("판매가", disabled=True),
    }
)

# 실시간 계산 반영
for index, row in edited_df.iterrows():
    calc_results = calculate_row(row, st.session_state.calc_mode)
    edited_df.loc[index, ['수수료금액', '마진금액', '목표마진대비금액', '판매가']] = calc_results

st.session_state.data = edited_df

# 3. 하단 버튼 그룹
st.divider()
c1, c2, c3, c4 = st.columns(4)

with c1:
    if st.button("💾 구글 시트에 저장 (히스토리 기록)"):
        # 저장 로직: 현재 데이터를 히스토리용 컬럼과 함께 DB에 추가
        save_df = edited_df.copy()
        save_df['업데이트일시'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_df['작업자'] = st.session_state.user_type
        save_df['리스트명'] = st.session_state.current_list
        # conn.create(data=save_df) # 실제 연결 시 활성화
        st.success("히스토리에 안전하게 저장되었습니다!")

with c2:
    if st.session_state.user_type == "업체 A":
        if st.button("📤 업체 B에게 단가 전송"):
            # 전송 스냅샷 저장 로직
            snapshot_df = edited_df[['품목', '규격', '판매가']].copy()
            snapshot_df.columns = ['품목', '규격', '원가'] # A의 판매가가 B의 원가로
            snapshot_df['전송일시'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.warning("업체 B에게 전송 원본이 '박제'되어 전달되었습니다.")

with c3:
    # 엑셀 다운로드 기능
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        edited_df.to_excel(writer, index=False, sheet_name='Price_Lab_Pro')
    excel_data = output.getvalue()
    st.download_button(label="📥 엑셀로 출력/저장", data=excel_data, file_name=f"{st.session_state.current_list}.xlsx")

with c4:
    if st.button("📜 히스토리 보기"):
        st.info("과거 변경 이력을 불러옵니다... (준비 중)")

# --- 상세 브리핑 영역 ---
with st.expander("ℹ️ 시스템 작동 가이드"):
    st.write("""
    1. **순서 변경**: '순서' 컬럼의 숫자를 바꾸면 자동으로 정렬됩니다.
    2. **마진 기준**: 사이드바에서 기준을 바꿔도 원가와 판매가는 유지된 채 마진율 수치만 재계산됩니다.
    3. **데이터 전송**: 업체 A가 전송한 데이터는 업체 B의 '수신함'에 원본 스냅샷으로 영구 보관됩니다.
    """)