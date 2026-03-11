import streamlit as st
import pandas as pd
from datetime import date
import calendar
import db
from scheduler import ScheduleGenerator
from exporter import export_schedule, export_schedule_pdf
import holidays
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
import extra_streamlit_components as stx
import streamlit.components.v1 as components

st.set_page_config(page_title="Generator Grafików Pro", layout="wide", initial_sidebar_state="expanded")

# --- Initialize Database ---
try:
    db.init_db()
except Exception as e:
    st.error(f"⚠️ Błąd połączenia z bazą danych: {str(e)}")
    st.info("Sprawdź ustawienia 'Secrets' na Streamlit Cloud. Prawdopodobnie musisz użyć linku 'Pooler' z Supabase (port 6543) zamiast bezpośredniego połączenia.")
    st.stop()

# --- Cookie Manager for 'Remember Me' ---
cookie_manager = stx.CookieManager(key="cm_global")

def check_cookies():
    # Cookie manager needs a moment to sync with browser
    creds = cookie_manager.get("remember_creds")
    if creds and "|" in creds and not st.session_state['authenticated']:
        try:
            saved_user, saved_pass = creds.split("|", 1)
            user = db.verify_user(saved_user, saved_pass)
            if user:
                st.session_state['authenticated'] = True
                st.session_state['user_role'] = user.role
                st.session_state['username'] = user.username
                return True
        except:
            pass
    return False

# --- Authentication ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['username'] = None

# Auto-login check
if not st.session_state['authenticated']:
    if check_cookies():
        st.rerun()

def login():
    st.title("🔒 Logowanie do Systemu")
    col1, col2 = st.columns([1, 1])
    with col1:
        with st.form("login_form"):
            username = st.text_input("Użytkownik")
            password = st.text_input("Hasło", type="password")
            remember = st.checkbox("Zapamiętaj mnie")
            submit = st.form_submit_button("Zaloguj")
            
            if submit:
                user = db.verify_user(username, password)
                if user:
                    st.session_state['authenticated'] = True
                    st.session_state['user_role'] = user.role
                    st.session_state['username'] = user.username
                    
                    if remember:
                        # Save credentials as a single string to avoid duplicate component calls
                        creds = f"{username}|{password}"
                        cookie_manager.set("remember_creds", creds, expires_at=date.today().replace(year=date.today().year + 1))
                    
                    st.success("Zalogowano pomyślnie!")
                    st.rerun()
                else:
                    st.error("Błędny użytkownik lub hasło")

if not st.session_state['authenticated']:
    login()
    st.stop()

# --- Custom CSS for Printing ---
st.markdown("""
<style>
@media print {
    /* Hide UI elements */
    [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stAppHeader"], .stButton, button {
        display: none !important;
    }
    /* Expand main area */
    .main .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        max-width: 100% !important;
    }
    /* Hide interactive components that don't print well */
    [data-testid="stDataFrame"], [data-testid="stDataEditor"], .stDataEditor {
        display: none !important;
    }
    /* Show static print table */
    .print-only {
        display: block !important;
    }
    /* Table styling for print */
    .print-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 10px;
    }
    .print-table th, .print-table td {
        border: 1px solid #000;
        padding: 3px;
        text-align: center;
    }
}
@media screen {
    .print-only {
        display: none;
    }
}
</style>
""", unsafe_allow_html=True)

def trigger_print():
    # window.parent.print() — drukuje główne okno, nie iframe Streamlit
    components.html("<script>window.parent.print()</script>", height=0)

# --- Helpers ---

def send_email_with_attachments(to_email, subject, body, attachments):
    smtp_server = st.secrets.get("smtp_server", "smtp.gmail.com")
    smtp_port = st.secrets.get("smtp_port", 587)
    smtp_user = st.secrets.get("smtp_user", "jakub.michalak1979@gmail.com")
    smtp_pass = st.secrets.get("smtp_pass", "") # App password needed

    if not smtp_pass:
        st.error("Błąd: Brak hasła SMTP w st.secrets!")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    for filepath in attachments:
        with open(filepath, "rb") as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(filepath)}')
            msg.attach(part)

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Błąd wysyłki: {e}")
        return False

# --- Main App ---

st.sidebar.title(f"Witaj, {st.session_state['username']}")
if st.sidebar.button("Wyloguj"):
    st.session_state['authenticated'] = False
    cookie_manager.delete("remember_creds")
    st.rerun()

# --- Initial State for Widgets ---
if 'selected_year' not in st.session_state:
    st.session_state['selected_year'] = date.today().year
if 'selected_month' not in st.session_state:
    st.session_state['selected_month'] = date.today().month
if 'selected_location_name' not in st.session_state:
    # Set default to first location if available
    locations = db.get_locations()
    if locations:
        st.session_state['selected_location_name'] = locations[0][1]
    else:
        st.session_state['selected_location_name'] = ""

locations = db.get_locations()
loc_dict = {name: id for id, name in locations}
loc_names = list(loc_dict.keys())

# Find index of saved location
try:
    loc_idx = loc_names.index(st.session_state['selected_location_name'])
except:
    loc_idx = 0

selected_loc_name = st.sidebar.selectbox(
    "Wybierz Obiekt", 
    loc_names, 
    index=loc_idx,
    key="location_widget"
)
# Manual update to avoid "setitem" error on bound keys
st.session_state['selected_location_name'] = selected_loc_name
location_id = loc_dict[selected_loc_name]

st.sidebar.divider()

if st.session_state['user_role'] == 'admin':
    menu_options = [
        "Generowanie Grafiku",
        "Niedostępności (Urlopy/L4)",
        "Statystyki",
        "Zatwierdzanie i Archiwum",
        "Pracownicy",
        "Zarządzanie Kontami"
    ]
else:
    menu_options = ["Mój Grafik", "Moje Preferencje", "Moje Statystyki"]

menu = st.sidebar.radio("Nawigacja", menu_options, key="nav_menu")

