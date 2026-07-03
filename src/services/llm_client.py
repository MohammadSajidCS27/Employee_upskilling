import logging
from typing import Any
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

class GroqClient:
    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    FALLBACK_MODEL = "llama-3.1-8b-instant"

    def __init__(self, api_key: str = None, model: str = None):
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key
        if not api_key:
            logger.warning("No Groq API key provided, using mock mode")
            self.client = None
        else:
            self.client = ChatGroq(api_key=api_key, model_name=self.model)

    def _swap_to_fallback_model(self) -> None:
        if not self.api_key or self.model == self.FALLBACK_MODEL:
            return
        logger.warning("Switching Groq model from %s to fallback model %s", self.model, self.FALLBACK_MODEL)
        self.model = self.FALLBACK_MODEL
        self.client = ChatGroq(api_key=self.api_key, model_name=self.model)

    def invoke(self, prompt: str) -> Any:
        if not self.client:
            # Mock mode - return empty structure
            class MockResponse:
                content = "{}"
            return MockResponse()
        try:
            return self.client.invoke([HumanMessage(content=prompt)])
        except Exception as exc:
            message = str(exc).lower()
            if "decommissioned" in message or "model" in message and "not supported" in message:
                self._swap_to_fallback_model()
                return self.client.invoke([HumanMessage(content=prompt)])
            raise