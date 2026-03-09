import sqlite3
from datetime import date

DB_PATH = "grafik.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Lokacje (Obiekty)
    c.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    
    # Pracownicy (z location_id)
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location_id INTEGER,
            FOREIGN KEY(location_id) REFERENCES locations(id),
            UNIQUE(name, location_id)
        )
    ''')
    
    # Niedostępności
    c.execute('''
        CREATE TABLE IF NOT EXISTS unavailabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            location_id INTEGER,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            type TEXT,
            FOREIGN KEY(employee_id) REFERENCES employees(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    ''')
    
    # Zapisane grafiki
    c.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            location_id INTEGER,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            shift TEXT,
            FOREIGN KEY(employee_id) REFERENCES employees(id),
            FOREIGN KEY(location_id) REFERENCES locations(id)
        )
    ''')
    
    # Migracja: dodaj kolumnę location_id jeśli nie istnieje (dla starszych wersji)
    try:
        c.execute("ALTER TABLE employees ADD COLUMN location_id INTEGER REFERENCES locations(id)")
    except sqlite3.OperationalError:
        pass # już istnieje
        
    try:
        c.execute("ALTER TABLE unavailabilities ADD COLUMN location_id INTEGER REFERENCES locations(id)")
    except sqlite3.OperationalError:
        pass
        
    try:
        c.execute("ALTER TABLE schedules ADD COLUMN location_id INTEGER REFERENCES locations(id)")
    except sqlite3.OperationalError:
        pass

    # Wypełnienie domyślnymi lokacjami
    locations = ["Maszynownia Przepompowni", "Oczyszczalnia", "Kanalarze"]
    for loc in locations:
        c.execute("INSERT OR IGNORE INTO locations (name) VALUES (?)", (loc,))
    
    # Pobierz ID pierwszej lokacji
    c.execute("SELECT id FROM locations WHERE name = ?", (locations[0],))
    default_loc_id = c.fetchone()[0]
    
    # Wypełnienie domyślnymi pracownikami dla pierwszej lokacji, jeśli pusto
    c.execute('SELECT COUNT(*) FROM employees')
    if c.fetchone()[0] == 0:
        default_emps = [f"Pracownik {i}" for i in range(1, 8)]
        c.executemany("INSERT INTO employees (name, location_id) VALUES (?, ?)", [(e, default_loc_id) for e in default_emps])
        
    conn.commit()
    conn.close()

def get_locations():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name FROM locations")
    locs = c.fetchall()
    conn.close()
    return locs

def get_employees(location_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if location_id:
        c.execute("SELECT id, name FROM employees WHERE location_id=?", (location_id,))
    else:
        c.execute("SELECT id, name FROM employees")
    emps = c.fetchall()
    conn.close()
    return emps

def add_employee(name, location_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO employees (name, location_id) VALUES (?, ?)", (name, location_id))
    conn.commit()
    conn.close()

def update_employee(emp_id, new_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("UPDATE employees SET name = ? WHERE id = ?", (new_name, emp_id))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    finally:
        conn.close()
    return success

def remove_employee(emp_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM schedules WHERE employee_id=?", (emp_id,))
    c.execute("DELETE FROM unavailabilities WHERE employee_id=?", (emp_id,))
    c.execute("DELETE FROM employees WHERE id=?", (emp_id,))
    conn.commit()
    conn.close()

def get_unavailabilities(year, month, location_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if location_id:
        c.execute("SELECT employee_id, day, type FROM unavailabilities WHERE year=? AND month=? AND location_id=?", (year, month, location_id))
    else:
        c.execute("SELECT employee_id, day, type FROM unavailabilities WHERE year=? AND month=?", (year, month))
    rows = c.fetchall()
    conn.close()
    return rows

def update_unavailabilities_for_month(year, month, data_list, location_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM unavailabilities WHERE year=? AND month=? AND location_id=?", (year, month, location_id))
    for emp_id, day, typ in data_list:
        c.execute("INSERT INTO unavailabilities (employee_id, location_id, year, month, day, type) VALUES (?, ?, ?, ?, ?, ?)",
                  (emp_id, location_id, year, month, day, typ))
    conn.commit()
    conn.close()

def save_schedule(schedule_dict, year, month, emp_name_to_id, location_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Usuwamy stary dla tego miesiąca w tej lokacji
    c.execute("DELETE FROM schedules WHERE year=? AND month=? AND location_id=?", (year, month, location_id))
    
    for emp_name, days in schedule_dict.items():
        emp_id = emp_name_to_id[emp_name]
        for d, shift in days.items():
            if shift:
                c.execute("INSERT INTO schedules (employee_id, location_id, year, month, day, shift) VALUES (?, ?, ?, ?, ?, ?)",
                          (emp_id, location_id, year, month, d, shift))
    conn.commit()
    conn.close()

def get_all_stats(location_id=None):
    # Zlicza sumarycznie liczbę R, P, N ze wszystkich miesięcy per pracownik
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if location_id:
        c.execute('''
            SELECT e.name, s.shift, COUNT(s.id)
            FROM employees e
            LEFT JOIN schedules s ON e.id = s.employee_id AND s.location_id=?
            WHERE e.location_id=?
            GROUP BY e.name, s.shift
        ''', (location_id, location_id))
    else:
        c.execute('''
            SELECT e.name, s.shift, COUNT(s.id)
            FROM employees e
            LEFT JOIN schedules s ON e.id = s.employee_id
            GROUP BY e.name, s.shift
        ''')
    rows = c.fetchall()
    conn.close()
    
    stats = {}
    for name, shift, count in rows:
        if name not in stats:
            stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
        if shift in stats[name]:
            stats[name][shift] = count
            
    # Normalize for missing employees
    emps = get_employees(location_id)
    for _, name in emps:
        if name not in stats:
            stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
            
    return stats
