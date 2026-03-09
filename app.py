import streamlit as st
import pandas as pd
from datetime import date
import calendar
import db
from scheduler import ScheduleGenerator
from exporter import export_schedule, export_schedule_pdf
import os
import holidays

st.set_page_config(page_title="Generator Grafików", layout="wide", initial_sidebar_state="expanded")

# Inicjalizacja bazy
db.init_db()

st.title("📅 Generator Grafików Pracy")

# Wybór obiektu
locations = db.get_locations()
loc_dict = {name: id for id, name in locations}
selected_loc_name = st.sidebar.selectbox("Wybierz Obiekt", list(loc_dict.keys()))
location_id = loc_dict[selected_loc_name]

st.sidebar.divider()
menu = st.sidebar.radio("Nawigacja", ["Generowanie Grafiku", "Niedostępności (Urlopy/L4)", "Statystyki", "Pracownicy"])

if menu == "Generowanie Grafiku":
    st.header(f"Generuj nowy grafik: {selected_loc_name}")
    
    col1, col2 = st.columns(2)
    with col1:
        rok = st.number_input("Rok", min_value=2020, max_value=2030, value=date.today().year)
    with col2:
        miesiac = st.number_input("Miesiąc", min_value=1, max_value=12, value=date.today().month)
        
    emps_master = db.get_employees(location_id)
    if not emps_master:
        st.warning(f"Najpierw dodaj pracowników dla obiektu '{selected_loc_name}' w zakładce 'Pracownicy'!")
    else:
        st.subheader("Wybierz pracowników do grafiku")
        
        df_emps = pd.DataFrame([{"Imię i Nazwisko": name, "Uwzględnij w tym miesiącu": True} for _, name in emps_master])
        edited_emps = st.data_editor(
            df_emps,
            column_config={
                "Uwzględnij w tym miesiącu": st.column_config.CheckboxColumn("Uwzględnij w tym miesiącu", default=True)
            },
            disabled=["Imię i Nazwisko"],
            hide_index=True,
            key="emp_selector"
        )
        
        included_names = edited_emps[edited_emps["Uwzględnij w tym miesiącu"] == True]["Imię i Nazwisko"].tolist()
        
        if st.button("Uruchom Generator", type="primary"):
            if not included_names:
                st.error("Musisz zaznaczyć przynajmniej jednego pracownika!")
            else:
                with st.spinner("Przeliczanie grafików (szukanie rozwiązań przez solver)..."):
                    emps = [e for e in emps_master if e[1] in included_names]
                    emp_dict = {i: name for i, (emp_id, name) in enumerate(emps)}
                    emp_name_to_id = {name: emp_id for emp_id, name in emps}
            
            unav_rows = db.get_unavailabilities(rok, miesiac, location_id)
            
            # formatowanie do solvera
            unavailabilities = {}
            for row in unav_rows:
                emp_id, day, typ = row
                # Znajdź lokalny indeks pracownika w emp_dict
                idx = [i for i, v in emp_dict.items() if emp_name_to_id[v] == emp_id][0]
                
                if idx not in unavailabilities:
                    unavailabilities[idx] = {}
                unavailabilities[idx][day] = typ
            
            generator = ScheduleGenerator(rok, miesiac, [emp_dict[i] for i in range(len(emps))], unavailabilities, location_name=selected_loc_name)
            wynik = generator.solve()
            
            if wynik:
                st.success("Grafik wygenerowany pomyślnie!")
                db.save_schedule(wynik, rok, miesiac, emp_name_to_id, location_id)
                
                # Zapis do plików
                filepath_xlsx = f"grafik_{miesiac}_{rok}.xlsx"
                filepath_pdf = f"grafik_{miesiac}_{rok}.pdf"
                
                export_schedule(wynik, rok, miesiac, filepath_xlsx)
                export_schedule_pdf(wynik, rok, miesiac, filepath_pdf)
                
                st.write("Pobierz wygenerowany grafik:")
                d_col1, d_col2 = st.columns(2)
                
                with d_col1:
                    with open(filepath_xlsx, "rb") as file_x:
                        st.download_button(
                            label="Pobierz plik Excel",
                            data=file_x,
                            file_name=filepath_xlsx,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                with d_col2:
                    with open(filepath_pdf, "rb") as file_p:
                        st.download_button(
                            label="Pobierz plik PDF",
                            data=file_p,
                            file_name=filepath_pdf,
                            mime="application/pdf",
                            use_container_width=True
                        )
                
                # Podgląd grafiku na ekranie
                num_days = calendar.monthrange(rok, miesiac)[1]
                df = pd.DataFrame.from_dict(wynik, orient='index')
                df = df.reindex(columns=range(1, num_days+1))
                
                pl_holidays = holidays.Poland(years=rok)
                
                # Obliczanie sum przepracowanych i wolnego
                work_days_list = []
                free_days_list = []
                we_work_days_list = []
                for _, row_data in df.iterrows():
                    w_d = sum(1 for v in row_data if v in ('R', 'P', 'N', 'U', 'CH'))
                    f_d = sum(1 for v in row_data if v == 'W')
                    we_w_d = 0
                    for d_col in df.columns:
                        if isinstance(d_col, int):
                            dt_curr = date(rok, miesiac, d_col)
                            if (dt_curr.weekday() >= 5 or dt_curr in pl_holidays) and row_data[d_col] in ('R', 'P', 'N'):
                                we_w_d += 1
                                
                    work_days_list.append(w_d)
                    free_days_list.append(f_d)
                    we_work_days_list.append(we_w_d)
                    
                df['Suma Dni Pracy'] = work_days_list
                df['Suma Dni Wolnych'] = free_days_list
                df['W/Ś w Pracy'] = we_work_days_list
                
                # Dodatkowe podsumowanie na dole dla poszczególnych zmian
                sum_r, sum_p, sum_n = [], [], []
                for c in df.columns:
                    if isinstance(c, int):
                        sum_r.append((df[c] == 'R').sum())
                        sum_p.append((df[c] == 'P').sum())
                        sum_n.append((df[c] == 'N').sum())
                    else:
                        sum_r.append("")
                        sum_p.append("")
                        sum_n.append("")
                        
                df.loc['📦 SUMA: Rano'] = sum_r
                df.loc['📦 SUMA: Popołudnie'] = sum_p
                df.loc['📦 SUMA: Noc'] = sum_n
                
                def highlight_col(s):
                    styles = []
                    d = s.name
                    if isinstance(d, int):
                        dt = date(rok, miesiac, d)
                        is_red = dt.weekday() == 6 or dt in pl_holidays
                        is_green = dt.weekday() == 5
                    else:
                        is_red = False
                        is_green = False
                    
                    for idx_val in s.index:
                        c = ''
                        
                        # Kolorowanie czcionek
                        cell_val = s[idx_val]
                        if idx_val == '📦 SUMA: Rano' or cell_val == 'R':
                            c += 'color: #00B050; font-weight: bold;'
                        elif idx_val == '📦 SUMA: Popołudnie' or cell_val == 'P':
                            c += 'color: #0070C0; font-weight: bold;'
                        elif idx_val == '📦 SUMA: Noc' or cell_val == 'N':
                            c += 'color: #000000; font-weight: bold;'
                        elif cell_val in ('U', 'CH', 'W'):
                            c += 'color: #FF0000; font-weight: bold;'
                            
                        # Kolorowanie tła dla weekendów/świąt
                        if is_red:
                            c += ' background-color: rgba(255, 0, 0, 0.2);'
                        elif is_green:
                            c += ' background-color: rgba(0, 255, 0, 0.2);'
                            
                        styles.append(c)
                    return styles
                
                st.dataframe(df.style.apply(highlight_col, axis=0))

            else:
                st.error("Nie udało się znaleźć rozwiązania spełniającego wszystkie wymagania prawne z podanymi urlopami. Spróbuj zmienić parametry (np. za dużo urlopów naraz w zespole).")

elif menu == "Niedostępności (Urlopy/L4)":
    st.header("Zarządzaj nieobecnościami (Edytor jak w Excelu)")
    
    colX, colY = st.columns(2)
    with colX:
        view_rok = st.number_input("Wybierz Rok", min_value=2020, max_value=2030, value=date.today().year)
    with colY:
        view_msc = st.number_input("Wybierz Miesiąc", min_value=1, max_value=12, value=date.today().month)
        
    emps = db.get_employees(location_id)
    if not emps:
        st.warning(f"Najpierw dodaj pracowników dla obiektu '{selected_loc_name}' w zakładce 'Pracownicy'!")
    else:
        emp_names = {name: id for id, name in emps}
        reverse_emps = {id: name for id, name in emps}
        
        unav = db.get_unavailabilities(view_rok, view_msc, location_id)
        
        num_days = calendar.monthrange(view_rok, view_msc)[1]
        pl_holidays = holidays.Poland(years=view_rok)
        
        col_names = []
        col_name_to_day = {}
        for d in range(1, num_days + 1):
            dt = date(view_rok, view_msc, d)
            if dt.weekday() == 6 or dt in pl_holidays:
                name = f"🔴 {d}"
            elif dt.weekday() == 5:
                name = f"🟢 {d}"
            else:
                name = str(d)
            col_names.append(name)
            col_name_to_day[name] = d
        
        # Przygotowanie pustej matrycy (dataframe)
        df_matrix = pd.DataFrame(
            index=[name for _, name in emps], 
            columns=col_names
        )
        
        # Wypełnienie aktualnymi danymi z bazy
        for emp_id, day, typ in unav:
            if emp_id in reverse_emps:
                emp_name = reverse_emps[emp_id]
                # Find the right column
                dt = date(view_rok, view_msc, day)
                if dt.weekday() == 6 or dt in pl_holidays:
                    col_name = f"🔴 {day}"
                elif dt.weekday() == 5:
                    col_name = f"🟢 {day}"
                else:
                    col_name = str(day)
                df_matrix.at[emp_name, col_name] = typ
                
        st.write("Wpisz typ nieobecności w odpowiedniej komórce (lub zostaw puste aby usunąć).")
        st.markdown("**Dostępne opcje:** `U` (Urlop), `CH` (Chorobowe), `W` (Przychylne Wolne), `NR` (Brak Rano), `NP` (Brak Popołudnia), `NN` (Brak Nocy), `TR` (Tylko Rano), `TP` (Tylko Popołudnie), `TN` (Tylko Noc).")
        
        # Konfiguracja kolumn - aby to były rozwijane listy (Dropdowns)
        config = {}
        options = ["U", "CH", "W", "NR", "NP", "NN", "TR", "TP", "TN"]
        for cn in col_names:
            config[cn] = st.column_config.SelectboxColumn(
                cn, 
                help=f"Dzień {col_name_to_day[cn]}", 
                options=options, 
                required=False
            )
            
        # Wyświetlenie interaktywnego edytora
        edited_df = st.data_editor(
            df_matrix, 
            column_config=config, 
            use_container_width=True,
            height=(len(emps) + 1) * 38
        )
        
        if st.button("💾 Zapisz zmiany w nieobecnościach", type="primary"):
            data_list = []
            for emp_name, row in edited_df.iterrows():
                emp_id = emp_names[emp_name]
                for cn in col_names:
                    val = row.get(cn)
                    if pd.notna(val) and str(val).strip() != "":
                        val_str = str(val).strip().upper()
                        if val_str in options:
                            data_list.append((emp_id, col_name_to_day[cn], val_str))
                            
            db.update_unavailabilities_for_month(view_rok, view_msc, data_list, location_id)
            st.success(f"Zapisano wszystkie zmiany dla {view_msc}-{view_rok} ({selected_loc_name})!")
            st.rerun()

elif menu == "Statystyki":
    st.header(f"Statystyki przydziałów: {selected_loc_name}")
    st.write("Sumaryczna liczba poszczególnych zmian we wszystkich historycznych grafikach:")
    stats = db.get_all_stats(location_id)
    stats_df = pd.DataFrame.from_dict(stats, orient='index').fillna(0).astype('int')
    st.dataframe(stats_df)
    
    colx, coly = st.columns(2)
    # Eksport statystyk do formatów
    with colx:
        filepath_stats_x = "statystyki.xlsx"
        stats_df.to_excel(filepath_stats_x)
        with open(filepath_stats_x, "rb") as file_sx:
            st.download_button("Pobierz Statystyki (Excel)", data=file_sx, file_name=filepath_stats_x, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
    with coly:
        # Generowanie PDF statystyk w locie
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.lib import colors as rl_colors
        
        filepath_stats_p = "statystyki.pdf"
        doc = SimpleDocTemplate(filepath_stats_p, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
        
        data = [["Imię i Nazwisko", "R", "P", "N", "W", "U", "CH"]]
        for emp, row in stats.items():
            data.append([emp, str(row.get('R', 0)), str(row.get('P', 0)), str(row.get('N', 0)), str(row.get('W', 0)), str(row.get('U', 0)), str(row.get('CH', 0))])
            
        t = Table(data)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), rl_colors.lightgrey),
            ('ALIGN', (1,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, rl_colors.black),
            ('PADDING', (0,0), (-1,-1), 6)
        ]))
        doc.build([t])
        
        with open(filepath_stats_p, "rb") as file_sp:
            st.download_button("Pobierz Statystyki (PDF)", data=file_sp, file_name=filepath_stats_p, mime="application/pdf")
    
