import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Date, UniqueConstraint, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import date
import streamlit as st

DB_URL = st.secrets.get("db_url", "postgresql://postgres.oxzlfmaotsosxzvivjrt:Logowanie000@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Models ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)  # 'admin' or 'user'
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)

class Location(Base):
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id"))
    sort_order = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint('name', 'location_id', name='_name_loc_uc'),)

class Unavailability(Base):
    __tablename__ = "unavailabilities"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    type = Column(String)

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    shift = Column(String)
    status = Column(String, default="DRAFT")
    version = Column(Integer, default=1)
    created_by = Column(String)
    created_at = Column(Date, default=date.today)

# --- DB Interactions ---

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(Location).count() == 0:
        for l in ["Maszynownia Przepompowni", "Oczyszczalnia", "Kanalarze"]:
            db.add(Location(name=l))
    if db.query(User).count() == 0:
        db.add(User(username="admin", password="Logowanie000", role="admin"))
        db.add(User(username="uzytkownik1", password="grafiki2026", role="user"))
    db.commit()
    db.close()

    # Migracja: dodaj kolumnę employee_id do tabeli users, jeśli nie istnieje
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id INTEGER REFERENCES employees(id)"
            ))
            conn.commit()
    except Exception:
        pass  # Kolumna już istnieje lub brak uprawnień

def get_locations():
    db = SessionLocal()
    locs = db.query(Location).all()
    db.close()
    return [(l.id, l.name) for l in locs]

def get_employees(location_id=None):
    db = SessionLocal()
    query = db.query(Employee)
    if location_id:
        query = query.filter(Employee.location_id == location_id)
    emps = query.order_by(Employee.sort_order, Employee.name).all()
    db.close()
    return [(e.id, e.name, e.email, e.sort_order) for e in emps]

def add_employee(name, location_id, email=None, sort_order=0):
    db = SessionLocal()
    db.add(Employee(name=name, location_id=location_id, email=email, sort_order=sort_order))
    try:
        db.commit()
    except:
        db.rollback()
    db.close()

def update_employee_order(emp_id, sort_order):
    db = SessionLocal()
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if emp:
        emp.sort_order = sort_order
        db.commit()
    db.close()

def update_employee(emp_id, name, email=None):
    db = SessionLocal()
    emp = db.query(Employee).filter(Employee.id == emp_id).first()
    if emp:
        emp.name = name
        emp.email = email
        db.commit()
    db.close()

def remove_employee(emp_id):
    db = SessionLocal()
    db.query(Schedule).filter(Schedule.employee_id == emp_id).delete()
    db.query(Unavailability).filter(Unavailability.employee_id == emp_id).delete()
    db.query(Employee).filter(Employee.id == emp_id).delete()
    db.commit()
    db.close()

def get_unavailabilities(year, month, location_id=None):
    db = SessionLocal()
    query = db.query(Unavailability).filter(Unavailability.year == year, Unavailability.month == month)
    if location_id:
        query = query.filter(Unavailability.location_id == location_id)
    rows = query.all()
    db.close()
    return [(r.employee_id, r.day, r.type) for r in rows]

def update_unavailabilities_for_month(year, month, data_list, location_id):
    db = SessionLocal()
    db.query(Unavailability).filter(Unavailability.year == year, Unavailability.month == month, Unavailability.location_id == location_id).delete()
    for eid, d, t in data_list:
        db.add(Unavailability(employee_id=eid, location_id=location_id, year=year, month=month, day=d, type=t))
    db.commit()
    db.close()

def save_schedule(schedule_dict, year, month, emp_name_to_id, location_id, status="DRAFT", user="system"):
    db = SessionLocal()
    db.query(Schedule).filter(Schedule.year == year, Schedule.month == month, Schedule.location_id == location_id, Schedule.status == status).delete()
    for emp_name, days in schedule_dict.items():
        eid = emp_name_to_id[emp_name]
        for d, shift in days.items():
            if shift:
                db.add(Schedule(employee_id=eid, location_id=location_id, year=year, month=month, day=d, shift=shift, status=status, created_by=user))
    db.commit()
    db.close()

def get_schedule(year, month, location_id, status="APPROVED"):
    db = SessionLocal()
    rows = db.query(Employee.name, Schedule.day, Schedule.shift).join(Employee).filter(
        Schedule.year == year,
        Schedule.month == month,
        Schedule.location_id == location_id,
        Schedule.status == status
    ).all()
    db.close()
    
    schedule = {}
    for name, d, s in rows:
        if name not in schedule: schedule[name] = {}
        schedule[name][d] = s
    return schedule

def get_all_schedules_with_status(status="DRAFT"):
    db = SessionLocal()
    # Get distinct year, month, location_id for a given status
    # Order by year desc, month desc
    results = db.query(Schedule.year, Schedule.month, Location.id, Location.name).join(Location).filter(
        Schedule.status == status
    ).group_by(Schedule.year, Schedule.month, Location.id, Location.name).order_by(Schedule.year.desc(), Schedule.month.desc()).all()
    db.close()
    return results