if menu == "Generowanie Grafiku":
    st.header(f"Generuj nowy grafik: {selected_loc_name}")
    col1, col2 = st.columns(2)
    
    rok = col1.number_input("Rok", 2020, 2030, st.session_state['selected_year'])
    miesiac = col2.number_input("Miesiąc", 1, 12, st.session_state['selected_month'])
    
    st.session_state['selected_year'] = rok
    st.session_state['selected_month'] = miesiac
        
    emps_master = db.get_employees(location_id)
    if not emps_master:
        st.warning("Dodaj pracowników!")
    else:
        # Check for existing DRAFT or APPROVED
        if 'active_schedule' not in st.session_state:
            saved_draft = db.get_schedule(rok, miesiac, location_id, status="DRAFT")
            saved_approved = db.get_schedule(rok, miesiac, location_id, status="APPROVED")
            
            if saved_draft:
                st.warning("⚠️ Masz zapisany roboczy grafik (DRAFT) dla tego miesiąca.")
                if st.button("Wczytaj DRAFT do edycji"):
                    st.session_state['active_schedule'] = saved_draft
                    st.session_state['schedule_status'] = "DRAFT"
            
            elif saved_approved:
                st.success("✅ Istnieje zatwierdzony grafik (APPROVED) dla tego miesiąca.")
                if st.button("Wczytaj APPROVED do podglądu/edycji"):
                    st.session_state['active_schedule'] = saved_approved
                    st.session_state['schedule_status'] = "APPROVED"

        st.divider()
        st.subheader("Opcje generowania")
        df_emps = pd.DataFrame([{"Imię i Nazwisko": e[1], "Uwzględnij": True} for e in emps_master])
        edited_emps = st.data_editor(df_emps, hide_index=True, key=f"emp_sel_{rok}_{miesiac}")
        included_names = edited_emps[edited_emps["Uwzględnij"] == True]["Imię i Nazwisko"].tolist()
        
        if st.button("Uruchom Generator (Nowa Propozycja)", type="primary"):
            with st.spinner("Przeliczanie..."):
                emps = [e for e in emps_master if e[1] in included_names]
                emp_dict = {i: name for i, (eid, name, email, s_order) in enumerate(emps)}
                emp_name_to_id = {name: eid for eid, name, email, s_order in emps}
                unav_rows = db.get_unavailabilities(rok, miesiac, location_id)
                unavailabilities = {}
                for eid, d, t in unav_rows:
                    m = [i for i, v in emp_dict.items() if emp_name_to_id[v] == eid]
                    if m:
                        idx = m[0]
                        if idx not in unavailabilities: unavailabilities[idx] = {}
                        unavailabilities[idx][d] = t
                
                generator = ScheduleGenerator(rok, miesiac, [emp_dict[i] for i in range(len(emps))], unavailabilities, location_name=selected_loc_name)
                wynik = generator.solve()
                if wynik:
                    st.session_state['active_schedule'] = wynik
                    st.session_state['schedule_status'] = "NEW"
                else:
                    st.error("Brak rozwiązania spełniającego zasady.")

        if 'active_schedule' in st.session_state:
            wynik = st.session_state['active_schedule']
            emp_name_to_id = {name: eid for eid, name, email, s_order in emps_master}
            pl_holidays = holidays.Poland(years=rok)
            
            days_in_month = calendar.monthrange(rok, miesiac)[1]
            days_list = list(range(1, days_in_month + 1))
            days_list_str = [str(d) for d in days_list]
            
            # Wymuszamy aby wszyscy pracownicy byli w tabeli
            for e in emps_master:
                if e[1] not in wynik:
                    wynik[e[1]] = {d: "" for d in days_list}
            
            # Upewniamy się, że dni są kluczami numerycznymi
            wynik_fixed = {name: {int(d): v for d, v in days.items()} for name, days in wynik.items()}
            wynik_str_keys = {name: {str(d): v for d, v in d_shifts.items()} for name, d_shifts in wynik_fixed.items()}
            df_wynik = pd.DataFrame.from_dict(wynik_str_keys, orient='index', columns=days_list_str)
            df_wynik = df_wynik.reindex([e[1] for e in emps_master])

            # --- Obliczenie Statystyk (Podsumowanie na prawo) ---
            r_list, p_list, n_list, w_list, u_list, ch_list, s_list, we_list = [], [], [], [], [], [], [], []
            for name, row in df_wynik.iterrows():
                row_list = row.fillna('').tolist()
                r_c = sum(1 for x in row_list if x == 'R')
                p_c = sum(1 for x in row_list if x == 'P')
                n_c = sum(1 for x in row_list if x == 'N')
                w_c = sum(1 for x in row_list if x == 'W')
                u_c = sum(1 for x in row_list if x == 'U')
                ch_c = sum(1 for x in row_list if x == 'CH')
                
                r_list.append(r_c); p_list.append(p_c); n_list.append(n_c)
                w_list.append(w_c); u_list.append(u_c); ch_list.append(ch_c)
                s_list.append(r_c + p_c + n_c + u_c + ch_c)
                
                we_count = 0
                for i, shift in enumerate(row_list):
                    day_val = days_list[i]
                    dt = date(rok, miesiac, day_val)
                    if (dt.weekday() >= 5 or dt in pl_holidays) and shift in ['R', 'P', 'N']:
                        we_count += 1
                we_list.append(we_count)
            
            df_wynik["R"] = r_list
            df_wynik["P"] = p_list
            df_wynik["N"] = n_list
            df_wynik["W"] = w_list
            df_wynik["U"] = u_list
            df_wynik["CH"] = ch_list
            df_wynik["S"] = s_list
            df_wynik["WE"] = we_list

            st.subheader("Edycja i weryfikacja grafiku")

            def style_preview(df_to_style):
                def highlight_days_gen(row):
                    styles = []
                    for col in row.index:
                        try:
                            d_int = int(col)
                            dt = date(rok, miesiac, d_int)
                            if dt.weekday() == 6 or dt in pl_holidays:
                                styles.append('background-color: #ffb3b3')
                            elif dt.weekday() == 5:
                                styles.append('background-color: #b3ffb3')
                            else: styles.append('')
                        except: styles.append('')
                    return styles
                def color_text(val):
                    if val == 'R': return 'color: green; font-weight: bold'
                    if val == 'P': return 'color: blue; font-weight: bold'
                    if val in ['W', 'U', 'CH']: return 'color: red; font-weight: bold'
                    if val == 'N': return 'color: black; font-weight: bold'
                    return ''
                return df_to_style.style.apply(highlight_days_gen, axis=1).map(color_text)

            st.write("💡 **Legenda kolorów (Podgląd):** Zielony = Sobota, Czerwony = Niedziela/Święto. Litery: R=zielony, P=niebieski, W/U/CH=czerwony")
            st.dataframe(style_preview(df_wynik[days_list_str]), use_container_width=True)

            # --- STATIC PRINT TABLE (Hidden on Screen) ---
            month_pl_names = ["", "STYCZEŃ", "LUTY", "MARZEC", "KWIECIEŃ", "MAJ", "CZERWIEC", 
                              "LIPIEC", "SIERPIEŃ", "WRZESIEŃ", "PAŹDZIERNIK", "LISTOPAD", "GRUDZIEŃ"]
            sum_cols = ["R", "P", "N", "W", "U", "CH", "S", "WE"]
            print_cols = days_list_str + sum_cols

            # Budujemy czysty HTML (st.table() nie renderuje się w ukrytym div)
            def shift_color(val):
                colors = {'R': '#006100', 'P': '#0070C0', 'N': '#000000',
                          'W': '#c00000', 'U': '#c00000', 'CH': '#c00000'}
                return colors.get(str(val), '#000000')

            def day_bg(col):
                try:
                    d_int = int(col)
                    dt = date(rok, miesiac, d_int)
                    if dt.weekday() == 6 or dt in pl_holidays:
                        return '#FFC7CE'
                    elif dt.weekday() == 5:
                        return '#C6EFCE'
                except:
                    pass
                return '#ffffff'

            th_cells = '<th style="border:1px solid #000;padding:3px;background:#d0d0d0">Imię i Nazwisko</th>'
            for col in print_cols:
                bg = day_bg(col)
                th_cells += f'<th style="border:1px solid #000;padding:2px;background:{bg};font-size:9px">{col}</th>'

            tr_rows = ''
            for emp_name, row in df_wynik[print_cols].iterrows():
                tds = f'<td style="border:1px solid #000;padding:3px;white-space:nowrap"><b>{emp_name}</b></td>'
                for col in print_cols:
                    val = row[col]
                    val_str = '' if (val is None or str(val) == 'nan') else str(val)
                    color = shift_color(val_str) if col not in sum_cols else '#000000'
                    bg = day_bg(col)
                    tds += f'<td style="border:1px solid #000;padding:2px;text-align:center;color:{color};font-weight:bold;background:{bg};font-size:9px">{val_str}</td>'
                tr_rows += f'<tr>{tds}</tr>'

            print_html = f"""
            <div class="print-only">
                <h2 style="margin:4px 0">GRAFIK — OBIEKT {selected_loc_name.upper()}</h2>
                <h3 style="margin:4px 0">MIESIĄC {month_pl_names[miesiac]} ROK {rok}</h3>
                <table style="width:100%;border-collapse:collapse;font-size:9px;margin-top:8px">
                    <thead><tr>{th_cells}</tr></thead>
                    <tbody>{tr_rows}</tbody>
                </table>
            </div>
            """
            st.markdown(print_html, unsafe_allow_html=True)

            # --- Edytor z Podsumowaniem po prawej ---
            shift_options = ['', 'R', 'P', 'N', 'W', 'U', 'CH']
            col_config = {}
            for d in days_list:
                d_s = str(d); dt = date(rok, miesiac, d)
                label = f"🔴 {d_s}" if (dt.weekday() == 6 or dt in pl_holidays) else (f"🟢 {d_s}" if dt.weekday() == 5 else d_s)
                col_config[d_s] = st.column_config.SelectboxColumn(label, options=shift_options, width="small")

            for col in ["R", "P", "N", "W", "U", "CH", "S", "WE"]:
                col_config[col] = st.column_config.Column(col, disabled=True, width="small")
            
            edited_df = st.data_editor(df_wynik, column_config=col_config, key=f"edit_{rok}_{miesiac}", use_container_width=True)
            
            # Walidacja
            warnings = []
            for name, row in edited_df[days_list_str].iterrows():
                row_list = row.fillna('').tolist()
                for i in range(len(row_list) - 1):
                    if (row_list[i], row_list[i+1]) in [('P', 'R'), ('N', 'R'), ('N', 'P')]:
                        warnings.append(f"⚠️ **{name}**: Brak 11h odpoczynku między dniem {i+1} a {i+2}")
                work_streak = 0
                for i, shift in enumerate(row_list):
                    if shift in ['R', 'P', 'N']:
                        work_streak += 1
                        if work_streak > 6: warnings.append(f"⚠️ **{name}**: Ponad 6 dni pracy z rzędu (dzień {i+1})")
                    else: work_streak = 0

            if warnings:
                for w in warnings: st.warning(w)
            else: st.success("✅ Grafik zgodny z podstawowymi zasadami odpoczynku.")

            c1, c2 = st.columns(2)
            if c1.button("Zapisz jako Roboczy (DRAFT)"):
                new_w = edited_df[days_list_str].to_dict(orient='index')
                new_w_int = {nm: {int(dk): dv for dk, dv in ds.items()} for nm, ds in new_w.items()}
                db.save_schedule(new_w_int, rok, miesiac, emp_name_to_id, location_id, status="DRAFT", user=st.session_state['username'])
                st.success("Grafik zapisany jako Roboczy (DRAFT)!")

            if st.session_state['user_role'] == 'admin':
                if c2.button("Zatwierdź Grafik (APPROVED)", type="primary"):
                    new_w = edited_df[days_list_str].to_dict(orient='index')
                    new_w_int = {nm: {int(dk): dv for dk, dv in ds.items()} for nm, ds in new_w.items()}
                    db.save_schedule(new_w_int, rok, miesiac, emp_name_to_id, location_id, status="APPROVED", user=st.session_state['username'])
                    st.success("GRAFIK ZATWIERDZONY!")
                    fx, fp = f"grafik_{miesiac}_{rok}.xlsx", f"grafik_{miesiac}_{rok}.pdf"
                    export_schedule(new_w_int, rok, miesiac, fx, location_name=selected_loc_name)
                    export_schedule_pdf(new_w_int, rok, miesiac, fp, location_name=selected_loc_name)
                    ca, cb = st.columns(2)
                    with open(fx, "rb") as f: ca.download_button("Pobierz Excel", f, fx)
                    with open(fp, "rb") as f: cb.download_button("Pobierz PDF", f, fp)
            
            st.divider()
            if st.button("Drukuj obecny widok (Podgląd Draftu)"):
                new_w = edited_df[days_list_str].to_dict(orient='index')
                new_w_int = {nm: {int(dk): dv for dk, dv in ds.items()} for nm, ds in new_w.items()}
                f_x = f"roboczy_{miesiac}.xlsx"; f_p = f"roboczy_{miesiac}.pdf"
                export_schedule(new_w_int, rok, miesiac, f_x, location_name=selected_loc_name)
                export_schedule_pdf(new_w_int, rok, miesiac, f_p, location_name=selected_loc_name)
                da, db_p = st.columns(2)
                with open(f_x, "rb") as f: da.download_button("Excel (Draft)", f, f_x)
                with open(f_p, "rb") as f: db_p.download_button("PDF (Draft)", f, f_p)
            
            if st.button("🖨️ DRUKUJ GRAFIK (Bezpośrednio)", use_container_width=True):
                trigger_print()

