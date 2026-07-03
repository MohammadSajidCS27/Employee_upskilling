# Phase 1 Architecture

## Objective

Build the Employee Intelligence Layer and Manager Talent Matching Layer.

Phase-1 establishes the foundational employee profile, skill intelligence, market intelligence, career transition intelligence, learning roadmap generation, and talent matching capabilities.

---

# Phase 1 Deliverables

## Employee Side

1. Resume Intelligence Agent
2. Skill Intelligence Agent
3. Market Intelligence Agent
4. Career Transition Agent
5. Learning Path Agent

---

## Manager Side

6. Talent Matching Agent

---

# Phase 1 Architecture

Employee Flow

Resume Upload
↓
Resume Intelligence Agent
↓
Skill Intelligence Agent
↓
Market Intelligence Agent
↓
Career Transition Agent
↓
Learning Path Agent
↓
PostgreSQL
↓
Employee Dashboard

---

Manager Flow

Job Description Upload
↓
Talent Matching Agent
↓
Employee Ranking
↓
Manager Dashboard

---

# LangGraph Workflow

Employee Workflow

resume_parser
↓
skill_intelligence
↓
market_intelligence
↓
career_transition
↓
learning_path
↓
persist_results

Manager Workflow

job_description_parser
↓
talent_matching
↓
ranking_generator

---

# Agent State

class AgentState(TypedDict):

    resume_text: str

    profile: dict

    readiness_score: float

    core_gaps: list

    market_gaps: list

    emerging_skills: list

    target_role: str

    transition_score: float

    target_role_gaps: list

    roadmap: dict

    learning_resources: dict

---

# Resume Intelligence Agent

Goal:

Convert resume into structured profile.

Input:

Resume PDF

Tools:

PyPDF
Groq LLM
Skill Normalizer

Output:

{
  "role": "",
  "experience": 0,
  "skills": [],
  "education": []
}

---

# Skill Intelligence Agent

Goal:

Employee vs Current Role

Sources:

ESCO
O*NET

Output:

{
  "readiness_score": 82,
  "core_gaps": []
}

---

# Market Intelligence Agent

Goal:

Employee vs Market

Sources:

ESCO
O*NET
Google Trends
GitHub Trends
Job Descriptions
YouTube Technology Signals

Output:

{
  "market_gaps": [],
  "emerging_skills": []
}

---

# Career Transition Agent

Goal:

Employee vs Target Role

Example

Java Developer
→ AI Engineer

Output:

{
  "transition_score": 45,
  "target_role_gaps": []
}

---

# Learning Path Agent

Goal:

Roadmap.sh-inspired roadmap generation

Logic:

Prerequisites
↓
Foundation Skills
↓
Core Skills
↓
Projects
↓
Advanced Skills

Output:

{
  "foundation": [],
  "core": [],
  "projects": [],
  "advanced": []
}

---

# Talent Matching Agent

Goal:

Match employees against Job Description.

Input:

Job Description

Output:

[
  {
    "employee":"John",
    "score":89
  }
]

---

# PostgreSQL Tables

employees
roles
skills
employee_skills
analyses
roadmaps
job_descriptions
talent_matches

---

# Phase 1 Success Criteria

Employee can:

- Upload Resume
- See Skill Gaps
- See Market Gaps
- See Career Transition Opportunities
- Get Learning Roadmap

Manager can:

- Upload Job Description
- Find Best Employees
- View Skill Match Scores