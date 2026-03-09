import streamlit as st
import pandas as pd
from datetime import date
import calendar
import db
from scheduler import ScheduleGenerator
from exporter import export_schedule, export_schedule_pdf
import os
import holidays

st.set_page_config(page_title="Generator Grafików Pro", layout="wide", initial_sidebar_state="expanded")

# --- Authentication ---
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
    st.session_state['user_role'] = None
    st.session_state['username'] = None

def login():
    st.title("🔒 Logowanie do Systemu")
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

# --- Main App ---

# Initializing DB (Supabase)
db.init_db()

st.sidebar.title(f"Witaj, {st.session_state['username']}")
if st.sidebar.button("Wyloguj"):
    st.session_state['authenticated'] = False
    st.rerun()

st.title("📅 Generator Grafików Pracy Online")

# Wybór obiektu
locations = db.get_locations()
loc_dict = {name: id for id, name in locations}
selected_loc_name = st.sidebar.selectbox("Wybierz Obiekt", list(loc_dict.keys()))
location_id = loc_dict[selected_loc_name]

st.sidebar.divider()

menu_options = ["Generowanie Grafiku", "Niedostępności (Urlopy/L4)", "Statystyki"]
if st.session_state['user_role'] == 'admin':
    menu_options += ["Zatwierdzanie Grafików", "Pracownicy"]

menu = st.sidebar.radio("Nawigacja", menu_options)

if menu == "Generowanie Grafiku":
    st.header(f"Generuj nowy grafik: {selected_loc_name}")
    
    col1, col2 = st.columns(2)
    with col1:
        rok = st.number_input("Rok", min_value=2020, max_value=2030, value=date.today().year)
    with col2:
        miesiac = st.number_input("Miesiąc", min_value=1, max_value=12, value=date.today().month)
        
    emps_master = db.get_employees(location_id)
    if not emps_master:
        st.warning(f"Najpierw dodaj pracowników dla obiektu '{selected_loc_name}'!")
    else:
        st.subheader("Wybierz pracowników do grafiku")
        df_emps = pd.DataFrame([{"Imię i Nazwisko": name, "Uwzględnij": True} for _, name in emps_master])
        edited_emps = st.data_editor(df_emps, hide_index=True)
        included_names = edited_emps[edited_emps["Uwzględnij"] == True]["Imię i Nazwisko"].tolist()
        
        if st.button("Uruchom Generator", type="primary"):
            with st.spinner("Przeliczanie..."):
                emps = [e for e in emps_master if e[1] in included_names]
                emp_dict = {i: name for i, (emp_id, name) in enumerate(emps)}
                emp_name_to_id = {name: emp_id for emp_id, name in emps}
                unav_rows = db.get_unavailabilities(rok, miesiac, location_id)
                
                unavailabilities = {}
                for emp_id, day, typ in unav_rows:
                    matches = [i for i, v in emp_dict.items() if emp_name_to_id[v] == emp_id]
                    if matches:
                        idx = matches[0]
                        if idx not in unavailabilities: unavailabilities[idx] = {}
                        unavailabilities[idx][day] = typ
                
                generator = ScheduleGenerator(rok, miesiac, [emp_dict[i] for i in range(len(emps))], unavailabilities, location_name=selected_loc_name)
                wynik = generator.solve()
                
                if wynik:
                    status = "DRAFT" if st.session_state['user_role'] != 'admin' else "APPROVED"
                    db.save_schedule(wynik, rok, miesiac, emp_name_to_id, location_id, status=status, user=st.session_state['username'])
                    st.success(f"Grafik zapisany jako {status}!")
                else:
                    st.error("Brak rozwiązania.")

elif menu == "Zatwierdzanie Grafików" and st.session_state['user_role'] == 'admin':
    st.header("Grafiki oczekujące na zatwierdzenie")
    # To be implemented: list schedules with status 'DRAFT' and allow approval
    st.info("Ta sekcja pozwoli na przeglądanie i zatwierdzanie wersji roboczych.")

elif menu == "Niedostępności (Urlopy/L4)":
    # (Existing logic from preview app.py for Unavailabilities, assuming similar structure)
    st.header("Zarządzaj nieobecnościami")
    colX, colY = st.columns(2)
    view_rok = colX.number_input("Rok", 2020, 2030, date.today().year)
    view_msc = colY.number_input("Miesiąc", 1, 12, date.today().month)
    
    emps = db.get_employees(location_id)
    if emps:
        emp_names = {name: id for id, name in emps}
        reverse_emps = {id: name for id, name in emps}
        unav = db.get_unavailabilities(view_rok, view_msc, location_id)
        num_days = calendar.monthrange(view_rok, view_msc)[1]
        
        df_matrix = pd.DataFrame(index=[name for _, name in emps], columns=[str(d) for d in range(1, num_days+1)])
        for eid, d, t in unav:
            if eid in reverse_emps: df_matrix.at[reverse_emps[eid], str(d)] = t
            
        edited_df = st.data_editor(df_matrix)
        if st.button("Zapisz Nieobecności"):
            data_list = []
            for emp_name, row in edited_df.iterrows():
                eid = emp_names[emp_name]
                for d_str, val in row.items():
                    if pd.notna(val) and str(val).strip():
                        data_list.append((eid, int(d_str), str(val).upper()))
            db.update_unavailabilities_for_month(view_rok, view_msc, data_list, location_id)
            st.success("Zapisano!")

elif menu == "Statystyki":
    st.header("Statystyki (tylko zatwierdzone grafiki)")
    stats = db.get_all_stats(location_id)
    st.dataframe(pd.DataFrame.from_dict(stats, orient='index').fillna(0).astype(int))

elif menu == "Pracownicy" and st.session_state['user_role'] == 'admin':
    st.header("Zarządzanie Pracownikami")
    imie = st.text_input("Imię i Nazwisko")
    if st.button("Dodaj Pracownika"):
        db.add_employee(imie, location_id)
        st.success("Dodano!")
        st.rerun()
    
    st.divider()
    emps = db.get_employees(location_id)
    for eid, name in emps:
        c1, c2 = st.columns([5,1])
        c1.write(name)
        if c2.button("Usuń", key=f"del_{eid}"):
            db.remove_employee(eid)
            st.rerun()
