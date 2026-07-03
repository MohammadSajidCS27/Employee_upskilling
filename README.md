# Personalized Learning & Development Pathway Generator

AI-powered platform for workforce intelligence, personalized employee development, and talent matching.

Answers four strategic workforce questions:
- What skills does an employee have vs what their role requires?
- What emerging market skills is the employee missing?
- Can the employee transition to a new role, and what is the path?
- Which employees best match an open job description?

## Quick Start

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Fill in GROQ_API_KEY, DATABASE_URL, and other values
   ```

3. **Start server**
   ```bash
   python run.py
   # API: http://localhost:8000
   # Docs: http://localhost:8000/docs
   ```

4. **Run React UI (development)**
   ```bash
   cd frontend
   npm install
   npm run dev
   # UI: http://localhost:5173
   ```

## Agents

| Agent | Endpoint | Purpose |
|-------|----------|---------|
| Resume Intelligence | `/analyze/resume` | Extract profile from resume |
| Skill Intelligence | `/analyze/skill-gaps` | Calculate role readiness and skill gaps |
| Market Intelligence | `/analyze/market-gaps` | Identify emerging and vanishing market skills |
| Career Transition | `/analyze/transition` | Evaluate feasibility of career moves |
| Learning Path | `/generate/roadmap` | Generate personalized learning roadmap |
| Talent Matching | `/talent/match` | Match employees to a job description |

## Workflows

| Workflow | Endpoint | Purpose |
|----------|----------|---------|
| Employee | `/workflow/employee` | Full analysis for an employee from resume |
| Manager | `/workflow/manager` | Find best-fit employees for a job description |
| Complete Pipeline | `/pipeline/complete` | End-to-end workforce intelligence pipeline |

## Testing

```bash
python -m pytest tests/ -v
```

## Docker

```bash
docker-compose up
```

## Production Notes

- Set the following in `.env` before deployment:
  - `APP_ENV=prod`
  - `GROQ_API_KEY`
  - `DATABASE_URL` (PostgreSQL)
  - `ALLOWED_ORIGINS`
- Health check: `/health`
- API metadata: `/meta/frameworks`

## Project Structure


```