def get_all_stats(location_id=None):
    db = SessionLocal()
    from sqlalchemy import func
    query = db.query(Employee.name, Schedule.shift, func.count(Schedule.id)).join(Schedule).filter(Schedule.status == "APPROVED")
    if location_id:
        query = query.filter(Schedule.location_id == location_id)
    rows = query.group_by(Employee.name, Schedule.shift).all()
    stats = {}
    for name, shift, count in rows:
        if name not in stats: stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
        if shift in stats[name]: stats[name][shift] = count
    emps = get_employees(location_id)
    for _, name, _, _ in emps:
        if name not in stats: stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
    db.close()
    return stats

def get_stats_for_range(location_id, year_from, month_from, year_to, month_to):
    """Zwraca statystyki (R, P, N, W, U, CH, S, WE) dla zakresu miesięcy z zatwierdzonych grafików."""
    db_s = SessionLocal()
    rows = db_s.query(
        Employee.name,
        Schedule.year,
        Schedule.month,
        Schedule.day,
        Schedule.shift
    ).join(Employee, Employee.id == Schedule.employee_id).filter(
        Schedule.status == "APPROVED",
        Schedule.location_id == location_id
    ).order_by(Employee.sort_order, Employee.name).all()
    db_s.close()

    from_val = year_from * 12 + month_from
    to_val   = year_to   * 12 + month_to

    import holidays as hol
    from datetime import date as dt_date

    pl_holidays_cache = {}
    stats = {}

    for name, year, month, day, shift in rows:
        val = year * 12 + month
        if from_val <= val <= to_val:
            if name not in stats:
                stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0, 'S': 0, 'WE': 0}
            if shift in ['R', 'P', 'N', 'W', 'U', 'CH']:
                stats[name][shift] += 1
            if shift in ['R', 'P', 'N', 'U', 'CH']:
                stats[name]['S'] += 1
            if shift in ['R', 'P', 'N']:
                if year not in pl_holidays_cache:
                    pl_holidays_cache[year] = hol.Poland(years=year)
                d = dt_date(year, month, day)
                if d.weekday() >= 5 or d in pl_holidays_cache[year]:
                    stats[name]['WE'] += 1

    return stats

def verify_user(username, password):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username, User.password == password).first()
    db.close()
    return user

def get_users():
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [(u.id, u.username, u.role) for u in users]

def get_users_full():
    """Zwraca listę użytkowników z powiązanym employee_id."""
    db = SessionLocal()
    users = db.query(User).all()
    db.close()
    return [(u.id, u.username, u.role, u.employee_id) for u in users]

def add_user(username, password, role="user"):
    db = SessionLocal()
    db.add(User(username=username, password=password, role=role))
    try:
        db.commit()
    except:
        db.rollback()
    db.close()

def remove_user(user_id):
    db = SessionLocal()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    db.close()

def link_user_to_employee(user_id, employee_id):
    """Powiązuje konto użytkownika z profilem pracownika (None = odłącz)."""
    db = SessionLocal()
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.employee_id = employee_id if employee_id else None
        db.commit()
    db.close()

def get_employee_for_user(username):
    """Zwraca (id, name, location_id, email, sort_order) pracownika powiązanego z tym kontem."""
    db = SessionLocal()
    user = db.query(User).filter(User.username == username).first()
    if user and user.employee_id:
        emp = db.query(Employee).filter(Employee.id == user.employee_id).first()
        db.close()
        if emp:
            return (emp.id, emp.name, emp.location_id, emp.email, emp.sort_order)
    db.close()
    return None

def get_my_schedule(employee_id, year, month):
    """Zwraca {day: shift} słownik dla pracownika z zatwierdzonego grafiku."""
    db = SessionLocal()
    rows = db.query(Schedule.day, Schedule.shift).filter(
        Schedule.employee_id == employee_id,
        Schedule.year == year,
        Schedule.month == month,
        Schedule.status == "APPROVED"
    ).all()
    db.close()
    return {day: shift for day, shift in rows}

def get_my_schedule_months(employee_id):
    """Zwraca listę (year, month, location_name) miesięcy z zatwierdzonymi grafikami dla pracownika."""
    db = SessionLocal()
    results = db.query(
        Schedule.year, Schedule.month, Location.name
    ).join(Location, Schedule.location_id == Location.id).filter(
        Schedule.employee_id == employee_id,
        Schedule.status == "APPROVED"
    ).distinct().order_by(Schedule.year.desc(), Schedule.month.desc()).all()
    db.close()
    return [(r[0], r[1], r[2]) for r in results]

def get_my_unavailabilities(employee_id, year, month):
    """Zwraca {day: type} preferencji dla pracownika."""
    db = SessionLocal()
    rows = db.query(Unavailability.day, Unavailability.type).filter(
        Unavailability.employee_id == employee_id,
        Unavailability.year == year,
        Unavailability.month == month
    ).all()
    db.close()
    return {day: typ for day, typ in rows}

def save_my_unavailabilities(employee_id, location_id, year, month, data_dict):
    """Zapisuje/nadpisuje preferencje pracownika na dany miesiąc. data_dict: {day: type_str}"""
    db = SessionLocal()
    db.query(Unavailability).filter(
        Unavailability.employee_id == employee_id,
        Unavailability.year == year,
        Unavailability.month == month,
        Unavailability.location_id == location_id
    ).delete()
    for day, typ in data_dict.items():
        if typ and str(typ).strip():
            db.add(Unavailability(
                employee_id=employee_id,
                location_id=location_id,
                year=year, month=month,
                day=int(day), type=str(typ).upper()
            ))
    db.commit()
    db.close()

