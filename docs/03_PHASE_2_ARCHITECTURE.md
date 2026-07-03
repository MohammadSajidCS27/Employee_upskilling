# Phase 2 Architecture

## Objective

Build the Learning Intelligence Layer.

Phase-2 transforms skill gaps into personalized learning recommendations.

---

# Phase 2 Deliverables

1. Content Intelligence Agent
2. Resource Retrieval Agent
3. Personalized Learning Agent

---

# Architecture

Skill Gaps
↓
Content Intelligence Agent
↓
Vector Search
↓
Resource Retrieval Agent
↓
Personalized Learning Agent
↓
Dashboard

---

# Content Intelligence Agent

Goal:

Collect learning resources.

Sources:

Udemy
Coursera
YouTube
GitHub
Documentation

Actions:

- Crawl
- Extract
- Categorize

Output:

Learning Resource Repository

---

# ChromaDB

Stores:

Course Embeddings
GitHub Embeddings
Documentation Embeddings
Video Embeddings

---

# Resource Retrieval Agent

Goal:

Find best learning materials.

Input:

Skill Gap

Output:

Top Learning Resources

---

# Personalized Learning Agent

Goal:

Generate personalized learning recommendations.

Factors:

Current Skills
Skill Gaps
Learning History
Career Goals

Output:

{
  "recommended_courses": [],
  "recommended_projects": [],
  "recommended_resources": []
}

---

# RAG Layer

Query
↓
Embedding
↓
ChromaDB
↓
Retrieved Context
↓
Groq

---

# Success Criteria

Employee receives:

- Personalized Courses
- Documentation
- GitHub Projects
- Practice Exercises
- Learning Recommendations