import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- 1. ДАННЫЕ ---
@st.cache_data
def get_clean_data():
    np.random.seed(42)
    periods = 48 * 7 
    time_idx = pd.date_range(start='2024-05-01', periods=periods, freq='30min')
    base_load = 500 + 300 * np.sin(np.arange(periods) * 2 * np.pi / 48 - np.pi/2)
    noise = np.random.normal(0, 25, periods)
    return pd.DataFrame({'timestamp': time_idx, 'load': base_load + noise})

# --- 2. УПРАВЛЕНИЕ ---
def move_interval(key, step):
    low, high = st.session_state[key]
    if 0 <= low + step and high + step <= 24:
        st.session_state[key] = (low + step, high + step)

def update_p_val():
    val = st.session_state.p_input_key
    if val > st.session_state.max_p_limit:
        st.session_state.p_val = st.session_state.max_p_limit
    else:
        st.session_state.p_val = val

# Инициализация состояний
if 'hc' not in st.session_state: st.session_state.hc = (7, 10)
if 'ha' not in st.session_state: st.session_state.ha = (0, 7)
if 'p_val' not in st.session_state: st.session_state.p_val = 200
if 'is_modeling' not in st.session_state: st.session_state.is_modeling = False
if 'max_p_limit' not in st.session_state: st.session_state.max_p_limit = 1000

