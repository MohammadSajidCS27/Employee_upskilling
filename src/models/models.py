from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, UTC

Base = declarative_base()


def utc_now():
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(200), unique=True, nullable=False)
    siemens_id = Column(String(200), unique=True, nullable=True)
    password_hash = Column(String(200), nullable=False)
    name = Column(String(200), nullable=True)
    department = Column(String(200), nullable=True)
    role = Column(String(200), nullable=True)
    experience_years = Column(Integer, nullable=True, default=0)
    skills = Column(JSON, nullable=True, default=[])
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String(100), unique=True)
    siemens_id = Column(String(100), unique=True, nullable=True)
    department = Column(String(100), nullable=True)
    role = Column(String(100), nullable=True)
    experience_years = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    skills = relationship("EmployeeSkill", back_populates="employee")
    analyses = relationship("Analysis", back_populates="employee")

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)
    description = Column(Text)
    required_skills = Column(JSON)

class Skill(Base):
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)
    category = Column(String(50))

class EmployeeSkill(Base):
    __tablename__ = "employee_skills"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    skill_id = Column(Integer, ForeignKey("skills.id"))
    proficiency = Column(Float)
    employee = relationship("Employee", back_populates="skills")

class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    readiness_score = Column(Float)
    core_gaps = Column(JSON)
    market_gaps = Column(JSON)
    emerging_skills = Column(JSON)
    created_at = Column(DateTime, default=utc_now)
    employee = relationship("Employee", back_populates="analyses")

class Roadmap(Base):
    __tablename__ = "roadmaps"
    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    foundation = Column(JSON)
    core = Column(JSON)
    projects = Column(JSON)
    advanced = Column(JSON)
    created_at = Column(DateTime, default=utc_now)

class JobDescription(Base):
    __tablename__ = "job_descriptions"
    id = Column(Integer, primary_key=True)
    title = Column(String(100))
    description = Column(Text)
    required_skills = Column(JSON)
    created_at = Column(DateTime, default=utc_now)

class TalentMatch(Base):
    __tablename__ = "talent_matches"
    id = Column(Integer, primary_key=True)
    job_description_id = Column(Integer, ForeignKey("job_descriptions.id"))
    employee_id = Column(Integer, ForeignKey("employees.id"))
    match_score = Column(Float)
    created_at = Column(DateTime, default=utc_now)