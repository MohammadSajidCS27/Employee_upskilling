from __future__ import annotations

from typing import Dict, List


def unique_lower(values: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def parse_csv(raw: str) -> List[str]:
    return unique_lower(raw.split(","))


def default_skill_catalog() -> List[str]:
    return [
        "python", "java", "javascript", "react", "angular", "vue", "node",
        "spring", "docker", "kubernetes", "aws", "azure", "gcp", "sql",
        "nosql", "mongodb", "postgresql", "mysql", "redis", "kafka",
        "tensorflow", "pytorch", "langchain", "llm", "ai", "ml", "git", "rest",
    ]


def default_education_keywords() -> List[str]:
    return ["bachelor", "master", "phd", "degree", "computer science", "engineering"]


def default_role_keywords() -> List[str]:
    return ["developer", "engineer", "architect", "manager", "analyst", "designer"]


def default_market_keywords() -> List[str]:
    # Build master list combining general and role-specific keywords
    keywords = [
        # Core languages & frameworks
        "python", "java", "javascript", "typescript", "react", "next.js", "vue", "angular",
        "spring", "django", "flask", "nodejs", "express", "fastapi",
        # Cloud & infrastructure
        "cloud", "docker", "kubernetes", "aws", "gcp", "azure", "terraform", "ansible",
        "helm", "istio", "linkerd", "serverless", "lambda", "cloudformation",
        # AI/ML & emerging tech
        "ai", "ml", "llm", "rag", "genai", "langchain", "llamaindex", "transformers",
        "machine learning", "deep learning", "tensorflow", "pytorch", "keras", "onnx",
        "computer vision", "nlp", "generative ai", "agentic ai", "ai agents",
        # Data & databases
        "sql", "nosql", "mongodb", "postgresql", "redis", "kafka", "spark", "hadoop",
        "elasticsearch", "graphql", "prisma", "supabase",
        # DevOps & tooling
        "devops", "ci/cd", "jenkins", "gitlab ci", "github actions", "argo cd",
        "testing", "pytest", "jest", "cypress", "playwright", "selenium",
        # Microservices & architecture
        "api", "microservices", "grpc", "websocket", "webhook",
        # Security & monitoring
        "security", "cybersecurity", "oauth", "jwt", "zero trust", "api security",
        "prometheus", "grafana", "logging", "observability",
        # Frontend modern stack
        "tailwind", "sass", "webpack", "vite", "esbuild", "swc",
        "redux", "zustand", "tanstack query", "react query",
        # Role-specific keywords (for matching)
        "senior software engineer", "senior ai engineer", "senior ux engineer",
        "java developer", "frontend developer",
    ]
    return keywords


def default_onet_trending_skills() -> List[str]:
    return [
        "ai agent development", "agentic ai", "rag",
        "generative ai", "llmops", "mlops", "ai safety", "prompt engineering",
        "cloud native", "kubernetes", "docker", "serverless", "edge computing",
        "quantum computing", "web3", "blockchain", "defi",
        "python", "typescript", "next.js", "react", "vue", "svelte",
        "spring boot 3", "quarkus", "micronaut",
        "machine learning", "deep learning", "computer vision", "nlp",
        "data engineering", "data pipelines", "apache spark", "kafka streams",
    ]


def default_github_languages() -> List[str]:
    return [
        "python", "javascript", "typescript", "java", "go", "rust", "kotlin", "swift",
        "c#", "cpp", "ruby", "php", "scala", "r", "julia", "zig", "nim",
    ]


def default_youtube_keywords() -> List[str]:
    return [
        "ai agent tutorial", "rag development", "llm tutorial", "generative ai",
        "python tutorial", "javascript react", "java spring boot", "kubernetes docker",
        "aws cloud tutorial", "machine learning", "cybersecurity", "devops ci cd",
        "next.js tutorial", "vue.js tutorial", "docker kubernetes", "terraform aws",
        "prompt engineering", "ai agents", "langchain tutorial", "llamaindex",
    ]


def default_esco_role_skill_map() -> Dict[str, List[str]]:
    return {
        "java developer": ["java", "spring", "sql", "docker", "hibernate", "maven", "gradle", "git", "testing"],
        "software developer": ["python", "java", "javascript", "sql", "docker", "git", "api", "rest"],
        "software engineer": ["python", "java", "javascript", "sql", "docker", "kubernetes", "aws", "azure", "gcp"],
        "web developer": ["javascript", "html", "css", "react", "angular", "vue", "nodejs", "api"],
        "data scientist": ["python", "pandas", "numpy", "sql", "machine learning", "tensorflow", "pytorch"],
        "ai engineer": ["python", "tensorflow", "pytorch", "llm", "rag", "machine learning", "docker"],
    }


def default_onet_occupation_skill_map() -> Dict[str, List[str]]:
    return {
        "software developer": ["programming", "software development", "sql", "testing", "debugging", "java", "python", "javascript"],
        "java developer": ["java", "spring", "sql", "hibernate", "maven", "testing"],
        "ai engineer": ["python", "machine learning", "tensorflow", "pytorch", "statistics", "data science"],
        "data scientist": ["python", "statistics", "machine learning", "sql", "r", "data analysis"],
        "cloud architect": ["aws", "azure", "gcp", "docker", "kubernetes", "terraform"],
    }


def default_role_trending_skills() -> Dict[str, List[str]]:
    return {
        "senior software engineer": [
            "ai", "llm", "rag", "genai", "agentic ai", "github copilot", "ai pair programming",
            "next.js", "svelte", "astro", "qwik", "tanstack query", "zustand",
            "tRPC", "wasm", "webassembly", "edge functions", "serverless",
            "argo cd", "helm", "terraform cloud", "pulumi", "nomad",
            "bun", "deno", "turborepo", "nx", "biome",
        ],
        "senior ai engineer": [
            "rag", "llmops", "agentic ai", "ai agents", "prompt engineering", "fine tuning",
            "transformers", "llamaindex", "vllm", "ollama", "deepspeed", "unsloth",
            "crewai", "autogen", "langgraph", "llm orchestration", "vector databases",
            "pgvector", "pinecone", "weaviate", "qdrant", "milvus",
            "llm security", "ai safety", "alignment", "guardrails",
        ],
        "senior ux engineer": [
            "figma ai", "framer", "shadcn ui", "radix ui", "aceternity ui",
            "tailwind", "tailwindcss", "motion", "framer motion", "lottie",
            "design systems", "component libraries", "storybook", "chromatic",
            "accessibility ai", "axe core", "inclusive design", "dark mode",
            "microinteractions", "neumorphism", "glassmorphism",
        ],
        "java developer": [
            "spring boot 3", "spring ai", "quarkus", "micronaut", "graalvm",
            "virtual threads", "lombok", "mapstruct", "modulithic",
            "java 21", "java 22", "pattern matching",
        ],
        "frontend developer": [
            "next.js 15", "react server components", "app router", "tanstack router",
            "sveltekit", "svelte 5", "runes", "astro", "qwik", "remix",
            "tailwindcss", "shadcn", "radix", "framer motion", "motion one",
        ],
    }