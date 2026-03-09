import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
import calendar
from datetime import date
import holidays
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors as rl_colors

def export_schedule(schedule_dict, year, month, filepath):
    wb = Workbook()
    ws = wb.active
    ws.title = f"Grafik {month}-{year}"
    
    pl_holidays = holidays.Poland(years=year)
    
    # Nagłówki
    headers = ["Imię i Nazwisko"]
    num_days = calendar.monthrange(year, month)[1]
    for d in range(1, num_days + 1):
        headers.append(str(d))
        
    stats_headers = ["Suma R", "Suma P", "Suma N", "Suma U", "Suma CH", "Suma W"]
    headers.extend(stats_headers)
    ws.append(headers)
    
    # Kolory czcionek: R-zielony, P-niebieski, N-czarny, U-czerwony, CH-czerwony, W-czerwony
    colors = {
        'R': '00B050',
        'P': '0070C0',
        'N': '000000',
        'U': 'FF0000',
        'CH': 'FF0000',
        'W': 'FF0000'
    }
    
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    
    # Formatowanie nagłówków i oznaczanie weekendow/swiat w pierwszym wierszu
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
        
        # Dni sa od kolumny 2 do num_days+1
        if 2 <= col <= num_days + 1:
            d = col - 1
            dt = date(year, month, d)
            if dt.weekday() == 6 or dt in pl_holidays:
                cell.fill = red_fill
            elif dt.weekday() == 5:
                cell.fill = green_fill
            
    # Formatowanie komórek
    for row_idx, (emp, days) in enumerate(schedule_dict.items(), start=2):
        row_data = [emp]
        counts = {'R': 0, 'P': 0, 'N': 0, 'U': 0, 'CH': 0, 'W': 0}
        
        for d in range(1, num_days + 1):
            shift = days.get(d, '')
            if shift in counts:
                counts[shift] += 1
            row_data.append(shift)
            
        row_data.extend([counts['R'], counts['P'], counts['N'], counts['U'], counts['CH'], counts['W']])
        ws.append(row_data)
        
        # Formatowanie komórek (Dni od kolumny B (2))
        for d in range(1, num_days + 1):
            cell = ws.cell(row=row_idx, column=1 + d)
            shift = cell.value
            dt = date(year, month, d)
            if shift in colors:
                cell.font = Font(color=colors[shift], bold=True)
            if dt.weekday() == 6 or dt in pl_holidays:
                cell.fill = red_fill
            elif dt.weekday() == 5:
                cell.fill = green_fill
            cell.alignment = Alignment(horizontal='center')
            
    # Podsumowanie pod tabelą (Opcjonalnie dla excela, dodajemy wiersze)
    bottom_row_start = len(schedule_dict) + 2
    for label, count_type in [('📦 SUMA: Rano', 'R'), ('📦 SUMA: Popołudnie', 'P'), ('📦 SUMA: Noc', 'N')]:
        row_data = [label]
        for d in range(1, num_days + 1):
            s = sum(1 for emp in schedule_dict if schedule_dict[emp].get(d) == count_type)
            row_data.append(s)
        ws.append(row_data)
    
    wb.save(filepath)
    return filepath

def export_schedule_pdf(schedule_dict, year, month, filepath):
    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            rightMargin=10, leftMargin=10, topMargin=10, bottomMargin=10)
    
    pl_holidays = holidays.Poland(years=year)
    num_days = calendar.monthrange(year, month)[1]
    
    # Nagłówki
    headers = ["Imię i Naz."] + [str(d) for d in range(1, num_days + 1)] + ["R", "P", "N", "U", "CH", "W"]
    data = [headers]
    
    # Wiersze pracownikow
    for emp, days in schedule_dict.items():
        counts = {'R': 0, 'P': 0, 'N': 0, 'U': 0, 'CH': 0, 'W': 0}
        row = [emp[:12]] # Skrocone imie zeby weszlo
        for d in range(1, num_days + 1):
            shift = days.get(d, '')
            if shift in counts:
                counts[shift] += 1
            row.append(shift)
        row.extend([counts['R'], counts['P'], counts['N'], counts['U'], counts['CH'], counts['W']])
        data.append(row)
        
    # Podsumowanie na dole
    data.append([]) # Pusty wiersz jako rozdzielacz
    for label, count_type in [('SUMA R', 'R'), ('SUMA P', 'P'), ('SUMA N', 'N')]:
        row = [label]
        for d in range(1, num_days + 1):
            s = sum(1 for emp in schedule_dict if schedule_dict[emp].get(d) == count_type)
            row.append(str(s))
        data.append(row)
        
    # Tworzenie tabeli
    # Kolumny dni wezsze, kolumna pracownika szersza
    col_widths = [60] + [18] * num_days + [18] * 6
    t = Table(data, colWidths=col_widths)
    
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), rl_colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), rl_colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (0,1), (0,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1, len(schedule_dict)), 0.5, rl_colors.black),
        ('GRID', (0, len(schedule_dict)+2), (num_days, -1), 0.5, rl_colors.black), # siatka dla sum 
    ])
    
    # Kolorowanie weekendów i skrótów
    for row_idx, row in enumerate(data):
        if row_idx == 0:
            for d in range(1, num_days + 1):
                dt = date(year, month, d)
                if dt.weekday() == 6 or dt in pl_holidays:
                    style.add('BACKGROUND', (d, 0), (d, len(schedule_dict)), rl_colors.mistyrose)
                elif dt.weekday() == 5:
                    style.add('BACKGROUND', (d, 0), (d, len(schedule_dict)), rl_colors.honeydew)
        
        for col_idx, cell in enumerate(row):
            if cell == 'R':
                style.add('TEXTCOLOR', (col_idx, row_idx), (col_idx, row_idx), rl_colors.green)
            elif cell == 'P':
                style.add('TEXTCOLOR', (col_idx, row_idx), (col_idx, row_idx), rl_colors.blue)
            elif cell in ('U', 'CH', 'W'):
                style.add('TEXTCOLOR', (col_idx, row_idx), (col_idx, row_idx), rl_colors.red)
                
    t.setStyle(style)
    
    elements = [t]
    doc.build(elements)
    
    return filepath