def run_energy_app():
    st.set_page_config(page_title="Energy Optimizer", layout="wide", initial_sidebar_state="expanded")
    
    st.markdown("""
        <style>
        /* Полная очистка системных элементов */
        #MainMenu {visibility: hidden;} /* Меню три точки */
        header {visibility: hidden;}    /* Верхняя панель и GitHub */
        footer {visibility: hidden;}    /* Футер Streamlit */
        
        /* Скрытие профиля и системных панелей внизу */
        [data-testid="stStatusWidget"] {display: none;} 
        [data-testid="stDecoration"] {display: none;}
        .viewerBadge_container__1QSob {display: none;} /* Кнопка профиля и хостинга */
        
        /* Основная верстка */
        .main .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; margin-top: -20px; }
        h1 { padding-top: 0px !important; margin-top: -10px !important; margin-bottom: 10px !important; }
        .stMetric {background-color: #1e2129; padding: 15px; border-radius: 10px; border: 1px solid #31333f;}
        [data-testid="stSidebar"] {background-color: #0e1117;}
        
        div.stButton > button:first-child[kind="primary"] {
            background-color: #28a745 !important;
            border-color: #28a745 !important;
            color: white !important;
            font-weight: bold !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    with st.sidebar:
        st.header("⚙️ Настройки системы")
        info_text = """
        Файл должен содержать колонки:
        * **timestamp**: дата и время (ГГГГ-ММ-ДД ЧЧ:ММ)
        * **load**: значение нагрузки в кВт
        
        Пример:

        | timestamp | load |
        | :--- | :--- |
        | 2024-05-01 00:00 | 450.5 |
        | 2024-05-01 00:30 | 432.1 |
        """

        uploaded_file = st.file_uploader("Загрузить профиль нагрузки", type=["xlsx", "csv"], help=info_text)
        
        if uploaded_file:
            try:
                df_input = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                df_input['timestamp'] = pd.to_datetime(df_input['timestamp'])
                df_raw = df_input[['timestamp', 'load']].copy()
                st.success("Данные импортированы")
            except Exception as e:
                st.error(f"Ошибка: {e}")
                df_raw = get_clean_data()
        else:
            df_raw = get_clean_data()
            
        st.divider()
        limit_val = st.number_input("Лимит мощности (кВт)", 300, 1500, 850, step=50)
        tech_min = st.number_input("Технологический минимум (кВт)", 0, 500, 100, step=10)
        
        with st.expander("💰 Параметры тарифов", expanded=False):
            p_peak = st.number_input("Пик (₽)", 0.0, 30.0, 9.5)
            p_half = st.number_input("Полупик (₽)", 0.0, 30.0, 6.8)
            p_night = st.number_input("Ночь (₽)", 0.0, 30.0, 3.2)
        
        st.divider()
        if not st.session_state.is_modeling:
            if st.button("🟢 НАЧАТЬ МОДЕЛИРОВАНИЕ", use_container_width=True, type="primary"):
                st.session_state.is_modeling = True
                st.rerun()
        else:
            if st.button("🔴 ОСТАНОВИТЬ МОДЕЛИРОВАНИЕ", use_container_width=True):
                st.session_state.is_modeling = False
                st.rerun()
    is_modeling = st.session_state.is_modeling
    df = df_raw.copy()
    df['hour'] = df['timestamp'].dt.hour
    
    cond = [(df['hour'] >= 23) | (df['hour'] < 7), (df['hour'] >= 7) & (df['hour'] < 10) | (df['hour'] >= 17) & (df['hour'] < 21)]
    prices_map = np.select(cond, [p_night, p_peak], default=p_half)
    cost_base = (df['load'] * 0.5 * prices_map).sum()
    df['load_opt'] = df['load'].copy()

    st.title("⚡ Поиск оптимального графика нагрузки")
    m1, m2, m3, m4 = st.columns(4)

    if is_modeling:
        hcs, hce = st.session_state.hc
        has, hae = st.session_state.ha
        overlap = not (hce <= has or hae <= hcs)
        
        load_in_interval = df.loc[(df['hour'] >= hcs) & (df['hour'] < hce), 'load']
        st.session_state.max_p_limit = max(0, int(load_in_interval.min() - tech_min)) if not load_in_interval.empty else 0

        # Коррекция мощности, если она превышает тех. минимум в выбранном интервале
        if st.session_state.p_val > st.session_state.max_p_limit:
            st.session_state.p_val = st.session_state.max_p_limit

        if not overlap:
            p_now = st.session_state.p_val
            df.loc[(df['hour'] >= hcs) & (df['hour'] < hce), 'load_opt'] -= p_now
            df.loc[(df['hour'] >= has) & (df['hour'] < hae), 'load_opt'] += (p_now * (hce-hcs) / (hae-has))

        cost_opt = (df['load_opt'] * 0.5 * prices_map).sum()
        savings = cost_base - cost_opt
        
        m1.metric("Текущие затраты", f"{cost_base:,.0f} ₽")
        m2.metric("Прогноз затрат", f"{cost_opt:,.0f} ₽")
        m3.metric("Экономия с учетом прогноза", f"{savings:,.0f} ₽", delta=f"{savings/cost_base*100:.1f}%" if not overlap else None)
        m4.metric("Пиковая нагрузка", f"{df['load_opt'].max():,.1f} кВт")

        st.divider()
        col_ctrl, col_chart = st.columns([1, 2.2], gap="large")

        with col_ctrl:
            st.subheader("🎮 Управление моделью")
            if st.button("🤖 ПОИСК МАКСИМАЛЬНОЙ ЭКОНОМИИ", use_container_width=True, type="primary"):
                pb = st.progress(0, text="Поиск...")
                best_s, best_params = -1, {}
                raw_l, hrs = df['load'].values, df['hour'].values
                p_range = np.arange(10, 1010, 10) 
                for idx, p in enumerate(p_range):
                    pb.progress((idx + 1) / len(p_range))
                    for hcs_t in range(24):
                        for dc in range(1, 6):
                            hce_t, dc_val = hcs_t + dc, dc
                            if hce_t > 24: continue
                            subset_c = raw_l[(hrs >= hcs_t) & (hrs < hce_t)]
                            if subset_c.size == 0 or p > (subset_c.min() - tech_min): continue 
                            for has_t in range(24):
                                for da in range(1, 10):
                                    hae_t, da_val = has_t + da, da
                                    if hae_t > 24 or not (hce_t <= has_t or hae_t <= hcs_t): continue
                                    temp = raw_l.copy()
                                    temp[(hrs >= hcs_t) & (hrs < hce_t)] -= p
                                    temp[(hrs >= has_t) & (hrs < hae_t)] += (p * dc_val / da_val)
                                    if temp.max() <= limit_val:
                                        cur_s = cost_base - (temp * 0.5 * prices_map).sum()
                                        if cur_s > best_s: best_s, best_params = cur_s, {'p': p, 'hc': (hcs_t, hce_t), 'ha': (has_t, hae_t)}
                pb.empty()
                if best_s > 0:
                    st.session_state.p_val, st.session_state.p_input_key = int(best_params['p']), int(best_params['p'])
                    st.session_state.hc, st.session_state.ha = best_params['hc'], best_params['ha']
                    st.rerun()

            with st.container(border=True):
                st.write("**🔽 Интервал разгрузки**")
                c1, c2, c3 = st.columns([1, 4, 1])
                c1.button("◀️", key="l1", on_click=move_interval, args=("hc", -1))
                c2.slider("hc_s", 0, 24, value=st.session_state.hc, key="hc", label_visibility="collapsed")
                c3.button("▶️", key="r1", on_click=move_interval, args=("hc", 1))
                st.write("**🔼 Интервал догрузки**")
                c4, c5, c6 = st.columns([1, 4, 1])
                c4.button("◀️", key="l2", on_click=move_interval, args=("ha", -1))
                c5.slider("ha_s", 0, 24, value=st.session_state.ha, key="ha", label_visibility="collapsed")
                c6.button("▶️", key="r2", on_click=move_interval, args=("ha", 1))
                st.number_input(f"Мощность, кВт (макс. {st.session_state.max_p_limit})", 0, max(st.session_state.max_p_limit, st.session_state.p_val), st.session_state.p_val, 50, key="p_input_key", on_change=update_p_val)

        with col_chart:
            fig = go.Figure()
            v = df.head(48)
            fig.add_trace(go.Scatter(x=v['timestamp'], y=v['load'], name="Профиль потребления", line=dict(color='gray', dash='dot')))
            if not overlap: 
                fig.add_trace(go.Scatter(x=v['timestamp'], y=v['load_opt'], name="Модель", fill='tozeroy', line=dict(color='#00d4ff')))
            fig.add_hline(y=limit_val, line_dash="dash", line_color="red", annotation_text="ЛИМИТ")
            fig.add_hline(y=tech_min, line_dash="dash", line_color="orange", annotation_text="ТЕХ. МИН")
            fig.update_layout(template="plotly_dark", height=450, margin=dict(t=20, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
            
            # --- ВЫВОД ПРЕДУПРЕЖДЕНИЙ ---
            if df['load_opt'].max() > limit_val:
                st.error(f"⚠️ ПРЕВЫШЕН ЛИМИТ! Пик: {df['load_opt'].max():,.1f} кВт")
            if overlap:
                st.warning("⚠️ Интервалы разгрузки и догрузки перекрываются!")
            if not load_in_interval.empty and load_in_interval.min() - st.session_state.p_val < tech_min:
                st.warning("⚠️ Нагрузка опускается ниже технологического минимума!")
    else:
        m1.metric("Текущие затраты", f"{cost_base:,.0f} ₽")
        m4.metric("Пиковая нагрузка", f"{df['load'].max():,.1f} кВт")
        fig = go.Figure(go.Scatter(x=df.head(48)['timestamp'], y=df.head(48)['load'], name="Факт", line=dict(color='#00d4ff')))
        fig.add_hline(y=limit_val, line_dash="dash", line_color="red", annotation_text="ЛИМИТ")
        fig.add_hline(y=tech_min, line_dash="dash", line_color="orange", annotation_text="ТЕХ. МИН")
        fig.update_layout(template="plotly_dark", height=580)
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    run_energy_app()
