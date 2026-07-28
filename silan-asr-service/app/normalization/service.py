import logging
import re
from typing import Dict, List
from app.config.settings import NormalizationConfig


logger = logging.getLogger(__name__)


class NormalizationService:
    def __init__(self, config: NormalizationConfig = None):
        self.config = config or NormalizationConfig()
        self.term_corrections: Dict[str, str] = {}
        self.entity_patterns: Dict[str, re.Pattern] = {}
        
        self._load_industry_terms()
    
    def _load_industry_terms(self) -> None:
        if not self.config.industry_term_file:
            return
        
        try:
            with open(self.config.industry_term_file, "r", encoding="utf-8") as f:
                lines = f.read().strip().split("\n")
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split("=")
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip()
                    self.term_corrections[key] = value
                else:
                    self.term_corrections[line] = line
            
            logger.info(f"Loaded {len(self.term_corrections)} industry terms")
        except Exception as e:
            logger.warning(f"Failed to load industry terms: {e}")
    
    def normalize(self, text: str) -> str:
        if not text:
            return text
        
        text = self._apply_term_corrections(text)
        
        if self.config.enable_entity_recognition:
            text = self._apply_entity_recognition(text)
        
        return text
    
    def _apply_term_corrections(self, text: str) -> str:
        for wrong, correct in self.term_corrections.items():
            if wrong in text:
                text = text.replace(wrong, correct)
        
        text = self._apply_special_corrections(text)
        
        return text
    
    def _apply_special_corrections(self, text: str) -> str:
        corrections = [
            (r"HBM\s*三\s*E", "HBM3E"),
            (r"HBM\s*3\s*E", "HBM3E"),
            (r"co\s*boss", "CoWoS"),
            (r"Co\s*Boss", "CoWoS"),
            (r"co\s*bos", "CoWoS"),
        ]
        
        for pattern, replacement in corrections:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        return text
    
    def _apply_entity_recognition(self, text: str) -> str:
        entities = self._extract_entities(text)
        
        for entity, entity_type in entities:
            if entity_type == "technology":
                text = self._highlight_entity(text, entity, "[TECH]")
            elif entity_type == "company":
                text = self._highlight_entity(text, entity, "[COMPANY]")
        
        return text
    
    def _extract_entities(self, text: str) -> list:
        entities = []
        
        company_keywords = ["TSMC", "Samsung", "Intel", "NVIDIA", "AMD", 
                           "Huawei", "SMIC", "GlobalFoundries"]
        
        tech_keywords = ["EUV", "HBM", "CoWoS", "FinFET", "GAA", "Chiplet"]
        
        for keyword in company_keywords:
            if keyword.lower() in text.lower():
                entities.append((keyword, "company"))
        
        for keyword in tech_keywords:
            if keyword.lower() in text.lower():
                entities.append((keyword, "technology"))
        
        return entities
    
    def _highlight_entity(self, text: str, entity: str, tag: str) -> str:
        return text.replace(entity, f"{tag}{entity}{tag}")
    
    def add_term(self, wrong: str, correct: str) -> None:
        self.term_corrections[wrong] = correct
    
    def remove_term(self, term: str) -> None:
        self.term_corrections.pop(term, None)
