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
    creds = cookie_manager.get("remember_creds")
    if creds and "|" in creds and not st.session_state['authenticated']:
        saved_user, saved_pass = creds.split("|", 1)
        user = db.verify_user(saved_user, saved_pass)
        if user:
            st.session_state['authenticated'] = True
            st.session_state['user_role'] = user.role
            st.session_state['username'] = user.username
            return True
    return False

# --- Authentication ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['username'] = None

# Auto-login check
if not st.session_state['authenticated']:
    check_cookies()

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

import os

# --- Main App ---

st.sidebar.title(f"Witaj, {st.session_state['username']}")
if st.sidebar.button("Wyloguj"):
    st.session_state['authenticated'] = False
    cookie_manager.delete("remember_creds")
    st.rerun()

st.title("📅 Generator Grafików Pracy Online")

locations = db.get_locations()
loc_dict = {name: id for id, name in locations}
selected_loc_name = st.sidebar.selectbox("Wybierz Obiekt", list(loc_dict.keys()))
location_id = loc_dict[selected_loc_name]

st.sidebar.divider()

menu_options = ["Generowanie Grafiku", "Niedostępności (Urlopy/L4)", "Statystyki"]
if st.session_state['user_role'] == 'admin':
    menu_options += ["Zatwierdzanie i Archiwum", "Pracownicy", "Zarządzanie Kontami"]

menu = st.sidebar.radio("Nawigacja", menu_options)

