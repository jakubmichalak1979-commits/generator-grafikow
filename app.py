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
    st.error(f"⚠️ Błąd połączenia z bazą danych! Sprawdź ustawienia 'Secrets' na Streamlit Cloud.")
    st.info("Prawdopodobnie musisz użyć linku 'Pooler' z Supabase (port 6543) zamiast bezpośredniego połączenia.")
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
    components.html("<script>window.print()</script>", height=0)

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

menu_options = ["Generowanie Grafiku", "Niedostępności (Urlopy/L4)", "Statystyki"]
if st.session_state['user_role'] == 'admin':
    menu_options += ["Zatwierdzanie i Archiwum", "Pracownicy", "Zarządzanie Kontami"]

menu = st.sidebar.radio("Nawigacja", menu_options)

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
            st.markdown('<div class="print-only">', unsafe_allow_html=True)
            month_pl_names = ["", "STYCZEŃ", "LUTY", "MARZEC", "KWIECIEŃ", "MAJ", "CZERWIEC", 
                              "LIPIEC", "SIERPIEŃ", "WRZESIEŃ", "PAŹDZIERNIK", "LISTOPAD", "GRUDZIEŃ"]
            st.write(f"### GRAFIK - OBIEKT {selected_loc_name.upper()}")
            st.write(f"### MIESIĄC {month_pl_names[miesiac]} ROK {rok}")
            # Include summary columns in print
            sum_cols = ["R", "P", "N", "W", "U", "CH", "S", "WE"]
            st.table(df_wynik[days_list_str + sum_cols])
            st.markdown('</div>', unsafe_allow_html=True)

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
    st.header("Zarządzanie grafikami")
    
    # --- PRZEGLĄD WSZYSTKICH DRAFTÓW ---
    st.subheader("❗ Grafiki czekające na zatwierdzenie (Wszystkie Obiekty)")
    all_drafts = db.get_all_schedules_with_status("DRAFT")
    if all_drafts:
        for yr, mo, loc_id, loc_name in all_drafts:
            c1, c2 = st.columns([3, 1])
            c1.info(f"📅 **{loc_name}** - Miesiąc: {mo}/{yr}")
            if c2.button(f"Wczytaj do edycji", key=f"ar_load_{yr}_{mo}_{loc_id}"):
                st.session_state['selected_location_name'] = loc_name
                st.session_state['selected_year'] = yr
                st.session_state['selected_month'] = mo
                st.session_state['active_schedule'] = db.get_schedule(yr, mo, loc_id, status="DRAFT")
                st.session_state['schedule_status'] = "DRAFT"
                st.rerun()
    else:
        st.success("Brak oczekujących draftów.")

    st.divider()
    st.subheader("🔍 Przeglądaj Archiwum / Wybrany okres")
    colA, colB = st.columns(2)
    r_ar = colA.number_input("Rok", 2020, 2030, st.session_state.get('selected_year', date.today().year), key="ar_r")
    m_ar = colB.number_input("Miesiąc", 1, 12, st.session_state.get('selected_month', date.today().month), key="ar_m")
    
    draft = db.get_schedule(r_ar, m_ar, location_id, status="DRAFT")
    approved = db.get_schedule(r_ar, m_ar, location_id, status="APPROVED")
    
    if draft:
        st.subheader("📝 Grafik Roboczy (DRAFT) dla obecnego obiektu")
        st.info("Ten grafik czeka na weryfikację.")
        if st.button("Pobierz Draft do edycji w generatorze"):
            st.session_state['active_schedule'] = draft
            st.session_state['schedule_status'] = "DRAFT"
            st.session_state['selected_year'] = r_ar
            st.session_state['selected_month'] = m_ar
            st.success("Wczytano! Przejdź teraz do zakładki 'Generowanie Grafiku'.")

    if approved:
        st.subheader("✅ Grafik Zatwierdzony (Archiwum) dla obecnego obiektu")
        
        # Display the approved schedule in a nice table
        pl_holidays = holidays.Poland(years=r_ar)
        days_in_month = calendar.monthrange(r_ar, m_ar)[1]
        days_list_str = [str(d) for d in range(1, days_in_month + 1)]
        
        # Fix keys and create DF
        approved_fixed = {name: {str(d): v for d, v in days.items()} for name, days in approved.items()}
        df_app = pd.DataFrame.from_dict(approved_fixed, orient='index', columns=days_list_str)
        
        st.dataframe(df_app, use_container_width=True)

        # --- STATIC PRINT TABLE (Hidden on Screen) ---
        st.markdown('<div class="print-only">', unsafe_allow_html=True)
        month_pl_names = ["", "STYCZEŃ", "LUTY", "MARZEC", "KWIECIEŃ", "MAJ", "CZERWIEC", 
                          "LIPIEC", "SIERPIEŃ", "WRZESIEŃ", "PAŹDZIERNIK", "LISTOPAD", "GRUDZIEŃ"]
        st.write(f"### ZATWIERDZONY GRAFIK - OBIEKT {selected_loc_name.upper()}")
        st.write(f"### MIESIĄC {month_pl_names[m_ar]} ROK {r_ar}")
        st.table(df_app)
        st.markdown('</div>', unsafe_allow_html=True)

        ca, cb, cc = st.columns(3)
        if ca.button("🖨️ Drukuj Approved", use_container_width=True):
            trigger_print()
            
        f1, f2 = f"archiwum_{m_ar}_{r_ar}.xlsx", f"archiwum_{m_ar}_{r_ar}.pdf"
        export_schedule(approved, r_ar, m_ar, f1, location_name=selected_loc_name)
        export_schedule_pdf(approved, r_ar, m_ar, f2, location_name=selected_loc_name)
        with open(f1, "rb") as f: cb.download_button("Pobierz Excel", f, f1, use_container_width=True)
        with open(f2, "rb") as f: cc.download_button("Pobierz PDF", f, f2, use_container_width=True)
    
    if not draft and not approved:
        st.info(f"Brak zapisanych grafików dla obiektu {selected_loc_name} w okresie {m_ar}/{r_ar}.")

elif menu == "Niedostępności (Urlopy/L4)":
    st.header("Grafik nieobecności")
    colX, colY = st.columns(2)
    vr = colX.number_input("Rok", 2020, 2030, date.today().year, key="unav_r")
    vm = colY.number_input("Miesiąc", 1, 12, date.today().month, key="unav_m")
    
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
    st.header("Podsumowanie przydziałów")
    stats = db.get_all_stats(location_id)
    if stats:
        st.dataframe(pd.DataFrame.from_dict(stats, orient='index').fillna(0).astype(int))
    else:
        st.write("Brak zatwierdzonych grafików w bazie.")

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
    users = db.get_users()
    for uid, uname, urole in users:
        colA, colB, colC = st.columns([2, 2, 1])
        colA.write(f"**{uname}**")
        colB.write(f"Rola: `{urole}`")
        if uname != 'admin': # Zabezpieczenie przed usunięciem głównego admina
            if colC.button("Usuń", key=f"user_{uid}"):
                db.remove_user(uid)
                st.rerun()
        else:
            colC.write("🔒")
