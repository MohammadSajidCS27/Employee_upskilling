# 01_MASTER_PROJECT_OVERVIEW.md

# Personalized Learning & Development Pathway Generator

## Version

1.0

## Project Type

AI-Powered Workforce Intelligence Platform

---

# 1. Executive Summary

Organizations invest heavily in employee training and development programs, but most organizations still struggle to answer critical questions:

### Employee Perspective

* What skills do I currently possess?
* What skills am I missing for my current role?
* What new skills are emerging in the industry?
* How future-proof am I?
* Can I transition into another role?
* What should I learn next?

### Manager Perspective

* Which employees best match a specific Job Description?
* Which employees are ready for future roles?
* Which skills are strong across the team?
* Which skills are missing across the team?
* Who can be upskilled for upcoming projects?
* What is the overall workforce readiness?

This platform solves these problems using AI Agents, Workforce Intelligence, Market Intelligence, Career Intelligence, and Personalized Learning Path Generation.

The platform is designed as a multi-agent system orchestrated using LangChain , LangGraph and powered by Groq LLMs.

---

# 2. Project Vision

The vision is to build an intelligent workforce platform capable of answering four strategic workforce questions.

---

## Intelligence Layer 1

### Employee vs Current Role

Question:

How suitable is an employee for their current role?

Example:

Current Role:

Java Developer

Employee Skills:

* Java
* Spring Boot
* SQL

Expected Skills:

* Java
* Spring Boot
* REST APIs
* Microservices
* Docker
* Git

Output:

* Readiness Score
* Core Skill Gaps
* Missing Competencies

---

## Intelligence Layer 2

### Employee vs Market

Question:

What new skills are emerging in the market that this employee does not possess?

Example:

Employee Skills:

* Java
* Spring Boot
* SQL

Market Trends:

* Java 21
* Virtual Threads
* Spring AI
* MCP
* Agentic AI
* RAG

Output:

* Emerging Skills
* Market Skill Gaps
* Future Readiness Score

Purpose:

Future-proof employees against changing industry demands.

---

## Intelligence Layer 3

### Employee vs Target Role

Question:

Can this employee transition into another role?

Example:

Current Role:

Java Developer

Target Role:

AI Engineer

Output:

* Transition Score
* Missing Skills
* Career Transition Roadmap

Purpose:

Support career growth and internal mobility.

---

## Intelligence Layer 4

### Job Description vs Employees

Question:

Which employees best match a particular Job Description?

Example:

Manager uploads:

Senior AI Engineer Job Description

System extracts:

* Python
* LLMs
* RAG
* LangChain
* LangGraph
* Vector Databases

System compares against all employee profiles.

Output:

Employee Ranking:

* Employee A → 89%
* Employee B → 81%
* Employee C → 73%

Purpose:

Talent Discovery and Internal Hiring.

---

# 3. Primary Users

## Employee

Goals:

* Understand current readiness
* Identify skill gaps
* Understand market trends
* Plan career growth
* Follow learning roadmap

---

## Manager

Goals:

* Identify suitable employees
* Analyze team skills
* Plan workforce development
* Improve team readiness
* Support internal mobility

---

# 4. Core Business Capabilities

The platform provides six major capabilities.

## Capability 1

Resume Understanding

Convert employee resumes into structured profiles.

Output:

* Role
* Experience
* Skills
* Education

---

## Capability 2

Current Role Analysis

Compare employee skills with expected role skills.

Output:

* Readiness Score
* Missing Skills
* Competency Analysis

---

## Capability 3

Market Intelligence

Compare employee skills against industry trends.

Data Sources:

* ESCO
* O*NET
* Google Trends
* GitHub Trends
* Job Descriptions
* YouTube Technology Trends

Output:

* Emerging Skills
* Trending Technologies
* Market Skill Gaps

---

## Capability 4

Career Transition Analysis

Compare employee skills against target role skills.

Output:

* Transition Score
* Missing Skills
* Career Roadmap

---

## Capability 5

Learning Path Generation

Generate roadmap.sh-inspired learning paths.

Output:

* Foundation Phase
* Core Skills Phase
* Project Phase
* Advanced Phase

---

## Capability 6

Talent Matching

Compare Job Descriptions against employee profiles.

Output:

* Employee Ranking
* Skill Match Score
* Hiring Recommendations

---

# 5. Technology Stack

## Backend

FastAPI

Purpose:

* REST APIs
* Authentication
* File Upload
* Service Layer

---

## Agent Orchestration

LangGraph

Purpose:

* Multi-Agent Workflow
* State Management
* Agent Communication

---

## LLM Provider

Groq

Purpose:

* Reasoning
* Resume Understanding
* Recommendations

---

## Relational Database

PostgreSQL

Purpose:

* Employee Profiles
* Analysis Results
* Roadmaps
* Learning Progress

---

## Vector Database

ChromaDB

Purpose:

* Learning Resource Embeddings
* Semantic Search
* RAG

---

## Frontend

React

Purpose:

* Employee Dashboard
* Manager Dashboard

---

# 6. Agent Architecture

An agent is created only when all of the following exist:

