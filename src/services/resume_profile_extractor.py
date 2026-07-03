from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


class ResumeProfileExtractor:
    SECTION_ALIASES = {
        "professional summary": "summary",
        "summary": "summary",
        "profile summary": "summary",
        "technical skills": "skills",
        "skills": "skills",
        "core skills": "skills",
        "professional experience": "experience",
        "work experience": "experience",
        "experience": "experience",
        "employment history": "experience",
        "education": "education",
        "certifications": "certifications",
        "certification": "certifications",
        "projects": "projects",
        "languages": "languages",
        "achievements": "achievements",
        "volunteering": "volunteering",
        "interests and hobbies": "interests",
        "interests": "interests",
        "hobbies": "interests",
    }

    ROLE_HINTS = {
        "developer",
        "engineer",
        "architect",
        "manager",
        "analyst",
        "designer",
        "scientist",
        "consultant",
        "programmer",
        "specialist",
        "lead",
        "administrator",
    }

    ROLE_BLOCKLIST = {
        "summary",
        "experience",
        "education",
        "certifications",
        "projects",
        "skills",
        "languages",
        "responsibilities",
        "qualifications",
        "contact",
        "linkedin",
        "email",
        "phone",
    }

    DEGREE_HINTS = (
        "bachelor",
        "master",
        "phd",
        "associate",
        "b.tech",
        "m.tech",
        "b.e",
        "m.e",
        "bsc",
        "msc",
        "computer science",
        "engineering",
    )

    DEGREE_LINE_HINTS = (
        "bachelor",
        "master",
        "phd",
        "associate",
        "b.tech",
        "m.tech",
        "b.e",
        "m.e",
        "bsc",
        "msc",
    )

    ACRONYM_MAP = {
        "ai": "AI",
        "ml": "ML",
        "qa": "QA",
        "ui": "UI",
        "ux": "UX",
        "devops": "DevOps",
        "sre": "SRE",
        "ios": "iOS",
    }

    def __init__(
        self,
        skill_catalog: Sequence[str],
        role_keywords: Sequence[str],
        education_keywords: Sequence[str],
        skill_normalizer: Any,
    ) -> None:
        self.skill_catalog = [item.strip().lower() for item in skill_catalog if item.strip()]
        self.role_keywords = {item.strip().lower() for item in role_keywords if item.strip()}
        self.education_keywords = [item.strip().lower() for item in education_keywords if item.strip()]
        self.skill_normalizer = skill_normalizer

    def extract(self, resume_text: str, default_role_title: str) -> Dict[str, Any]:
        normalized_text = self._normalize_text(resume_text)
        lines = self._split_lines(normalized_text)
        sections = self._group_sections(lines)

        return {
            "role": self.extract_role(normalized_text, lines, sections, default_role_title),
            "experience": self.extract_experience(normalized_text, sections),
            "skills": self.extract_skills(normalized_text, sections),
            "education": self.extract_education(lines, sections),
        }

    def extract_role(
        self,
        text: str,
        lines: Optional[List[str]] = None,
        sections: Optional[Dict[str, List[str]]] = None,
        default_role_title: str = "Software Developer",
    ) -> str:
        lines = lines or self._split_lines(self._normalize_text(text))
        sections = sections or self._group_sections(lines)

        candidates: List[Tuple[int, str]] = []

        for index, line in enumerate(lines[:8]):
            candidate = self._candidate_from_line(line)
            if candidate:
                score = 120 - (index * 10)
                if index == 1:
                    score += 10
                candidates.append((score, candidate))

        for index, line in enumerate(sections.get("experience", [])[:10]):
            for part_index, segment in enumerate(self._split_experience_line(line)):
                candidate = self._candidate_from_line(segment)
                if candidate:
                    score = 90 - (index * 4) - (part_index * 2)
                    candidates.append((score, candidate))

        summary_text = " ".join(sections.get("summary", [])[:4])
        for match in re.findall(
            r"\b(?:as|aspires to join .*? as|worked as|serving as)\s+(?:a\s+|an\s+)?([A-Za-z][A-Za-z/&\-\s]{3,60})",
            summary_text,
            re.IGNORECASE,
        ):
            candidate = self._candidate_from_line(match)
            if candidate:
                candidates.append((70, candidate))

        if candidates:
            best = max(candidates, key=lambda item: (item[0], len(item[1])))[1]
            
            inferred = self._infer_role_from_skills(sections, lines)
            if inferred and inferred != best:
                generic_roles = {"software engineer", "software developer", "associate software engineer", "software professional"}
                if best.lower() in generic_roles and inferred.lower() not in generic_roles:
                    return inferred
            
            return best

        for line in lines[:12]:
            lowered = line.lower()
            for keyword in sorted(self.role_keywords, key=len, reverse=True):
                if re.search(self._boundary_pattern(keyword), lowered):
                    candidate = self._candidate_from_line(line)
                    if candidate:
                        return candidate

        inferred = self._infer_role_from_skills(sections, lines)
        if inferred:
            return inferred

        return default_role_title

    def _infer_role_from_skills(self, sections: Dict[str, List[str]], lines: List[str]) -> Optional[str]:
        skill_text = " ".join(sections.get("skills", []) + lines[:30]).lower()
        
        role_skill_map = {
            "UI Developer": ["react", "angular", "vue", "javascript", "typescript", "html", "css", "frontend", "ui", "ux", "figma", "bootstrap", "tailwind", "responsive", "webpack", "sass", "less"],
            "DevOps Engineer": ["docker", "kubernetes", "jenkins", "terraform", "ansible", "aws", "azure", "gcp", "ci/cd", "devops", "sre", "linux", "bash", "helm", "prometheus", "grafana"],
            "QA Engineer": ["selenium", "junit", "testng", "pytest", "qa", "testing", "automation", "cucumber", "cypress", "jest", "mocha", "manual testing", "functional testing", "regression testing", "system testing", "integration testing", "api testing", "postman", "test case", "bug tracking", "smoke testing", "sanity testing", "test execution", "end-to-end testing", "cross-browser testing", "database validation", "istqb", "agile tester", "quality assurance", "sdet", "defect", "quality"],
            "Backend Developer": ["java", "spring", "spring boot", "python", "django", "flask", "node", "express", "microservices", "api", "rest", "backend", "sql", "postgresql", "mongodb"],
            "Data Engineer": ["spark", "hadoop", "kafka", "airflow", "etl", "data pipeline", "big data", "databricks", "snowflake"],
            "Full Stack Developer": ["react", "angular", "vue", "node", "express", "mongodb", "postgresql", "fullstack", "full-stack", "full stack"],
            "Mobile Developer": ["swift", "kotlin", "android", "ios", "flutter", "react native", "mobile"],
            "Cloud Engineer": ["aws", "azure", "gcp", "cloud", "terraform", "cloudformation", "serverless", "lambda"],
        }
        
        best_role = None
        best_score = 0
        for role, keywords in role_skill_map.items():
            score = sum(1 for kw in keywords if kw in skill_text)
            if score > best_score:
                best_score = score
                best_role = role
        
        if best_score >= 2:
            return best_role
        return None

    def extract_experience(self, text: str, sections: Optional[Dict[str, List[str]]] = None) -> int:
        explicit_years = [int(value) for value in re.findall(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", text, re.IGNORECASE)]
        if explicit_years:
            return max(explicit_years)

        lines = self._split_lines(self._normalize_text(text))
        sections = sections or self._group_sections(lines)
        experience_lines = sections.get("experience", []) or lines
        intervals = self._extract_date_intervals(experience_lines)
        if not intervals:
            intervals = self._extract_date_intervals(lines)
        if not intervals:
            return 0

        merged: List[Tuple[int, int]] = []
        for start, end in sorted(intervals):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
                continue
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))

        total_months = sum(max(0, end - start) for start, end in merged)
        return max(0, total_months // 12)

    def extract_skills(self, text: str, sections: Optional[Dict[str, List[str]]] = None) -> List[str]:
        normalized_text = self._normalize_text(text)
        lines = self._split_lines(normalized_text)
        sections = sections or self._group_sections(lines)

        collected: List[str] = []
        for line in sections.get("skills", []):
            collected.extend(self._extract_skill_tokens_from_line(line))

        for line in sections.get("projects", []):
            collected.extend(self._extract_skill_tokens_from_line(line))

        vocabulary = self._build_skill_vocabulary()

        lowered_text = normalized_text.lower()
        for skill in sorted(vocabulary, key=len, reverse=True):
            if not skill:
                continue
            if re.search(self._boundary_pattern(skill), lowered_text):
                collected.append(skill)

        normalized = self.skill_normalizer.normalize_list(collected)
        filtered = [item for item in normalized if item and len(item) > 1]
        return sorted(set(filtered))

    def extract_education(self, lines: List[str], sections: Optional[Dict[str, List[str]]] = None) -> List[str]:
        sections = sections or self._group_sections(lines)
        candidates = sections.get("education", []) or lines
        results: List[str] = []

        for line in candidates:
            lowered = line.lower()
            if any(hint in lowered for hint in self.DEGREE_LINE_HINTS):
                match = re.search(
                    r"(Bachelor[^,.\n]*|Master[^,.\n]*|PhD[^,.\n]*|Associate[^,.\n]*|B\.Tech[^,.\n]*|M\.Tech[^,.\n]*|B\.E[^,.\n]*|M\.E[^,.\n]*|BSc[^,.\n]*|MSc[^,.\n]*)",
                    line,
                    re.IGNORECASE,
                )
                cleaned = match.group(1).strip(" -") if match else line.strip(" -")
                cleaned = re.sub(r"\s+\[[^\]]+\]$", "", cleaned).strip()
                if cleaned and cleaned not in results:
                    results.append(cleaned)

        if results:
            return results

        fallback = [item for item in self.education_keywords if item in " ".join(lines).lower()]
        return fallback

    def is_valid_role(self, role: Any) -> bool:
        if not isinstance(role, str):
            return False
        candidate = self._candidate_from_line(role)
        return bool(candidate)

    def normalize_skills(self, skills: Any) -> List[str]:
        if not isinstance(skills, list):
            return []
        normalized = self.skill_normalizer.normalize_list([str(item).strip() for item in skills if str(item).strip()])
        return sorted(set(item for item in normalized if item))

    def normalize_education(self, education: Any) -> List[str]:
        if isinstance(education, str):
            education = [education]
        if not isinstance(education, list):
            return []
        seen = set()
        output: List[str] = []
        for item in education:
            value = str(item).strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            output.append(value)
        return output

    def _normalize_text(self, text: str) -> str:
        normalized = text.replace("\r", "\n")
        normalized = re.sub(r"[•●▪◦¢]", "-", normalized)
        normalized = re.sub(r"[\u2018\u2019]", "'", normalized)
        normalized = re.sub(r"[\u201c\u201d]", '"', normalized)
        normalized = re.sub(r"\n{2,}", "\n\n", normalized)
        return normalized

    def _split_lines(self, text: str) -> List[str]:
        lines = []
        for raw_line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", raw_line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines

    def _group_sections(self, lines: List[str]) -> Dict[str, List[str]]:
        sections: Dict[str, List[str]] = {"header": []}
        current = "header"
        for line in lines:
            heading = self._heading_name(line)
            if heading:
                current = heading
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        return sections

    def _heading_name(self, line: str) -> Optional[str]:
        lowered = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if lowered in self.SECTION_ALIASES:
            return self.SECTION_ALIASES[lowered]
        if line.isupper() and lowered in self.SECTION_ALIASES:
            return self.SECTION_ALIASES[lowered]
        return None

    def _candidate_from_line(self, line: str) -> Optional[str]:
        if not line:
            return None

        parts = [segment.strip() for segment in re.split(r"\s+[|@]\s+|\s+-\s+|\s+–\s+|[.;]", line) if segment.strip()]
        parts = parts or [line.strip()]

        for part in parts:
            lowered = part.lower()
            if self._looks_like_contact(part):
                continue
            if not any(re.search(self._boundary_pattern(token), lowered) for token in self.ROLE_HINTS | self.role_keywords):
                continue
            if re.search(r"\b(certification|certificate|academy|school|university)\b", lowered):
                continue

            match = re.search(
                r"([A-Za-z][A-Za-z/&+\-\s]{1,60}?(?:developer|engineer|architect|manager|analyst|designer|scientist|consultant|programmer|specialist|lead|administrator))\b",
                part,
                re.IGNORECASE,
            )
            if match:
                part = match.group(1)
                lowered = part.lower()

            if len(part.split()) > 8:
                continue

            if any(token in lowered for token in {"certification", "certificate", "summary", "education", "skills"}):
                continue

            cleaned = re.sub(r"[^A-Za-z0-9/&+\- ]", " ", part)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
            if not cleaned:
                continue
            # A genuine job title must contain a role noun (e.g. "engineer",
            # "developer"). Tech keywords such as "react" or "databases" can appear in
            # the workbook role vocabulary and pass the earlier hint check, so reject
            # candidates that are merely a list of skills with no real role noun.
            cleaned_lower = cleaned.lower()
            if not any(re.search(self._boundary_pattern(hint), cleaned_lower) for hint in self.ROLE_HINTS):
                continue
            return self._format_title(cleaned)
        return None

    def _looks_like_contact(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in ["@", "http", "www.", "linkedin", ".com", "+91", "(", ")"])

    def _split_experience_line(self, line: str) -> List[str]:
        return [segment.strip() for segment in re.split(r"\||@", line) if segment.strip()]

    def _extract_date_intervals(self, lines: Sequence[str]) -> List[Tuple[int, int]]:
        intervals: List[Tuple[int, int]] = []
        current_date = datetime.now(timezone.utc)
        current_value = current_date.year * 12 + current_date.month

        for line in lines:
            for match in re.finditer(
                r"(?P<start>(?:[A-Za-z]{3,9}\s+)?\d{4}|\d{1,2}/\d{4})\s*[-–]\s*(?P<end>present|current|now|(?:[A-Za-z]{3,9}\s+)?\d{4}|\d{1,2}/\d{4})",
                line,
                re.IGNORECASE,
            ):
                start = self._parse_date_token(match.group("start"))
                end_token = match.group("end")
                end = current_value if end_token.lower() in {"present", "current", "now"} else self._parse_date_token(end_token)
                if start is None or end is None or end <= start:
                    continue
                intervals.append((start, end))
        return intervals

    def _parse_date_token(self, value: str) -> Optional[int]:
        token = value.strip().lower()
        month_map = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }

        if re.fullmatch(r"\d{1,2}/\d{4}", token):
            month, year = token.split("/")
            return int(year) * 12 + int(month)

        parts = token.split()
        if len(parts) == 2 and parts[0][:3] in month_map and parts[1].isdigit():
            return int(parts[1]) * 12 + month_map[parts[0][:3]]

        if token.isdigit() and len(token) == 4:
            return int(token) * 12 + 1

        return None

    def _extract_skill_tokens_from_line(self, line: str) -> List[str]:
        vocabulary = self._build_skill_vocabulary()
        candidate = line
        if ":" in line:
            candidate = line.split(":", 1)[1]
        candidate = candidate.replace("/", ",")
        candidate = candidate.replace("|", ",")
        pieces = [piece.strip(" .-") for piece in candidate.split(",") if piece.strip(" .-")]

        output: List[str] = []
        for piece in pieces:
            lowered = piece.lower()
            if len(piece.split()) > 5 and " " in piece:
                continue
            if lowered in self.SECTION_ALIASES:
                continue
            output.extend(self._match_known_skills(lowered, vocabulary))
        return output

    def _build_skill_vocabulary(self) -> set[str]:
        vocabulary = set(self.skill_catalog)

        # Add decomposed variants from compound workbook terms (/, (), -, commas).
        expanded_terms: set[str] = set()
        for term in list(vocabulary):
            cleaned = str(term or "").strip().lower()
            if not cleaned:
                continue
            expanded_terms.add(cleaned)

            base = re.sub(r"\([^)]*\)", "", cleaned).strip()
            if base:
                expanded_terms.add(base)

            for part in re.split(r"/|,|\||\band\b", cleaned):
                piece = re.sub(r"\([^)]*\)", "", part).strip()
                if piece and len(piece) > 1:
                    expanded_terms.add(piece)

            paren = re.findall(r"\(([^)]*)\)", cleaned)
            for group in paren:
                for piece in re.split(r"/|,|\||\band\b", group):
                    token = piece.strip()
                    if token and len(token) > 1:
                        expanded_terms.add(token)

        vocabulary.update(expanded_terms)
        vocabulary.update(self.skill_normalizer.skill_mappings.keys())
        vocabulary.update(self.skill_normalizer.skill_mappings.values())
        for canonical, synonyms in self.skill_normalizer.synonym_map.items():
            vocabulary.add(canonical.lower())
            vocabulary.update(item.lower() for item in synonyms)
        vocabulary.update(
            {
                "node.js",
                "spring boot",
                "rest apis",
                "microservices",
                "ci/cd",
                "ci cd",
                "continuous integration",
                "continuous deployment",
                "gitlab ci",
                "jenkins",
                "api security",
                "service mesh",
                "service mesh security",
                "grpc",
                "bootstrap",
                "maven",
                "php",
                "html",
                "css",
                "jquery",
                "next.js",
                "nextjs",
                "tailwind",
                "tailwindcss",
                "html5",
                "css3",
                "sass",
                "scss",
                "less",
                "webpack",
                "babel",
                "gulp",
                "grunt",
                "npm",
                "yarn",
                "redux",
                "ngrx",
                "vuex",
                "jest",
                "mocha",
                "cypress",
                "selenium",
                "material ui",
                "ant design",
                "figma",
                "sketch",
                "wcag",
                "accessibility",
                "flexbox",
                "grid",
                "responsive",
                "web design",
                "prototyping",
                "user research",
                "agile",
                "scrum",
                "kanban",
                "jira",
                "confluence",
                "cross-browser",
                "performance optimization",
                "lazy loading",
                "minification",
                "image optimization",
                "csp",
                "xss",
                "authentication",
                "authorization",
                "oauth",
                "jwt",
                "sso",
                "a/b testing",
                "micro frontend",
                "microfrontend",
                "figma",
                "sketch",
                "material design",
                "fluent design",
                "manual testing",
                "functional testing",
                "regression testing",
                "system testing",
                "integration testing",
                "api testing",
                "postman",
                "test case design",
                "bug tracking",
                "smoke testing",
                "sanity testing",
                "test execution",
                "end-to-end testing",
                "cross-browser testing",
                "database validation",
                "istqb",
                "agile tester",
                "quality assurance",
                "sdet",
                "automation testing",
                "testng",
                "pytest",
                "cucumber",
                "junit",
                "defect tracking",
                "test scenario",
                "test plan",
                "test strategy",
                "uat",
                "user acceptance testing",
                "load testing",
                "stress testing",
                "security testing",
                "penetration testing",
                "performance testing",
                "jmeter",
                "loadrunner",
                "bugzilla",
                "mantis",
                "trello",
                "azure devops",
                "bitbucket",
                "svn",
                "mercurial",
                "coaching",
                "mentoring",
                "facilitation",
                "conflict resolution",
                "stakeholder management",
                "servant leadership",
                "change management",
                "agile transformation",
                "scaled agile",
                "safe",
                "less",
                "product vision",
                "roadmap development",
                "backlog prioritization",
                "story point estimation",
                "retrospectives",
                "feedback loops",
                "process optimization",
                "risk management",
                "program management",
                "project management",
                "budgeting",
                "contracting",
                "devops practices",
                "continuous deployment",
                "continuous integration",
                "ci/cd",
                "cd/ci",
            }
        )
        return vocabulary

    def _match_known_skills(self, text: str, vocabulary: set[str]) -> List[str]:
        matches: List[str] = []
        cleaned = re.sub(r"\s+", " ", text).strip()
        for skill in sorted(vocabulary, key=len, reverse=True):
            if skill and re.search(self._boundary_pattern(skill), cleaned):
                matches.append(skill)
        return matches

    def _boundary_pattern(self, token: str) -> str:
        return rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])"

    def _format_title(self, text: str) -> str:
        words = []
        for word in text.split():
            lowered = word.lower()
            if lowered in self.ACRONYM_MAP:
                words.append(self.ACRONYM_MAP[lowered])
            else:
                words.append(word.capitalize())
        return " ".join(words)