elif menu == "Zatwierdzanie i Archiwum" and st.session_state['user_role'] == 'admin':
    st.header("🗂️ Archiwum i Zarządzanie Grafikami")
    st.write(f"Wybrany obiekt: **{selected_loc_name}**")

    # Pobierz dostępne grafiki dla WYBRANEGO obiektu
    all_drafts_raw = db.get_all_schedules_with_status("DRAFT")
    all_approved_raw = db.get_all_schedules_with_status("APPROVED")
    
    # Filtrujemy tylko dla obecnego 'location_id'
    loc_drafts = [d for d in all_drafts_raw if d[2] == location_id]
    loc_approved = [d for d in all_approved_raw if d[2] == location_id]

    month_pl_names = ["", "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", 
                       "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]

    tab_draft, tab_arch = st.tabs(["❗ Szkice do zatwierdzenia (Drafty)", "✅ Zatwierdzone (Archiwum)"])

    with tab_draft:
        st.subheader("Grafiki robocze (DRAFT) czekające na edycję/zatwierdzenie")
        if not loc_drafts:
            st.success(f"Brak oczekujących draftów dla obiektu '{selected_loc_name}'. Wszystko załatwione!")
        else:
            draft_options = [f"{month_pl_names[mo]} {yr}" for yr, mo, _, _ in loc_drafts]
            sel_draft_label = st.selectbox("Wybierz szkic:", draft_options, key="draft_sel")
            idx = draft_options.index(sel_draft_label)
            d_yr, d_mo, d_loc_id, d_loc_name = loc_drafts[idx]

            c1, c2 = st.columns([1, 1])
            if c1.button("✏️ Wczytaj wybrany Draft do Edytora", type="primary", use_container_width=True):
                st.session_state['selected_year'] = d_yr
                st.session_state['selected_month'] = d_mo
                st.session_state['active_schedule'] = db.get_schedule(d_yr, d_mo, d_loc_id, status="DRAFT")
                st.session_state['schedule_status'] = "DRAFT"
                st.session_state['nav_menu'] = "Generowanie Grafiku"
                st.rerun()

    with tab_arch:
        st.subheader("Przewijaj historyczne grafiki")
        if not loc_approved:
            st.info(f"Brak zatwierdzonych grafików w archiwum dla '{selected_loc_name}'.")
        else:
            app_options = [f"{month_pl_names[mo]} {yr}" for yr, mo, _, _ in loc_approved]
            sel_app_label = st.selectbox("Wybierz zatwierdzony grafik:", app_options, key="app_sel")
            idx_a = app_options.index(sel_app_label)
            a_yr, a_mo, a_loc_id, a_loc_name = loc_approved[idx_a]

            approved = db.get_schedule(a_yr, a_mo, a_loc_id, status="APPROVED")
            
            # --- Tabela podglądu bezpośredniego ---
            pl_holidays = holidays.Poland(years=a_yr)
            days_in_month = calendar.monthrange(a_yr, a_mo)[1]
            days_list_str = [str(d) for d in range(1, days_in_month + 1)]
            
            approved_fixed = {name: {str(d): v for d, v in days.items()} for name, days in approved.items()}
            df_app = pd.DataFrame.from_dict(approved_fixed, orient='index', columns=days_list_str)
            st.dataframe(df_app, use_container_width=True)

            # --- Generowanie HTML do druku (ukryte) ---
            def day_bg2(col, y, m):
                try:
                    dt2 = date(y, m, int(col))
                    ph2 = holidays.Poland(years=y)
                    if dt2.weekday() == 6 or dt2 in ph2: return '#FFC7CE'
                    if dt2.weekday() == 5: return '#C6EFCE'
                except: pass
                return '#ffffff'

            def shift_color2(val):
                c = {'R': '#006100', 'P': '#0070C0', 'N': '#000000', 'W': '#c00000', 'U': '#c00000', 'CH': '#c00000'}
                return c.get(str(val), '#000000')

            th_cells2 = '<th style="border:1px solid #000;padding:3px;background:#d0d0d0">Imię i Nazwisko</th>'
            for col2 in days_list_str:
                th_cells2 += f'<th style="border:1px solid #000;padding:2px;background:{day_bg2(col2, a_yr, a_mo)};font-size:9px">{col2}</th>'

            tr_rows2 = ''
            for emp_name2, row2 in df_app.iterrows():
                tds2 = f'<td style="border:1px solid #000;padding:3px;white-space:nowrap"><b>{emp_name2}</b></td>'
                for col2 in days_list_str:
                    val2 = str(row2[col2]) if pd.notna(row2[col2]) else ''
                    tds2 += f'<td style="border:1px solid #000;padding:2px;text-align:center;font-weight:bold;color:{shift_color2(val2)};font-size:10px">{val2}</td>'
                tr_rows2 += f'<tr>{tds2}</tr>'

            print_html2 = f"""
            <div class="print-element print-only" style="width:100%; font-family:sans-serif;">
                <h3 style="text-align:center; margin-bottom:10px;">GRAFIK PRACY: {a_loc_name} - {sel_app_label.upper()} (ZATWIERDZONY)</h3>
                <table style="width:100%; border-collapse:collapse; text-align:center; font-size:11px;">
                    <thead><tr>{th_cells2}</tr></thead>
                    <tbody>{tr_rows2}</tbody>
                </table>
            </div>
            """
            st.markdown(print_html2, unsafe_allow_html=True)

            # --- Przyciski eksportu ---
            st.divider()
            c_p, c_e, c_pf = st.columns(3)
            if c_p.button("🖨️ Drukuj Archiwum", use_container_width=True):
                trigger_print()
                
            f_xl = f"archiwum_{a_mo}_{a_yr}.xlsx"
            f_pd = f"archiwum_{a_mo}_{a_yr}.pdf"
            export_schedule(approved, a_yr, a_mo, f_xl, location_name=selected_loc_name)
            export_schedule_pdf(approved, a_yr, a_mo, f_pd, location_name=selected_loc_name)
            
            with open(f_xl, "rb") as f: c_e.download_button("Pobierz Excel", f, f_xl, use_container_width=True)
            with open(f_pd, "rb") as f: c_pf.download_button("Pobierz PDF", f, f_pd, use_container_width=True)
    
    # The original "if not draft and not approved" block is now handled by the tab logic
    # and the specific messages within each tab.
    # This part of the original code is no longer needed:
    # if not draft and not approved:
    #     st.info(f"Brak zapisanych grafików dla obiektu {selected_loc_name} w okresie {m_ar}/{r_ar}.")

elif menu == "Niedostępności (Urlopy/L4)":
    st.header("Grafik nieobecności")
    colX, colY = st.columns(2)
    vr = colX.number_input("Rok", 2020, 2030, st.session_state.get('selected_year', date.today().year), key="unav_r")
    vm = colY.number_input("Miesiąc", 1, 12, st.session_state.get('selected_month', date.today().month), key="unav_m")
    
    st.session_state['selected_year'] = vr
    st.session_state['selected_month'] = vm
    
    pl_holidays = holidays.Poland(years=vr)

    emps = db.get_employees(location_id)
    if emps:
        emp_names = {e[1]: e[0] for e in emps}
        reverse_emps = {e[0]: e[1] for e in emps}
        unav = db.get_unavailabilities(vr, vm, location_id)
        num_days = calendar.monthrange(vr, vm)[1]
        
        df = pd.DataFrame(index=[e[1] for e in emps], columns=[str(d) for d in range(1, num_days+1)])
        for eid, d, t in unav:
            if eid in reverse_emps: df.at[reverse_emps[eid], str(d)] = t
        # --- Kolorowanie podglądu nieobecności ---
        def style_unav(df_to_style):
            def highlight_days(row):
                styles = []
                for col in row.index:
                    try:
                        d_int = int(col)
                        dt = date(vr, vm, d_int)
                        if dt.weekday() == 6 or dt in pl_holidays:
                            styles.append('background-color: #ffccce')
                        elif dt.weekday() == 5:
                            styles.append('background-color: #ccffcc')
                        else: styles.append('')
                    except: styles.append('')
                return styles

            def color_text_unav(val):
                if val in ['W', 'U', 'CH', 'N', 'NR', 'NP', 'NN']: return 'color: red; font-weight: bold'
                if val in ['R', 'TR']: return 'color: green; font-weight: bold'
                if val in ['P', 'TP']: return 'color: blue; font-weight: bold'
                if val == 'TN': return 'color: black; font-weight: bold'
                return ''

            return df_to_style.style.apply(highlight_days, axis=1).map(color_text_unav)

        st.write("**Podgląd dni i zmian (kolory):**")
        st.dataframe(style_unav(df), use_container_width=True)

        # Definicja dropdownów dla każdego dnia z kolorowymi kropkami
        day_config = {}
        for d in range(1, num_days + 1):
            d_s = str(d)
            dt = date(vr, vm, d)
            label = d_s
            if dt.weekday() == 6 or dt in pl_holidays:
                label = f"🔴 {d_s}"
            elif dt.weekday() == 5:
                label = f"🟢 {d_s}"
            
            day_config[d_s] = st.column_config.SelectboxColumn(
                label=label,
                width="small",
                options=['', 'W', 'U', 'CH', 'R', 'P', 'N', 'NR', 'NP', 'NN', 'TR', 'TP', 'TN'],
                required=False
            )
        
        edited = st.data_editor(
            df, 
            use_container_width=True, 
            column_config=day_config,
            key="unav_editor"
        )
        
        if st.button("Zapisz"):
            data = []
            for name, row in edited.iterrows():
                eid = emp_names[name]
                for d_str, v in row.items():
                    if pd.notna(v) and str(v).strip():
                        data.append((eid, int(d_str), str(v).upper()))
            db.update_unavailabilities_for_month(vr, vm, data, location_id)
            st.success("Zapisano pomyślnie!")

elif menu == "Statystyki":
    st.header(f"📊 Statystyki — {selected_loc_name}")

    today = date.today()

    # --- Inicjalizacja stanu ---
    if 'stats_yr_from' not in st.session_state:
        st.session_state['stats_yr_from'] = today.year
    if 'stats_mo_from' not in st.session_state:
        st.session_state['stats_mo_from'] = today.month
    if 'stats_yr_to' not in st.session_state:
        st.session_state['stats_yr_to'] = today.year
    if 'stats_mo_to' not in st.session_state:
        st.session_state['stats_mo_to'] = today.month

    # --- Przyciski skrótów ---
    st.subheader("⚡ Szybki wybór zakresu")
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)

    if pc1.button("Ten miesiąc", use_container_width=True):
        st.session_state.update({'stats_yr_from': today.year, 'stats_mo_from': today.month,
                                  'stats_yr_to': today.year,   'stats_mo_to':   today.month})
        st.rerun()

    if pc2.button("Ten kwartał", use_container_width=True):
        q_start = ((today.month - 1) // 3) * 3 + 1
        q_end   = min(q_start + 2, 12)
        st.session_state.update({'stats_yr_from': today.year, 'stats_mo_from': q_start,
                                  'stats_yr_to': today.year,   'stats_mo_to':   q_end})
        st.rerun()

    if pc3.button("Ten rok", use_container_width=True):
        st.session_state.update({'stats_yr_from': today.year, 'stats_mo_from': 1,
                                  'stats_yr_to': today.year,   'stats_mo_to':   12})
        st.rerun()

    if pc4.button("Poprzedni kwartał", use_container_width=True):
        q = (today.month - 1) // 3
        if q == 0:
            st.session_state.update({'stats_yr_from': today.year-1, 'stats_mo_from': 10,
                                      'stats_yr_to': today.year-1,   'stats_mo_to':   12})
        else:
            q_start = (q - 1) * 3 + 1
            st.session_state.update({'stats_yr_from': today.year, 'stats_mo_from': q_start,
                                      'stats_yr_to': today.year,   'stats_mo_to':   q_start + 2})
        st.rerun()

    if pc5.button("Poprzedni rok", use_container_width=True):
        st.session_state.update({'stats_yr_from': today.year-1, 'stats_mo_from': 1,
                                  'stats_yr_to': today.year-1,   'stats_mo_to':   12})
        st.rerun()

    # --- Własny zakres dat ---
    st.subheader("📅 Własny zakres dat")
    c_from, c_to = st.columns(2)
    with c_from:
        st.write("**Od:**")
        fc1, fc2 = st.columns(2)
        yr_from = fc1.number_input("Rok",     2020, 2030, st.session_state['stats_yr_from'], key="stats_yr_from_w")
        mo_from = fc2.number_input("Miesiąc", 1,    12,   st.session_state['stats_mo_from'], key="stats_mo_from_w")
    with c_to:
        st.write("**Do:**")
        tc1, tc2 = st.columns(2)
        yr_to = tc1.number_input("Rok",     2020, 2030, st.session_state['stats_yr_to'], key="stats_yr_to_w")
        mo_to = tc2.number_input("Miesiąc", 1,    12,   st.session_state['stats_mo_to'], key="stats_mo_to_w")

    # Zapisz aktualny wybór
    st.session_state.update({'stats_yr_from': yr_from, 'stats_mo_from': mo_from,
                              'stats_yr_to': yr_to,     'stats_mo_to':   mo_to})

    if yr_from * 12 + mo_from > yr_to * 12 + mo_to:
        st.error("⚠️ Data 'Od' musi być wcześniejsza lub równa dacie 'Do'.")
    else:
        month_abbr = ["","Sty","Lut","Mar","Kwi","Maj","Cze","Lip","Sie","Wrz","Paź","Lis","Gru"]
        label_from = f"{month_abbr[mo_from]} {yr_from}"
        label_to   = f"{month_abbr[mo_to]} {yr_to}"
        range_label = label_from if (yr_from == yr_to and mo_from == mo_to) else f"{label_from} — {label_to}"

        stats_r = db.get_stats_for_range(location_id, yr_from, mo_from, yr_to, mo_to)

        if stats_r:
            st.success(f"📋 Zakres: **{range_label}** | Obiekt: **{selected_loc_name}**")

            df_stats = pd.DataFrame.from_dict(stats_r, orient='index')
            df_stats = df_stats[['R', 'P', 'N', 'W', 'U', 'CH', 'S', 'WE']].fillna(0).astype(int)
            df_stats.index.name = "Pracownik"

            # Wiersz SUMA
            suma_row = df_stats.sum().rename("SUMA")
            df_display = pd.concat([df_stats, suma_row.to_frame().T])

            # Styl tabeli
            def style_stats(df_s):
                def row_style(row):
                    if row.name == "SUMA":
                        return ['background-color: #d0e8ff; font-weight: bold; color: #003366'] * len(row)
                    return [''] * len(row)
                def val_color(val):
                    return 'font-weight: bold' if val > 0 else 'color: #aaaaaa'
                return df_s.style.apply(row_style, axis=1).map(val_color)

            st.dataframe(style_stats(df_display), use_container_width=True)

            # --- Wykres słupkowy ---
            st.subheader("📈 Porównanie zmian na pracownika")
            chart_cols = st.multiselect(
                "Wybierz typy zmian do wykresu:",
                options=['R', 'P', 'N', 'W', 'U', 'CH', 'WE'],
                default=['R', 'P', 'N'],
                key="stats_chart_cols"
            )
            if chart_cols:
                st.bar_chart(df_stats[chart_cols])
            else:
                st.info("Wybierz przynajmniej jeden typ zmiany.")
        else:
            st.info(f"Brak zatwierdzonych grafików dla obiektu **{selected_loc_name}** w zakresie **{range_label}**. "
                     f"Grafiki muszą mieć status APPROVED, żeby pojawiły się w statystykach.")

elif menu == "Pracownicy" and st.session_state['user_role'] == 'admin':
    st.header("Baza Pracowników")
    with st.expander("Dodaj nowego pracownika"):
        new_name = st.text_input("Imię i Nazwisko")
        new_email = st.text_input("Email")
        new_order = st.number_input("Kolejność (0-100)", 0, 100, 0)
        if st.button("Dodaj"):
            db.add_employee(new_name, location_id, new_email, new_order)
            st.success("Dodano!")
            st.rerun()
    
    st.divider()
    st.subheader("Lista pracowników i kolejność")
    
    emps_data = db.get_employees(location_id)
    if emps_data:
        # Create a dataframe for easy editing
        # emps_data tuple: (id, name, email, sort_order)
        df_order = pd.DataFrame([{"ID": e[0], "Imię i Nazwisko": e[1], "Email": e[2], "Kolejność": e[3]} for e in emps_data])
        edited_order = st.data_editor(df_order, hide_index=True, disabled=["ID"])
        
        if st.button("Zapisz zmiany (Dane i Kolejność)"):
            for _, row in edited_order.iterrows():
                db.update_employee_order(row["ID"], row["Kolejność"])
                db.update_employee(row["ID"], row["Imię i Nazwisko"], row["Email"])
            st.success("Zmiany zostały zapisane!")
            st.rerun()

        st.divider()
        st.subheader("Zarządzanie (Usuwanie)")
        for eid, name, email, s_order in emps_data:
            c1, c2, c3 = st.columns([3, 3, 1])
            c1.write(f"**{name}** (Poz: {s_order})")
            c2.write(email if email else "-")
            if c3.button("Usuń", key=f"del_emp_{eid}"):
                db.remove_employee(eid)
                st.rerun()
    else:
        st.write("Brak pracowników.")

elif menu == "Zarządzanie Kontami" and st.session_state['user_role'] == 'admin':
    st.header("Zarządzanie Kontami Użytkowników")
    st.write("Tutaj możesz zarządzać osobami, które mają dostęp do tej aplikacji.")

    with st.expander("Utwórz nowe konto"):
        new_user = st.text_input("Nazwa użytkownika")
        new_pass = st.text_input("Hasło użytkownika", type="password")
        new_role = st.selectbox("Rola", ["user", "admin"])
        if st.button("Utwórz Konto"):
            if new_user and new_pass:
                db.add_user(new_user, new_pass, new_role)
                st.success(f"Dodano użytkownika {new_user}!")
                st.rerun()
            else:
                st.error("Wypełnij wszystkie pola.")

    st.divider()
    st.subheader("Aktualne konta w systemie")

    # Pobierz wszystkich pracowników ze wszystkich obiektów do powiązania
    all_emps_for_link = []
    for loc_id_l, loc_name_l in db.get_locations():
        for eid_l, ename_l, _, _ in db.get_employees(loc_id_l):
            all_emps_for_link.append((eid_l, f"{ename_l} ({loc_name_l})"))
    emp_link_options = {"Brak powiązania": None}
    emp_link_options.update({label: eid for eid, label in all_emps_for_link})

    users_full = db.get_users_full()
    for uid, uname, urole, linked_emp_id in users_full:
        st.divider()
        colA, colB, colC, colD = st.columns([2, 2, 3, 1])
        colA.write(f"**{uname}**")
        colB.write(f"Rola: `{urole}`")

        # Selectbox powiązania z pracownikiem
        current_label = "Brak powiązania"
        for eid_l, label_l in all_emps_for_link:
            if eid_l == linked_emp_id:
                current_label = label_l
                break
        all_labels = list(emp_link_options.keys())
        curr_idx = all_labels.index(current_label) if current_label in all_labels else 0
        chosen = colC.selectbox(
            "Powiąż z pracownikiem",
            options=all_labels,
            index=curr_idx,
            key=f"link_emp_{uid}",
            label_visibility="collapsed"
        )
        if colC.button("Zapisz powiązanie", key=f"save_link_{uid}"):
            db.link_user_to_employee(uid, emp_link_options[chosen])
            st.success(f"Powiązano konto **{uname}** z: **{chosen}**")
            st.rerun()

        if uname != 'admin':
            if colD.button("Usuń", key=f"user_{uid}"):
                db.remove_user(uid)
                st.rerun()
        else:
            colD.write("🔒")

# ========================================
# SEKCJE DLA PRACOWNIKA (rola: user)
# ========================================

elif menu == "Mój Grafik":
    st.header("📅 Grafik Działu")

    my_emp = db.get_employee_for_user(st.session_state['username'])
    if not my_emp:
        st.warning("⚠️ Twoje konto nie jest powiązane z żadnym pracownikiem. "
                   "Skontaktuj się z administratorem, aby powiązał Twój login z profilem pracownika.")
        st.stop()

    emp_id, emp_name, emp_loc_id, emp_email, _ = my_emp
    st.info(f"👤 Zalogowany jako: **{emp_name}** | Twój wiersz jest podświetlony na żółto.")

    # Znajdź dostępne miesiące dla całego działu (nie tylko tego pracownika)
    dept_schedule_months = []
    for yr_a, mo_a, loc_a in db.get_my_schedule_months(emp_id):
        dept_schedule_months.append((yr_a, mo_a, loc_a))

    # Dodaj też miesiące z bazy dla całej lokalizacji (może być więcej niż dla tego pracownika)
    from db import SessionLocal, Schedule, Location as DbLocation
    try:
        _db = SessionLocal()
        _rows = _db.query(Schedule.year, Schedule.month).filter(
            Schedule.location_id == emp_loc_id,
            Schedule.status == "APPROVED"
        ).distinct().all()
        _db.close()
        for _yr, _mo in _rows:
            if (_yr, _mo, None) not in [(r[0], r[1], None) for r in dept_schedule_months]:
                dept_schedule_months.append((_yr, _mo, "Dział"))
    except Exception:
        pass

    # Deduplikacja i sortowanie
    seen = set()
    unique_months = []
    month_pl_names = ["","Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                      "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]
    for yr_m, mo_m, loc_m in dept_schedule_months:
        key = (yr_m, mo_m)
        if key not in seen:
            seen.add(key)
            unique_months.append((yr_m, mo_m))
    unique_months.sort(key=lambda x: (x[0], x[1]), reverse=True)

    if not unique_months:
        st.info("Brak zatwierdzonych grafików dla Twojego działu. Grafiki pojawią się tutaj, gdy administrator je zatwierdzi.")
    else:
        month_labels = [f"{month_pl_names[mo]} {yr}" for yr, mo in unique_months]
        chosen_label = st.selectbox("Wybierz miesiąc:", month_labels, key="my_sched_month")
        chosen_idx = month_labels.index(chosen_label)
        sel_yr, sel_mo = unique_months[chosen_idx]

        # Pełny grafik działu
        full_schedule = db.get_schedule(sel_yr, sel_mo, emp_loc_id, status="APPROVED")
        pl_holidays = holidays.Poland(years=sel_yr)
        num_days = calendar.monthrange(sel_yr, sel_mo)[1]
        days_list = list(range(1, num_days + 1))
        days_str = [str(d) for d in days_list]

        if not full_schedule:
            st.info("Brak zatwierdzonego grafiku dla tego miesiąca.")
        else:
            shift_txt_color = {
                'R': '#006100', 'P': '#0070C0', 'N': '#222222',
                'W': '#c00000', 'U': '#c00000', 'CH': '#880000'
            }

            def day_header_bg(d):
                dt = date(sel_yr, sel_mo, d)
                if dt.weekday() == 6 or dt in pl_holidays:
                    return '#FFCDD2'
                elif dt.weekday() == 5:
                    return '#DCEDC8'
                return '#e8e8e8'

            def day_cell_bg(d):
                dt = date(sel_yr, sel_mo, d)
                if dt.weekday() == 6 or dt in pl_holidays:
                    return '#FFF3F3'
                elif dt.weekday() == 5:
                    return '#F3FFF3'
                return '#ffffff'

            # Buduj nagłówek tabeli
            th_html = '<th style="border:1px solid #ccc; padding:5px 8px; background:#d0d0d0; text-align:left; white-space:nowrap">Pracownik</th>'
            for d in days_list:
                bg = day_header_bg(d)
                dt_h = date(sel_yr, sel_mo, d)
                dow = ['Pn','Wt','Śr','Cz','Pt','So','Nd'][dt_h.weekday()]
                th_html += f'<th style="border:1px solid #ccc; padding:3px 2px; background:{bg}; text-align:center; min-width:26px; font-size:10px">{d}<br><span style="font-weight:normal">{dow}</span></th>'

            # Pobierz kolejność pracowników
            all_emps_dept = db.get_employees(emp_loc_id)
            ordered_names = [e[1] for e in all_emps_dept]
            # Pracownicy w grafiku, których nie ma w liście — dołącz na końcu
            for name in full_schedule:
                if name not in ordered_names:
                    ordered_names.append(name)

            # Wiersze tabeli
            tr_html = ''
            my_shifts = {}
            for emp_row_name in ordered_names:
                if emp_row_name not in full_schedule:
                    continue
                shifts_row = full_schedule[emp_row_name]
                is_me = (emp_row_name == emp_name)
                row_bg = '#FFFDE7' if is_me else '#ffffff'
                name_style = 'font-weight:bold; color:#BF6900' if is_me else ''
                me_mark = ' ⬅' if is_me else ''

                tds = f'<td style="border:1px solid #ccc; padding:4px 8px; background:{row_bg}; white-space:nowrap; {name_style}">{emp_row_name}{me_mark}</td>'
                for d in days_list:
                    shift = shifts_row.get(d, '')
                    if is_me:
                        my_shifts[d] = shift
                    fc = shift_txt_color.get(shift, '#888888')
                    cbg = day_cell_bg(d)
                    if is_me:
                        cbg = '#FFFDE7'  # żółte tło dla mojego wiersza
                    tds += f'<td style="border:1px solid #ccc; padding:3px 2px; text-align:center; background:{cbg}; color:{fc}; font-weight:bold; font-size:12px">{shift if shift else ""}</td>'
                tr_html += f'<tr>{tds}</tr>'

            table_html = f'''
            <style>
              .dept-sched-table {{ font-family: sans-serif; border-collapse: collapse; font-size: 12px; width: 100%; }}
              .dept-sched-table td, .dept-sched-table th {{ border: 1px solid #ccc; }}
            </style>
            <div style="overflow-x:auto; margin-top:10px">
            <table class="dept-sched-table">
              <thead><tr>{th_html}</tr></thead>
              <tbody>{tr_html}</tbody>
            </table>
            </div>
            '''
            st.markdown(table_html, unsafe_allow_html=True)

            # Legenda
            st.markdown("""
            <div style='margin-top:10px; font-size:12px; color:#555'>
            <b>Legenda:</b>
            <span style='color:#006100'>■ R</span> Rano &nbsp;
            <span style='color:#0070C0'>■ P</span> Popołudnie &nbsp;
            <span style='color:#333'>■ N</span> Noc &nbsp;
            <span style='color:#c00000'>■ W/U/CH</span> Wolne/Urlop/L4 &nbsp;
            <span style='background:#FFCDD2; padding:0 4px'>Nd/Święto</span> &nbsp;
            <span style='background:#DCEDC8; padding:0 4px'>Sobota</span> &nbsp;
            <span style='background:#FFFDE7; padding:0 4px'>⬅ Twój wiersz</span>
            </div>
            """, unsafe_allow_html=True)

            # Moje podsumowanie
            st.divider()
            st.subheader(f"📋 Moje podsumowanie — {month_pl_names[sel_mo]} {sel_yr}")
            r_c = sum(1 for s in my_shifts.values() if s == 'R')
            p_c = sum(1 for s in my_shifts.values() if s == 'P')
            n_c = sum(1 for s in my_shifts.values() if s == 'N')
            u_c = sum(1 for s in my_shifts.values() if s == 'U')
            ch_c = sum(1 for s in my_shifts.values() if s == 'CH')
            we_c = sum(1 for d, s in my_shifts.items()
                       if s in ['R','P','N'] and
                       (date(sel_yr, sel_mo, d).weekday() >= 5 or date(sel_yr, sel_mo, d) in pl_holidays))
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
            mc1.metric("🌞 Rano", r_c)
            mc2.metric("🌇 Popołudnie", p_c)
            mc3.metric("🌙 Noc", n_c)
            mc4.metric("🏖️ Weekendy", we_c)
            mc5.metric("✈️ Urlop", u_c)
            mc6.metric("🤒 L4", ch_c)

elif menu == "Moje Preferencje":
    st.header("🗓️ Moje Preferencje do Grafiku")
    st.write("Wpisz swoje potrzeby na nadchodzący miesiąc. Administrator uwzględni je przy generowaniu grafiku.")

    my_emp = db.get_employee_for_user(st.session_state['username'])
    if not my_emp:
        st.warning("⚠️ Twoje konto nie jest powiązane z żadnym pracownikiem. Skontaktuj się z administratorem.")
        st.stop()

    emp_id, emp_name, emp_loc_id, _, _ = my_emp
    st.info(f"👤 Pracownik: **{emp_name}**")

    today = date.today()
    pref_col1, pref_col2 = st.columns(2)
    with pref_col1:
        pref_yr = st.number_input("Rok", 2020, 2030,
                                   today.year if today.month == 12 else today.year,
                                   key="pref_yr")
    with pref_col2:
        next_mo = today.month % 12 + 1
        pref_mo = st.number_input("Miesiąc", 1, 12, next_mo, key="pref_mo")

    pl_holidays_p = holidays.Poland(years=pref_yr)
    num_days_p = calendar.monthrange(pref_yr, pref_mo)[1]

    # Wczytaj zapisane preferencje
    saved_pref = db.get_my_unavailabilities(emp_id, pref_yr, pref_mo)

    month_names_p = ["","Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                     "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]
    st.subheader(f"Preferencje na {month_names_p[pref_mo]} {pref_yr}")

    pref_options = ['', 'W', 'U', 'CH', 'R', 'P', 'N', 'NR', 'NP', 'NN']
    pref_help = {
        'W': 'Wolne', 'U': 'Urlop', 'CH': 'L4 / Choroba',
        'R': 'Chcę zmianę Rano', 'P': 'Chcę zmianę Popołudniową', 'N': 'Chcę zmianę Nocną',
        'NR': 'Nie chcę Rano', 'NP': 'Nie chcę Popołudniowej', 'NN': 'Nie chcę Nocnej'
    }

    # Tabela preferencji
    pref_df = {}
    for d in range(1, num_days_p + 1):
        pref_df[str(d)] = saved_pref.get(d, '')

    pref_col_cfg = {}
    for d in range(1, num_days_p + 1):
        d_s = str(d)
        dt = date(pref_yr, pref_mo, d)
        if dt.weekday() == 6 or dt in pl_holidays_p:
            label = f"🔴 {d_s}"
        elif dt.weekday() == 5:
            label = f"🟢 {d_s}"
        else:
            label = d_s
        pref_col_cfg[d_s] = st.column_config.SelectboxColumn(
            label=label, options=pref_options, width="small", required=False
        )

    import pandas as pd
    pref_df_obj = pd.DataFrame([pref_df], index=[emp_name])
    edited_pref = st.data_editor(
        pref_df_obj,
        column_config=pref_col_cfg,
        use_container_width=True,
        key=f"pref_editor_{pref_yr}_{pref_mo}"
    )

    # Pomoc
    st.markdown("**Legenda opcji:** " + " | ".join([f"`{k}` = {v}" for k, v in pref_help.items()]))

    if st.button("💾 Zapisz moje preferencje", type="primary"):
        row_data = edited_pref.iloc[0].to_dict()
        data_to_save = {int(d): v for d, v in row_data.items() if v and str(v).strip()}
        db.save_my_unavailabilities(emp_id, emp_loc_id, pref_yr, pref_mo, data_to_save)
        st.success(f"✅ Preferencje na {month_names_p[pref_mo]} {pref_yr} zostały zapisane!")
        st.info("🔔 Administrator zobaczy Twoje preferencje przy generowaniu grafiku.")

elif menu == "Moje Statystyki":
    st.header("📊 Moje Statystyki")

    my_emp_s = db.get_employee_for_user(st.session_state['username'])
    if not my_emp_s:
        st.warning("⚠️ Twoje konto nie jest powiązane z żadnym pracownikiem. Skontaktuj się z administratorem.")
        st.stop()

    emp_id_s, emp_name_s, emp_loc_id_s, _, _ = my_emp_s
    st.info(f"👤 Pracownik: **{emp_name_s}**")

    today_s = date.today()
    if 'my_stats_yr_from' not in st.session_state:
        st.session_state['my_stats_yr_from'] = today_s.year
        st.session_state['my_stats_mo_from'] = 1
        st.session_state['my_stats_yr_to'] = today_s.year
        st.session_state['my_stats_mo_to'] = today_s.month

    # Presety
    ms1, ms2, ms3 = st.columns(3)
    if ms1.button("Ten rok", use_container_width=True):
        st.session_state.update({'my_stats_yr_from': today_s.year, 'my_stats_mo_from': 1,
                                  'my_stats_yr_to': today_s.year, 'my_stats_mo_to': today_s.month})
        st.rerun()
    if ms2.button("Poprzedni rok", use_container_width=True):
        st.session_state.update({'my_stats_yr_from': today_s.year-1, 'my_stats_mo_from': 1,
                                  'my_stats_yr_to': today_s.year-1, 'my_stats_mo_to': 12})
        st.rerun()
    if ms3.button("Ostatnie 3 miesiące", use_container_width=True):
        from_m = (today_s.month - 3) or 12
        from_y = today_s.year if today_s.month > 3 else today_s.year - 1
        st.session_state.update({'my_stats_yr_from': from_y, 'my_stats_mo_from': from_m,
                                  'my_stats_yr_to': today_s.year, 'my_stats_mo_to': today_s.month})
        st.rerun()

    sc1, sc2 = st.columns(2)
    with sc1:
        sa1, sa2 = st.columns(2)
        syr_f = sa1.number_input("Rok od", 2020, 2030, st.session_state['my_stats_yr_from'], key="my_syr_f")
        smo_f = sa2.number_input("Mies. od", 1, 12, st.session_state['my_stats_mo_from'], key="my_smo_f")
    with sc2:
        sb1, sb2 = st.columns(2)
        syr_t = sb1.number_input("Rok do", 2020, 2030, st.session_state['my_stats_yr_to'], key="my_syr_t")
        smo_t = sb2.number_input("Mies. do", 1, 12, st.session_state['my_stats_mo_to'], key="my_smo_t")

    st.session_state.update({'my_stats_yr_from': syr_f, 'my_stats_mo_from': smo_f,
                              'my_stats_yr_to': syr_t, 'my_stats_mo_to': smo_t})

    all_stats = db.get_stats_for_range(emp_loc_id_s, syr_f, smo_f, syr_t, smo_t)
    my_stats = all_stats.get(emp_name_s)

    if my_stats:
        month_abbr_s = ["","Sty","Lut","Mar","Kwi","Maj","Cze","Lip","Sie","Wrz","Paź","Lis","Gru"]
        range_s = f"{month_abbr_s[smo_f]} {syr_f} — {month_abbr_s[smo_t]} {syr_t}"
        st.success(f"📋 Statystyki za period: **{range_s}**")

        sm1,sm2,sm3,sm4,sm5,sm6,sm7,sm8 = st.columns(8)
        sm1.metric("🌞 Rano", my_stats['R'])
        sm2.metric("🌇 Popoł.", my_stats['P'])
        sm3.metric("🌙 Noc", my_stats['N'])
        sm4.metric("⛳ Wolne", my_stats['W'])
        sm5.metric("✈️ Urlop", my_stats['U'])
        sm6.metric("🤒 L4", my_stats['CH'])
        sm7.metric("📋 Łącznie", my_stats['S'])
        sm8.metric("🏖️ Weekendy", my_stats['WE'])

        st.divider()
        st.subheader("📈 Podział zmian")
        import pandas as pd
        chart_data = pd.DataFrame({
            'Zmiana': ['Rano (R)', 'Popołudnie (P)', 'Noc (N)', 'Wolne (W)', 'Urlop (U)', 'L4 (CH)'],
            'Ilość': [my_stats['R'], my_stats['P'], my_stats['N'],
                       my_stats['W'], my_stats['U'], my_stats['CH']]
        }).set_index('Zmiana')
        st.bar_chart(chart_data)
    else:
        st.info("Brak danych dla wybranego zakresu. Upewnij się, że grafiki są zatwierdzone (APPROVED).")

