import os
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Date, UniqueConstraint, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import date
import streamlit as st

# Connection string from user (with placeholder for security in code if needed, but here we use it directly)
# In production, this should be in st.secrets
DB_URL = st.secrets.get("db_url", "postgresql://postgres:Logowanie000@db.oxzlfmaotsosxzvivjrt.supabase.co:5432/postgres")

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Models ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, PRIMARY KEY=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)  # In real app use hashing
    role = Column(String)  # 'admin' or 'user'

class Location(Base):
    __tablename__ = "locations"
    id = Column(Integer, PRIMARY KEY=True, index=True)
    name = Column(String, unique=True, index=True)

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, PRIMARY KEY=True, index=True)
    name = Column(String)
    location_id = Column(Integer, ForeignKey("locations.id"))
    __table_args__ = (UniqueConstraint('name', 'location_id', name='_name_loc_uc'),)

class Unavailability(Base):
    __tablename__ = "unavailabilities"
    id = Column(Integer, PRIMARY KEY=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    type = Column(String) # 'U', 'CH', etc.

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, PRIMARY KEY=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    location_id = Column(Integer, ForeignKey("locations.id"))
    year = Column(Integer)
    month = Column(Integer)
    day = Column(Integer)
    shift = Column(String) # 'R', 'P', 'N'
    status = Column(String, default="DRAFT") # 'DRAFT', 'PENDING', 'APPROVED'
    version = Column(Integer, default=1)
    created_by = Column(String)
    created_at = Column(Date, default=date.today)

# --- DB Interactions ---

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Init default locations
    if db.query(Location).count() == 0:
        locs = ["Maszynownia Przepompowni", "Oczyszczalnia", "Kanalarze"]
        for l in locs:
            db.add(Location(name=l))
    
    # Init default users
    if db.query(User).count() == 0:
        db.add(User(username="admin", password="Logowanie000", role="admin"))
        db.add(User(username="uzytkownik1", password="grafiki2026", role="user"))
        
    db.commit()
    db.close()

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

def get_locations():
    db = SessionLocal()
    locs = db.query(Location).all()
    db.close()
    return [(l.id, l.name) for l in locs]

def get_employees(location_id=None):
    db = SessionLocal()
    if location_id:
        emps = db.query(Employee).filter(Employee.location_id == location_id).all()
    else:
        emps = db.query(Employee).all()
    db.close()
    return [(e.id, e.name) for e in emps]

def add_employee(name, location_id):
    db = SessionLocal()
    emp = Employee(name=name, location_id=location_id)
    db.add(emp)
    try:
        db.commit()
    except:
        db.rollback()
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
    db.query(Unavailability).filter(
        Unavailability.year == year, 
        Unavailability.month == month, 
        Unavailability.location_id == location_id
    ).delete()
    for emp_id, day, typ in data_list:
        db.add(Unavailability(employee_id=emp_id, location_id=location_id, year=year, month=month, day=day, type=typ))
    db.commit()
    db.close()

def save_schedule(schedule_dict, year, month, emp_name_to_id, location_id, status="DRAFT", user="system"):
    db = SessionLocal()
    
    # For now, we overwrite if same month/loc/status or just wipe and re-save
    # To support archives, we should probably handle versions better.
    # Simple approach: one record per day/emp/month/loc
    db.query(Schedule).filter(
        Schedule.year == year, 
        Schedule.month == month, 
        Schedule.location_id == location_id,
        Schedule.status == status
    ).delete()
    
    for emp_name, days in schedule_dict.items():
        emp_id = emp_name_to_id[emp_name]
        for d, shift in days.items():
            if shift:
                db.add(Schedule(
                    employee_id=emp_id, 
                    location_id=location_id, 
                    year=year, 
                    month=month, 
                    day=d, 
                    shift=shift,
                    status=status,
                    created_by=user
                ))
    db.commit()
    db.close()

def get_schedule(year, month, location_id, status="APPROVED"):
    db = SessionLocal()
    rows = db.query(Schedule).filter(
        Schedule.year == year, 
        Schedule.month == month, 
        Schedule.location_id == location_id,
        Schedule.status == status
    ).all()
    db.close()
    return rows

def get_all_stats(location_id=None):
    db = SessionLocal()
    from sqlalchemy import func
    
    query = db.query(Employee.name, Schedule.shift, func.count(Schedule.id))\
              .join(Schedule, Employee.id == Schedule.employee_id)\
              .filter(Schedule.status == "APPROVED")
              
    if location_id:
        query = query.filter(Schedule.location_id == location_id, Employee.location_id == location_id)
        
    rows = query.group_by(Employee.name, Schedule.shift).all()
    
    stats = {}
    for name, shift, count in rows:
        if name not in stats:
            stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
        if shift in stats[name]:
            stats[name][shift] = count
            
    # Fill missing emps
    emps = get_employees(location_id)
    for _, name in emps:
        if name not in stats:
            stats[name] = {'R': 0, 'P': 0, 'N': 0, 'W': 0, 'U': 0, 'CH': 0}
    db.close()
    return stats

def verify_user(username, password):
    db = SessionLocal()
    user = db.query(User).filter(User.username == username, User.password == password).first()
    db.close()
    return user
