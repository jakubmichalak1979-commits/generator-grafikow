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

st.set_page_config(page_title="Generator Grafików Pro", layout="wide", initial_sidebar_state="expanded")

# --- Initialize Database ---
try:
    db.init_db()
except Exception as e:
    st.error(f"⚠️ Błąd połączenia z bazą danych! Sprawdź ustawienia 'Secrets' na Streamlit Cloud.")
    st.info("Prawdopodobnie musisz użyć linku 'Pooler' z Supabase (port 6543) zamiast bezpośredniego połączenia.")
    st.stop()

# --- Authentication ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['username'] = None

def login():
    st.title("🔒 Logowanie do Systemu")
    col1, col2 = st.columns([1, 1])
    with col1:
        with st.form("login_form"):
            username = st.text_input("Użytkownik")
            password = st.text_input("Hasło", type="password")
            submit = st.form_submit_button("Zaloguj")
            if submit:
                user = db.verify_user(username, password)
                if user:
                    st.session_state['authenticated'] = True
                    st.session_state['user_role'] = user.role
                    st.session_state['username'] = user.username
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
                emp_dict = {i: name for i, (eid, name, email) in enumerate(emps)}
                emp_name_to_id = {name: eid for eid, name, email in emps}
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
                    status = "DRAFT" if st.session_state['user_role'] != 'admin' else "APPROVED"
                    db.save_schedule(wynik, rok, miesiac, emp_name_to_id, location_id, status=status, user=st.session_state['username'])
                    st.success(f"Grafik zapisany jako **{status}**!")
                    
                    # Manual export option
                    fname_x = f"grafik_{miesiac}_{rok}.xlsx"
                    fname_p = f"grafik_{miesiac}_{rok}.pdf"
                    export_schedule(wynik, rok, miesiac, fname_x)
                    export_schedule_pdf(wynik, rok, miesiac, fname_p)
                    
                    st.write("Pobierz:")
                    c1, c2 = st.columns(2)
                    with open(fname_x, "rb") as f: c1.download_button("Excel", f, fname_x)
                    with open(fname_p, "rb") as f: c2.download_button("PDF", f, fname_p)
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
            
        edited = st.data_editor(df, use_container_width=True)
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