* Goal
* Reasoning
* Tools
* Decision Making
* Action
* Memory

If these characteristics are absent, the component should be implemented as a service rather than an agent.

---

## Agent 1

Resume Intelligence Agent

### Goal

Understand employee profile.

### Why It Is An Agent

The system must reason over unstructured resume content and infer:

* Role
* Experience
* Skills
* Education

### Tools

* PDF Loader
* Groq LLM
* Skill Normalization Service

### Output

Employee Profile

---

## Agent 2

Skill Intelligence Agent

### Goal

Evaluate employee readiness for current role.

### Why It Is An Agent

The agent reasons over employee skills and compares them with expected role competencies.

### Tools

* ESCO Repository
* O*NET Repository
* Skill Repository

### Output

* Readiness Score
* Core Skill Gaps

---

## Agent 3

Market Intelligence Agent

### Goal

Identify emerging skills and industry trends.

### Why It Is An Agent

The agent collects and merges signals from multiple sources and decides which trends are relevant.

### Tools

* ESCO
* O*NET
* Google Trends
* GitHub Trends
* Job Description Repository
* YouTube Technology Signals

### Output

* Market Gaps
* Emerging Skills
* Trend Report

---

## Agent 4

Career Transition Agent

### Goal

Evaluate career transition possibilities.

### Why It Is An Agent

The agent reasons about role-to-role skill mappings and identifies transition feasibility.

### Tools

* Role Repository
* Skill Repository
* ESCO
* O*NET

### Output

* Transition Score
* Missing Skills

---

## Agent 5

Learning Path Agent

### Goal

Generate roadmap.sh-inspired learning paths.

### Why It Is An Agent

The agent reasons over:

* Skill Dependencies
* Prerequisites
* Learning Sequence
* Project Milestones

### Tools

* Skill Dependency Graph
* Roadmap Templates

### Output

* Learning Roadmap

---

## Agent 6

Talent Matching Agent

### Goal

Find the best employees for a Job Description.

### Why It Is An Agent

The agent must:

* Parse the Job Description
* Extract Skills
* Compare Employees
* Rank Candidates

### Tools

* JD Parser
* Employee Repository
* Skill Matching Engine

### Output

* Employee Ranking
* Match Scores

---

# 7. Non-Agent Components

These are services.

## Course Repository Service

Stores:

* Courses
* Certifications

---

## ESCO Repository Service

Stores:

* Occupations
* Skills

---

## O*NET Repository Service

Stores:

* Competencies

---

## PostgreSQL Service

Stores:

* Employee Data
* Analysis Results

---

## ChromaDB Service

Stores:

* Learning Embeddings
* Semantic Search Data

---

# 8. Project Phases

## Phase 1

Employee Intelligence Layer

Deliverables:

* Resume Intelligence Agent
* Skill Intelligence Agent
* Market Intelligence Agent
* Career Transition Agent
* Learning Path Agent
* Talent Matching Agent
* PostgreSQL Integration

Outcome:

Employees receive:

* Current Role Analysis
* Market Analysis
* Career Analysis
* Learning Roadmap

Managers receive:

* Talent Matching
* Employee Rankings

---

## Phase 2

Learning Intelligence Layer

Deliverables:

* Resource Collection
* ChromaDB
* RAG
* Personalized Learning Recommendations

Outcome:

Context-aware learning recommendations.

---

## Phase 3

Workforce Intelligence Layer

Deliverables:

* Team Analytics
* Workforce Readiness
* Skill Heatmaps
* Internal Mobility Analytics
* Learning Impact Analytics

Outcome:

Organization-wide workforce intelligence.

---

# 9. Manager Analytics

Manager Dashboard should provide:

### Team Skill Strengths

### Team Skill Gaps

### Workforce Readiness

### Skill Heatmaps

### Internal Mobility Opportunities

### Talent Matching Results

### Employee Skill Ranking

### Emerging Skill Readiness

---

# 10. Final End-to-End Workflow

Employee Flow:

Resume Upload
→ Resume Intelligence Agent
→ Skill Intelligence Agent
→ Market Intelligence Agent
→ Career Transition Agent
→ Learning Path Agent
→ PostgreSQL
→ Employee Dashboard

Manager Flow:

Job Description Upload
→ Talent Matching Agent
→ Employee Ranking
→ Workforce Insights
→ Manager Dashboard

---

# 11. Success Criteria

Employee Level

* Accurate Skill Extraction
* Accurate Skill Gap Detection
* Useful Learning Roadmaps

Manager Level

* Accurate Employee Matching
* Workforce Visibility
* Better Internal Hiring Decisions

Organization Level

* Improved Workforce Readiness
* Faster Upskilling
* Better Internal Mobility

---

# Conclusion

This project is not a resume parser, course recommender, or LMS.

It is an AI-Powered Workforce Intelligence Platform that continuously answers four strategic questions:

1. Employee vs Current Role
2. Employee vs Market
3. Employee vs Target Role
4. Job Description vs Employees

using six specialized AI agents, workforce intelligence repositories, market intelligence sources, and personalized learning pathways.