elif menu == "Pracownicy":
    st.header(f"Zarządzanie Zespołem: {selected_loc_name}")
    
    col_add, col_edit = st.columns(2)
    with col_add:
        st.subheader("Dodaj pracownika")
        dodaj_imie = st.text_input("Nowy pracownik (Imię i Nazwisko)")
        if st.button("Dodaj"):
            if dodaj_imie.strip():
                db.add_employee(dodaj_imie, location_id)
                st.success(f"Dodano pracownika do {selected_loc_name}!")
                st.rerun()
            else:
                st.error("Imię i nazwisko nie może być puste.")
            
    with col_edit:
        st.subheader("Edytuj dane")
        emps_for_edit = db.get_employees(location_id)
        if emps_for_edit:
            emp_dict = {name: emp_id for emp_id, name in emps_for_edit}
            selected_emp_edit = st.selectbox("Wybierz pracownika do edycji", list(emp_dict.keys()))
            nowe_imie = st.text_input("Nowe Imię i Nazwisko", value=selected_emp_edit)
            if st.button("Zapisz zmiany"):
                if nowe_imie.strip() and nowe_imie != selected_emp_edit:
                    success = db.update_employee(emp_dict[selected_emp_edit], nowe_imie)
                    if success:
                        st.success("Zmieniono dane pracownika!")
                        st.rerun()
                    else:
                        st.error("Pracownik o takim imieniu już istnieje (bądź wystąpił błąd bazy).")
                elif nowe_imie == selected_emp_edit:
                    st.info("Dalsze bez zmian.")
                else:
                    st.error("Pole nie może być puste.")
        else:
            st.info("Brak pracownikow do edycji w tym obiekcie.")
        
    st.divider()
    st.subheader(f"Aktualna lista pracowników: {selected_loc_name}")
    emps = db.get_employees(location_id)
    if emps:
        for emp_id, name in emps:
            colA, colB = st.columns([5, 1])
            with colA:
                st.write(f"**{name}**")
            with colB:
                if st.button("Usuń", key=f"del_{emp_id}"):
                    db.remove_employee(emp_id)
                    st.success(f"Usunięto pracownika {name}!")
                    st.rerun()
    else:
        st.write("Brak pracowników.")
