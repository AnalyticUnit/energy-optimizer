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
    st.session_state.p_val = st.session_state.p_input_key

if 'hc' not in st.session_state: st.session_state.hc = (7, 10)
if 'ha' not in st.session_state: st.session_state.ha = (0, 7)
if 'p_val' not in st.session_state: st.session_state.p_val = 200

def run_energy_app():
    st.set_page_config(page_title="Energy AI Optimizer", layout="wide", initial_sidebar_state="expanded")
    
    # CSS: Сбалансированные отступы
    st.markdown("""
        <style>
        .main .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            margin-top: -20px;
        }
        h1 {
            padding-top: 0px !important;
            margin-top: -10px !important;
            margin-bottom: 10px !important;
        }
        .stMetric {background-color: #1e2129; padding: 15px; border-radius: 10px; border: 1px solid #31333f;}
        [data-testid="stSidebar"] {background-color: #0e1117;}
        </style>
    """, unsafe_allow_html=True)
    
    # --- СИДБАР (Настройки) ---
    with st.sidebar:
        st.header("⚙️ Настройки системы")
        
        # ВОССТАНОВЛЕННАЯ ПОЛНАЯ ПОДСКАЗКА
        uploaded_file = st.file_uploader(
            "Загрузить профиль нагрузки", 
            type=["xlsx", "csv"],
            help="""Файл должен содержать колонки:
- **timestamp**: дата и время (ГГГГ-ММ-ДД ЧЧ:ММ)
- **load**: значение нагрузки в кВт

**Пример:**


| timestamp | load |
| :--- | :--- |
| 2024-05-01 00:00 | 450.5 |
| 2024-05-01 00:30 | 432.1 |
"""
        )
        
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
        
        # НОВЫЙ ПАРАМЕТР
        tech_min = st.number_input(
            "Технологический минимум (кВт)", 0, 500, 100, step=10, 
            help="Уровень нагрузки (освещение, безопасность, ИТ), ниже которого завод не может опускаться даже при разгрузке."
        )
        
        with st.expander("💰 Параметры тарифа", expanded=False):
            p_peak = st.number_input("Пик (₽)", 9.5, value=9.5)
            p_half = st.number_input("Полупик (₽)", 6.8, value=6.8)
            p_night = st.number_input("Ночь (₽)", 3.2, value=3.2)
        
        st.divider()
        is_modeling = st.toggle("🚀 Режим AI-моделирования", value=False)

    # Расчет базы
    df = df_raw.copy()
    df['hour'] = df['timestamp'].dt.hour
    cond = [(df['hour'] >= 23) | (df['hour'] < 7), 
            (df['hour'] >= 7) & (df['hour'] < 10) | (df['hour'] >= 17) & (df['hour'] < 21)]
    prices_map = np.select(cond, [p_night, p_peak], default=p_half)
    cost_base = (df['load'] * 0.5 * prices_map).sum()
    df['load_opt'] = df['load'].copy()

    # --- ГЛАВНЫЙ ЭКРАН ---
    st.title("⚡ Energy AI Optimizer (v2 - Smart Limit)")
    
    m1, m2, m3, m4 = st.columns(4)
    
    if is_modeling:
        hcs, hce = st.session_state.hc
        has, hae = st.session_state.ha
        overlap = not (hce <= has or hae <= hcs)

        # ЛОГИКА УМНОГО ЛИМИТА С УЧЕТОМ ТЕХ. МИНИМУМА
        load_in_interval = df.loc[(df['hour'] >= hcs) & (df['hour'] < hce), 'load']
        max_p_allowed = int(load_in_interval.min() - tech_min) if not load_in_interval.empty else 600
        if max_p_allowed < 0: max_p_allowed = 0

        if st.session_state.p_val > max_p_allowed:
            st.session_state.p_val = max_p_allowed

        if not overlap:
            p_now = st.session_state.p_val
            df.loc[(df['hour'] >= hcs) & (df['hour'] < hce), 'load_opt'] -= p_now
            df.loc[(df['hour'] >= has) & (df['hour'] < hae), 'load_opt'] += (p_now * (hce-hcs) / (hae-has))

        cost_opt = (df['load_opt'] * 0.5 * prices_map).sum()
        savings = cost_base - cost_opt
        
        m1.metric("Текущие затраты", f"{cost_base:,.0f} ₽")
        m2.metric("Прогноз после опт.", f"{cost_opt:,.0f} ₽")
        m3.metric("Экономия", f"{savings:,.0f} ₽", delta=f"{savings/cost_base*100:.1f}%" if not overlap else None)
        m4.metric("Пиковая нагрузка", f"{df['load_opt'].max():,.1f} кВт")

        st.divider()
        col_ctrl, col_chart = st.columns([1, 2.2], gap="large")

        with col_ctrl:
            st.subheader("🎮 Управление моделью")
            if st.button("🤖 АВТО-ОПТИМИЗАЦИЯ", use_container_width=True, type="primary"):
                pb = st.progress(0, text="Поиск лучшего решения...")
                best_s, best_params = -1, {}
                raw_l, hrs = df['load'].values, df['hour'].values
                p_range = np.arange(10, 610, 10)
                
                for idx, p in enumerate(p_range):
                    pb.progress((idx + 1) / len(p_range))
                    for hcs_t in range(24):
                        for dc in range(1, 6):
                            hce_t = hcs_t + dc
                            if hce_t > 24: continue
                            subset_c = raw_l[(hrs >= hcs_t) & (hrs < hce_t)]
                            if subset_c.size == 0: continue
                            
                            # Учет тех. минимума в алгоритме
                            current_min_available = subset_c.min() - tech_min
                            if p > current_min_available: continue 

                            for has_t in range(24):
                                for da in range(1, 10):
                                    hae_t = has_t + da
                                    if hae_t > 24 or not (hce_t <= has_t or hae_t <= hcs_t): continue
                                    subset_a = raw_l[(hrs >= has_t) & (hrs < hae_t)]
                                    if subset_a.size == 0: continue
                                    
                                    temp = raw_l.copy()
                                    temp[(hrs >= hcs_t) & (hrs < hce_t)] -= p
                                    temp[(hrs >= has_t) & (hrs < hae_t)] += (p * dc / da)
                                    if temp.max() <= limit_val:
                                        cur_s = cost_base - (temp * 0.5 * prices_map).sum()
                                        if cur_s > best_s:
                                            best_s, best_params = cur_s, {'p': p, 'hc': (hcs_t, hce_t), 'ha': (has_t, hae_t)}
                pb.empty()
                if best_s > 0:
                    st.session_state.p_val = int(best_params['p'])
                    st.session_state.p_input_key = int(best_params['p'])
                    st.session_state.hc, st.session_state.ha = best_params['hc'], best_params['ha']
                    st.rerun()

            with st.container(border=True):
                st.write(f"**🔽 Интервал разгрузки** (Запас: {max_p_allowed} кВт)")
                c1, c2, c3 = st.columns(3)
                c1.button("◀️", key="l1", on_click=move_interval, args=("hc", -1))
                c2.slider("hc_s", 0, 24, value=st.session_state.hc, key="hc", label_visibility="collapsed")
                c3.button("▶️", key="r1", on_click=move_interval, args=("hc", 1))
                
                st.write("**🔼 Интервал догрузки**")
                c4, c5, c6 = st.columns(3)
                c4.button("◀️", key="l2", on_click=move_interval, args=("ha", -1))
                c5.slider("ha_s", 0, 24, value=st.session_state.ha, key="ha", label_visibility="collapsed")
                c6.button("▶️", key="r2", on_click=move_interval, args=("ha", 1))
                
                st.number_input("Мощность оборудования, кВт", 0, max_p_allowed, value=st.session_state.p_val, step=50, key="p_input_key", on_change=update_p_val)

        with col_chart:
            fig = go.Figure()
            v = df.head(48)
            fig.add_trace(go.Scatter(x=v['timestamp'], y=v['load'], name="База (факт)", line=dict(color='rgba(255,255,255,0.3)', dash='dot')))
            if not overlap:
                fig.add_trace(go.Scatter(x=v['timestamp'], y=v['load_opt'], name="Модель (план)", fill='tozeroy', line=dict(color='#00d4ff', width=3)))
            
            # ВИЗУАЛИЗАЦИЯ ЛИНИЙ
            fig.add_hline(y=tech_min, line_dash="dot", line_color="orange", annotation_text="ТЕХ. МИНИМУМ")
            fig.add_hline(y=limit_val, line_dash="dash", line_color="#ff4b4b", annotation_text="ЛИМИТ")
            fig.update_layout(template="plotly_dark", height=450, margin=dict(t=20, b=0, l=0, r=0), legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig, use_container_width=True)
            if overlap: st.warning("Интервалы перекрываются!")

    else:
        # РЕЖИМ ПРОСМОТРА
        m1.metric("Затраты за период", f"{cost_base:,.0f} ₽")
        m4.metric("Пик нагрузки", f"{df['load'].max():,.1f} кВт")
        fig = go.Figure().add_trace(go.Scatter(x=df.head(48)['timestamp'], y=df.head(48)['load'], name="Базовая нагрузка", line=dict(color='#00d4ff', width=3)))
        fig.add_hline(y=limit_val, line_dash="dash", line_color="#ff4b4b")
        fig.update_layout(template="plotly_dark", height=580, margin=dict(t=20, b=20, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    run_energy_app()
