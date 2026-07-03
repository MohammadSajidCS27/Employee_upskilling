"""Resume extraction tools for LangChain agents."""
import logging
import tempfile
from typing import Any, Optional
from pathlib import Path
from src.services.resume_profile_extractor import ResumeProfileExtractor
from src.services.skill_normalizer import SkillNormalizer
from src.services.dynamic_defaults import (
    default_education_keywords,
    default_role_keywords,
    default_skill_catalog,
)
import pdfplumber

logger = logging.getLogger(__name__)


class ResumeTools:
    """Suite of resume extraction tools for agents."""

    def __init__(self, workbook_repo: Optional[Any] = None):
        skill_catalog = list(default_skill_catalog())
        role_keywords = list(default_role_keywords())

        if workbook_repo is not None:
            try:
                skill_catalog.extend(workbook_repo.get_all_skills())
                role_keywords.extend(workbook_repo.get_role_keywords())
                logger.info(
                    "ResumeTools initialized with workbook vocabulary (skills=%s roles=%s)",
                    len(skill_catalog),
                    len(role_keywords),
                )
            except Exception as error:
                logger.warning("Workbook vocabulary unavailable for ResumeTools: %s", error)

        self.skill_normalizer = SkillNormalizer()
        self.profile_extractor = ResumeProfileExtractor(
            skill_catalog=skill_catalog,
            role_keywords=role_keywords,
            education_keywords=default_education_keywords(),
            skill_normalizer=self.skill_normalizer,
        )

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text content from the PDF
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            
            if text.strip():
                logger.info(f"Extracted {len(text)} characters from PDF")
                return text
            else:
                logger.error(f"No text extracted from {pdf_path}")
                return ""
        except Exception as e:
            logger.error(f"Error extracting PDF: {e}")
            raise ValueError(f"Failed to extract text from PDF: {e}")

    def extract_text_from_pdf_bytes(self, pdf_bytes: bytes, filename: str = "upload.pdf") -> str:
        """
        Extract text from PDF bytes (for uploaded files).
        
        Args:
            pdf_bytes: Raw PDF file bytes
            filename: Original filename for temp file naming
            
        Returns:
            Extracted text content from the PDF
        """
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", prefix=f"resume_{filename}_", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name
            
            try:
                extracted = self.extract_text_from_pdf(tmp_path)
                return extracted
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Error extracting PDF from bytes: {e}")
            raise ValueError(f"Failed to extract text from PDF: {e}")

    def extract_role_from_resume(self, resume_text: str) -> str:
        """
        Extract job role/title from resume text.
        
        Args:
            resume_text: The resume content as text
            
        Returns:
            The extracted job role
        """
        try:
            role = self.profile_extractor.extract_role(resume_text)
            logger.info(f"Extracted role: {role}")
            return role
        except Exception as e:
            logger.error(f"Error extracting role: {e}")
            raise

    def extract_experience_from_resume(self, resume_text: str) -> int:
        """
        Extract years of experience from resume text.
        
        Args:
            resume_text: The resume content as text
            
        Returns:
            Number of years of experience
        """
        try:
            experience = self.profile_extractor.extract_experience(resume_text)
            logger.info(f"Extracted experience: {experience} years")
            return experience
        except Exception as e:
            logger.error(f"Error extracting experience: {e}")
            raise

    def extract_skills_from_resume(self, resume_text: str) -> list:
        """
        Extract technical skills from resume text.
        
        Args:
            resume_text: The resume content as text
            
        Returns:
            List of technical skills
        """
        try:
            skills = self.profile_extractor.extract_skills(resume_text)
            logger.info(f"Extracted {len(skills)} skills")
            return skills
        except Exception as e:
            logger.error(f"Error extracting skills: {e}")
            raise

    def extract_education_from_resume(self, resume_text: str) -> list:
        """
        Extract education background from resume text.
        
        Args:
            resume_text: The resume content as text
            
        Returns:
            List of education entries
        """
        try:
            lines = self.profile_extractor._split_lines(resume_text)
            education = self.profile_extractor.extract_education(lines)
            logger.info(f"Extracted {len(education)} education entries")
            return education
        except Exception as e:
            logger.error(f"Error extracting education: {e}")
            raise

    def normalize_skills(self, skills: list) -> list:
        """
        Normalize skill names.
        
        Args:
            skills: List of skill names
            
        Returns:
            Normalized skill list
        """
        try:
            normalized = self.skill_normalizer.normalize_list(skills)
            logger.info(f"Normalized {len(skills)} skills")
            return normalized
        except Exception as e:
            logger.error(f"Error normalizing skills: {e}")
            raise

    def get_tools(self):
        """Return all tools as a list for agent."""
        return [
            self.extract_text_from_pdf,
            self.extract_text_from_pdf_bytes,
            self.extract_role_from_resume,
            self.extract_experience_from_resume,
            self.extract_skills_from_resume,
            self.extract_education_from_resume,
            self.normalize_skills,
        ]
