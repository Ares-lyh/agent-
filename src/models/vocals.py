"""Human vocal direction, kept independent of a model's arrangement prose."""
from typing import Literal
from src.models.common import Contract


class VocalRequirements(Contract):
    lead: Literal["female", "male", "mixed", "unspecified"] = "unspecified"
    style: str = ""
    source: Literal["brief", "references", "feedback", "unspecified"] = "unspecified"

    def instruction(self):
        directions = {
            "female": "Solo FEMALE lead vocals throughout the entire song, female singer in every verse, chorus and bridge. 全曲女声主唱，各段保持女声音色，高潮保持女声，不改成男声喊唱；不要男声主唱、男声念白或男女对唱。",
            "male": "Solo MALE lead vocals throughout the entire song. 全曲男声主唱，各段保持男声音色，不要女声主唱或男女对唱。",
            "mixed": "Male and female duet vocals. 男女对唱。",
            "unspecified": "",
        }
        timbre = ("Ethereal, airy and breathy singing, clear Mandarin articulation, light head voice; preserve the vocal identity in the powerful chorus."
                  if any(word in self.style.lower() for word in ("空灵", "ethereal", "airy")) else "")
        return " ".join(filter(None, (directions[self.lead], self.style, timbre)))


class AudioGenerationIntent(Contract):
    project_id: str
    version: str
    provider: str
    prompt: str
    vocal_requirements: VocalRequirements