if menu == "Generowanie Grafiku":
    st.header(f"Generuj nowy grafik: {selected_loc_name}")
    col1, col2 = st.columns(2)
    rok = col1.number_input("Rok", 2020, 2030, date.today().year)
    miesiac = col2.number_input("Miesiąc", 1, 12, date.today().month)
        
    emps_master = db.get_employees(location_id)
    if not emps_master:
        st.warning("Dodaj pracowników!")
    else:
        st.subheader("Wybierz pracowników")
        df_emps = pd.DataFrame([{"Imię i Nazwisko": e[1], "Uwzględnij": True} for e in emps_master])
        edited_emps = st.data_editor(df_emps, hide_index=True)
        included_names = edited_emps[edited_emps["Uwzględnij"] == True]["Imię i Nazwisko"].tolist()
        
        if st.button("Uruchom Generator", type="primary"):
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
                    st.success("Wygenerowano propozycję grafiku!")
                    
                    # Konwersja na DataFrame (wymuszamy stringi jako nazwy kolumn dla stabilności)
                    days_list = sorted(list(wynik[list(wynik.keys())[0]].keys()))
                    days_list_str = [str(d) for d in days_list]
                    df_wynik = pd.DataFrame.from_dict(wynik, orient='index', columns=days_list_str)
                    
                    # --- Obliczenie Statystyk (Podsumowanie na prawo) ---
                    pl_holidays = holidays.Poland(years=rok)
                    
                    praca_list = []
                    wolne_list = []
                    absencja_list = []
                    we_list = []
                    
                    for name, row in df_wynik.iterrows():
                        row_list = row.tolist()
                        praca_list.append(sum(1 for x in row_list if x in ['R', 'P', 'N']))
                        wolne_list.append(sum(1 for x in row_list if x == 'W'))
                        absencja_list.append(sum(1 for x in row_list if x in ['U', 'CH']))
                        
                        we_count = 0
                        for i, shift in enumerate(row_list):
                            day = days_list[i]
                            dt = date(rok, miesiac, day)
                            if (dt.weekday() >= 5 or dt in pl_holidays) and shift in ['R', 'P', 'N']:
                                we_count += 1
                        we_list.append(we_count)
                    
                    # Dodanie kolumn podsumowania do DataFrame
                    df_wynik["SUMA: Praca"] = praca_list
                    df_wynik["SUMA: Wolne"] = wolne_list
                    df_wynik["SUMA: U/CH"] = absencja_list
                    df_wynik["SUMA: WE/ŚW"] = we_list

                    st.subheader("Edycja i weryfikacja grafiku")
                    
                    # --- Kolorowy Podgląd (Informacyjny) ---
                    def highlight_days_gen(row):
                        styles = []
                        for col in row.index:
                            try:
                                d_int = int(col)
                                dt = date(rok, miesiac, d_int)
                                if dt.weekday() == 6 or dt in pl_holidays:
                                    styles.append('background-color: #ffb3b3') # Czerwony
                                elif dt.weekday() == 5:
                                    styles.append('background-color: #b3ffb3') # Zielony
                                else: styles.append('')
                            except: styles.append('') # Kolumny tekstowe (statystyki)
                        return styles

                    st.write("💡 **Legenda kolorów (tylko podgląd):** Zielony = Sobota, Czerwony = Niedziela/Święto")
                    st.dataframe(df_wynik[days_list_str].style.apply(highlight_days_gen, axis=1), use_container_width=True)

                    # --- Edytor z Podsumowaniem po prawej ---
                    shift_options = ['R', 'P', 'N', 'W', 'U', 'CH']
                    col_config = {
                        d_s: st.column_config.SelectboxColumn(d_s, options=shift_options, width="small") 
                        for d_s in days_list_str
                    }
                    # Blokujemy edycję kolumn podsumowania
                    for col in ["SUMA: Praca", "SUMA: Wolne", "SUMA: U/CH", "SUMA: WE/ŚW"]:
                        col_config[col] = st.column_config.Column(col, disabled=True, width="small")
                    
                    edited_df = st.data_editor(df_wynik, column_config=col_config, key="schedule_editor", use_container_width=True)
                    
                    # --- Walidacja Kodeksu Pracy ---
                    warnings = []
                    for name, row in edited_df[days_list_str].iterrows():
                        row_list = row.tolist()
                        for i in range(len(row_list) - 1):
                            curr = row_list[i]
                            nxt = row_list[i+1]
                            if (curr == 'P' and nxt == 'R') or (curr == 'N' and nxt == 'R') or (curr == 'N' and nxt == 'P'):
                                warnings.append(f"⚠️ **{name}**: Brak 11h odpoczynku między dniem {i+1} a {i+2} ({curr} -> {nxt})")
                        
                        work_streak = 0
                        for i, shift in enumerate(row_list):
                            if shift in ['R', 'P', 'N']:
                                work_streak += 1
                                if work_streak > 6:
                                    warnings.append(f"⚠️ **{name}**: Ponad 6 dni pracy z rzędu (dzień {i+1})")
                            else: work_streak = 0

                    if warnings:
                        for w in warnings: st.warning(w)
                    else: st.success("✅ Grafik zgodny z podstawowymi zasadami odpoczynku.")

                    # Przyciski akcji
                    c1, c2 = st.columns(2)
                    if c1.button("Zapisz jako Roboczy (DRAFT)"):
                        new_wynik = edited_df[days_list_str].to_dict(orient='index')
                        # Zamieniamy klucze z powrotem na inty dla bazy danych
                        new_wynik_int = {name: {int(d): v for d, v in days.items()} for name, days in new_wynik.items()}
                        db.save_schedule(new_wynik_int, rok, miesiac, emp_name_to_id, location_id, status="DRAFT", user=st.session_state['username'])
                        st.success("Grafik zapisany jako Roboczy!")

                    if st.session_state['user_role'] == 'admin':
                        if c2.button("Zatwierdź Grafik (APPROVED)", type="primary"):
                            new_wynik = edited_df[days_list_str].to_dict(orient='index')
                            new_wynik_int = {name: {int(d): v for d, v in days.items()} for name, days in new_wynik.items()}
                            db.save_schedule(new_wynik_int, rok, miesiac, emp_name_to_id, location_id, status="APPROVED", user=st.session_state['username'])
                            st.success("GRAFIK ZATWIERDZONY!")
                            
                            fname_x = f"grafik_{miesiac}_{rok}.xlsx"
                            fname_p = f"grafik_{miesiac}_{rok}.pdf"
                            export_schedule(new_wynik_int, rok, miesiac, fname_x)
                            export_schedule_pdf(new_wynik_int, rok, miesiac, fname_p)
                            st.write("Pobierz gotowe pliki:")
                            ca, cb = st.columns(2)
                            with open(fname_x, "rb") as f: ca.download_button("Excel", f, fname_x)
                            with open(fname_p, "rb") as f: cb.download_button("PDF", f, fname_p)
                else:
                    st.error("Brak rozwiązania spełniającego zasady.")

elif menu == "Zatwierdzanie i Archiwum" and st.session_state['user_role'] == 'admin':
    st.header("Zarządzanie grafikami")
    colA, colB = st.columns(2)
    r = colA.number_input("Rok", 2020, 2030, date.today().year, key="arc_r")
    m = colB.number_input("Miesiąc", 1, 12, date.today().month, key="arc_m")
    
    # This section would normally show 'DRAFT' schedules and allow approval
    st.info("Tutaj będziesz mógł zatwierdzać propozycje grafików od użytkowników.")
    if st.button("Pokaż grafik (Zatwierdzony)"):
        # Placeholder for viewing approved schedule
        st.write("Podgląd archiwum...")

elif menu == "Niedostępności (Urlopy/L4)":
    st.header("Grafik nieobecności")
    colX, colY = st.columns(2)
    vr = colX.number_input("Rok", 2020, 2030, date.today().year, key="unav_r")
    vm = colY.number_input("Miesiąc", 1, 12, date.today().month, key="unav_m")
    
    emps = db.get_employees(location_id)
    if emps:
        emp_names = {e[1]: e[0] for e in emps}
        reverse_emps = {e[0]: e[1] for e in emps}
        unav = db.get_unavailabilities(vr, vm, location_id)
        num_days = calendar.monthrange(vr, vm)[1]
        
        df = pd.DataFrame(index=[e[1] for e in emps], columns=[str(d) for d in range(1, num_days+1)])
        for eid, d, t in unav:
            if eid in reverse_emps: df.at[reverse_emps[eid], str(d)] = t
        # --- Kolorowanie i Skonfigurowanie Wyboru ---
        pl_holidays = holidays.Poland(years=vr)
        
        def highlight_days(row):
            styles = []
            for col in row.index:
                try:
                    d_int = int(col)
                    dt = date(vr, vm, d_int)
                    if dt.weekday() == 6 or dt in pl_holidays: # Niedziela / Święto
                        styles.append('background-color: #ffccce') # Jasnoczerwony
                    elif dt.weekday() == 5: # Sobota
                        styles.append('background-color: #ccffcc') # Jasnozielony
                    else:
                        styles.append('')
                except:
                    styles.append('')
            return styles

        st.write("**Podgląd dni (kolory - Soboty: zielony, Niedziele/Święta: czerwony):**")
        st.dataframe(df.style.apply(highlight_days, axis=1), use_container_width=True)

        # Definicja dropdownów dla każdego dnia
        day_config = {
            str(d): st.column_config.SelectboxColumn(
                label=str(d),
                width="small",
                options=['', 'W', 'U', 'CH', 'R', 'P', 'N', 'NR', 'NP', 'NN', 'TR', 'TP', 'TN'],
                required=False
            ) for d in range(1, num_days + 1)
        }
        
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
        df_order = pd.DataFrame([{"ID": e[0], "Imię i Nazwisko": e[1], "Kolejność": e[3]} for e in emps_data])
        edited_order = st.data_editor(df_order, hide_index=True, disabled=["ID", "Imię i Nazwisko"])
        
        if st.button("Zapisz nową kolejność"):
            for _, row in edited_order.iterrows():
                db.update_employee_order(row["ID"], row["Kolejność"])
            st.success("Kolejność została zapisana!")
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
